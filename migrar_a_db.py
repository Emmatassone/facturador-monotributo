"""
Migra los datos locales (config.json, clientes.json, claves/, resultados/)
a la base de datos PostgreSQL. Se corre UNA sola vez.

    .venv\\Scripts\\python migrar_a_db.py
"""
import csv
import glob
import json
import os

import db


def migrar_config() -> None:
    with open("config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    db.set_config("ambiente", cfg["ambiente"])
    db.set_config("tope_consumidor_final_digital",
                  str(cfg["tope_consumidor_final_digital"]))
    db.set_config("tope_consumidor_final_efectivo",
                  str(cfg["tope_consumidor_final_efectivo"]))
    e = cfg["email"]
    db.set_config("email_habilitado", "true" if e["habilitado"] else "false")
    db.set_config("email_smtp_host", e["smtp_host"])
    db.set_config("email_smtp_port", str(e["smtp_port"]))
    db.set_config("email_usuario", e["usuario"])
    db.set_config("email_password", e["password"])
    db.set_config("email_destinatario", e["destinatario"])
    print("config migrada")


def migrar_clientes() -> None:
    with open("clientes.json", encoding="utf-8") as f:
        clientes = json.load(f)
    for cli in clientes:
        cert_pem = ""
        clave_pem = ""
        if cli.get("certificado") and os.path.exists(cli["certificado"]):
            with open(cli["certificado"], encoding="utf-8") as f:
                cert_pem = f.read()
        if cli.get("clave_privada") and os.path.exists(cli["clave_privada"]):
            with open(cli["clave_privada"], encoding="utf-8") as f:
                clave_pem = f.read()
        db.crear_cliente({
            "cuit": cli["cuit"],
            "nombre": cli["nombre"],
            "activo": bool(cli.get("activo", True)),
            "punto_de_venta": cli["punto_de_venta"],
            "tipo_comprobante": cli["tipo_comprobante"],
            "concepto": cli["concepto"],
            "descripcion": cli.get("descripcion", ""),
            "monto": cli["monto"],
            "medio_pago": cli.get("medio_pago", "digital"),
            "doc_tipo": cli.get("doc_tipo", 99),
            "doc_nro": cli.get("doc_nro", 0),
            "condicion_iva_receptor": cli.get("condicion_iva_receptor", 5),
            "certificado": cert_pem,
            "clave_privada": clave_pem,
        })
        print(f"cliente migrado: {cli['nombre']} (CUIT {cli['cuit']}) "
              f"cert={'OK' if cert_pem else 'falta'} key={'OK' if clave_pem else 'falta'}")


def migrar_emisiones() -> None:
    total = 0
    for ruta in sorted(glob.glob(os.path.join("resultados", "facturas_*.csv"))):
        with open(ruta, newline="", encoding="utf-8") as f:
            for fila in csv.DictReader(f):
                db.registrar_emision(fila)
                total += 1
    print(f"emisiones migradas: {total}")


if __name__ == "__main__":
    db.init_db()
    print("tablas creadas/verificadas")
    migrar_config()
    migrar_clientes()
    migrar_emisiones()
    print("\nMigracion completa.")
