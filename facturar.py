"""
Facturador mensual multi-cliente para monotributos (uso local).

Los datos (clientes, certificados, config, historial) viven en la base de
datos PostgreSQL (ver db.py) — el codigo no contiene informacion sensible.

Por cada cliente activo:
  1. Valida el monto contra los topes de Consumidor Final sin identificar.
  2. Se autentica en WSAA con el certificado propio de ese CUIT.
  3. Consulta el ultimo comprobante y emite el siguiente via WSFEv1.
  4. Registra el resultado en la tabla emisiones.

Uso:
    python facturar.py              -> emite las facturas de verdad
    python facturar.py --dry-run    -> NO emite; solo consulta el proximo numero
    python facturar.py --solo 20123456789   -> procesa un solo CUIT
"""
import argparse
import smtplib
import sys
import traceback
from datetime import datetime
from email.mime.text import MIMEText

import db
from wsaa import WSAA
from wsfe import WSFE


def validar_tope(cliente: dict, config: dict) -> str | None:
    """Devuelve un mensaje de error si el monto supera el tope y el comprador
    no esta identificado; None si esta todo bien."""
    if int(cliente.get("doc_nro") or 0) > 0:
        return None  # Identificado con DNI/CUIT: no aplica tope

    monto = float(cliente["monto"])
    medio = cliente.get("medio_pago", "digital")
    tope = (config["tope_consumidor_final_efectivo"] if medio == "efectivo"
            else config["tope_consumidor_final_digital"])

    if monto > tope:
        return (f"El monto ${monto:,.2f} supera el tope de ${tope:,.2f} para "
                f"Consumidor Final sin identificar (medio de pago: {medio}). "
                f"Identificar al comprador (doc_tipo/doc_nro).")
    return None


def procesar_cliente(cliente: dict, config: dict,
                     wsaa: WSAA, wsfe: WSFE, dry_run: bool) -> dict:
    cuit = cliente["cuit"]
    fila = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cuit": cuit,
        "nombre": cliente["nombre"],
        "punto_venta": cliente["punto_de_venta"],
        "tipo_cbte": cliente["tipo_comprobante"],
        "numero": "",
        "monto": cliente["monto"],
        "resultado": "",
        "cae": "",
        "cae_vencimiento": "",
        "detalle": "",
    }

    # --- Regla critica: tope de Consumidor Final ---
    error_tope = validar_tope(cliente, config)
    if error_tope:
        fila["resultado"] = "BLOQUEADO"
        fila["detalle"] = error_tope
        return fila

    crt_pem = (cliente.get("certificado") or "").encode()
    key_pem = (cliente.get("clave_privada") or "").encode()
    if not crt_pem or not key_pem:
        fila["resultado"] = "ERROR"
        fila["detalle"] = "Este CUIT no tiene certificado/clave cargados en la base"
        return fila

    # --- Autenticacion con el certificado de ESTE CUIT ---
    auth = wsaa.obtener_token_sign(cuit, crt_pem, key_pem)

    ultimo = wsfe.ultimo_comprobante(
        auth, cliente["punto_de_venta"], cliente["tipo_comprobante"])
    proximo = ultimo + 1
    fila["numero"] = proximo

    if dry_run:
        fila["resultado"] = "DRY-RUN"
        fila["detalle"] = f"Se emitiria el comprobante N {proximo}"
        return fila

    # --- Emision ---
    resp = wsfe.emitir_factura(
        auth=auth,
        punto_venta=cliente["punto_de_venta"],
        tipo_cbte=cliente["tipo_comprobante"],
        numero=proximo,
        monto=float(cliente["monto"]),
        concepto=cliente["concepto"],
        doc_tipo=cliente.get("doc_tipo", 99),
        doc_nro=cliente.get("doc_nro", 0),
        condicion_iva_receptor=cliente.get("condicion_iva_receptor", 5),
    )

    fila["cae"] = resp["cae"]
    fila["cae_vencimiento"] = resp["cae_vencimiento"]
    if resp["resultado"] == "A":
        fila["resultado"] = "APROBADA"
        obs = " | ".join(resp["observaciones"])
        fila["detalle"] = f"Obs: {obs}" if obs else "OK"
    else:
        fila["resultado"] = "RECHAZADA"
        fila["detalle"] = " | ".join(resp["observaciones"] + resp["errores"])
    return fila


def armar_reporte(filas: list[dict], dry_run: bool) -> str:
    titulo = ("REPORTE DE SIMULACION (dry-run)" if dry_run
              else "REPORTE DE FACTURACION")
    lineas = [titulo, f"Fecha: {datetime.now():%Y-%m-%d %H:%M}", "-" * 70]
    aprobadas = sum(1 for f in filas if f["resultado"] in ("APROBADA", "DRY-RUN"))
    for f in filas:
        nro = f"#{f['numero']}" if f["numero"] else "-"
        lineas.append(
            f"[{f['resultado']:>9}] {f['nombre']} (CUIT {f['cuit']}) "
            f"-> Comprobante {nro} ${float(f['monto']):,.2f} "
            f"CAE: {f['cae'] or '-'}")
        if f["detalle"] and f["resultado"] not in ("APROBADA",):
            lineas.append(f"             {f['detalle']}")
    lineas.append("-" * 70)
    lineas.append(f"Exitosas: {aprobadas}/{len(filas)}")
    return "\n".join(lineas)


def enviar_email(config: dict, asunto: str, cuerpo: str) -> None:
    cfg = config["email"]
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = cfg["usuario"]
    msg["To"] = cfg["destinatario"]
    with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"]) as smtp:
        smtp.login(cfg["usuario"], cfg["password"])
        smtp.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Facturador mensual multi-cliente")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simula sin emitir comprobantes")
    parser.add_argument("--solo", type=str, default=None,
                        help="Procesa unicamente el CUIT indicado")
    args = parser.parse_args()

    db.init_db()
    config = db.get_config()
    clientes = [c for c in db.get_clientes() if c.get("activo")]
    if args.solo:
        cuit = args.solo.replace("-", "")
        clientes = [c for c in clientes if str(c["cuit"]) == cuit]
        if not clientes:
            sys.exit(f"No hay cliente activo con CUIT {cuit}")

    print(f"Ambiente: {config['ambiente'].upper()} | "
          f"Clientes a procesar: {len(clientes)}"
          + (" | MODO DRY-RUN" if args.dry_run else ""))
    print()

    wsaa = WSAA(config["ambiente"])
    wsfe = WSFE(config["ambiente"])

    filas = []
    for cliente in clientes:
        print(f"Procesando {cliente['nombre']} (CUIT {cliente['cuit']})...", end=" ")
        try:
            fila = procesar_cliente(cliente, config, wsaa, wsfe, args.dry_run)
        except Exception as e:  # un cliente que falla NO frena al resto
            fila = {
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "cuit": cliente["cuit"], "nombre": cliente["nombre"],
                "punto_venta": cliente.get("punto_de_venta", ""),
                "tipo_cbte": cliente.get("tipo_comprobante", ""),
                "numero": "", "monto": cliente.get("monto", ""),
                "resultado": "ERROR", "cae": "", "cae_vencimiento": "",
                "detalle": f"{type(e).__name__}: {e}",
            }
            traceback.print_exc()
        filas.append(fila)
        db.registrar_emision(fila)
        print(fila["resultado"])

    print()
    reporte = armar_reporte(filas, args.dry_run)
    print(reporte)

    if config["email"].get("habilitado"):
        enviar_email(config, "Reporte de facturacion mensual", reporte)
        print("\nReporte enviado por email.")


if __name__ == "__main__":
    main()
