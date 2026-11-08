"""
Dashboard web local para el facturador multi-cliente.

    python app.py      ->  abrir http://localhost:5000

Los datos (clientes, certificados, historial) viven en PostgreSQL (db.py);
el codigo no contiene informacion sensible.

- Panel general: resumen, clientes, historial.
- Selector de cliente (por CUIT) -> ficha con su actividad fiscal consultada
  en vivo a ARCA y su historial de emisiones.
- Alta de clientes con subida de certificado/clave (se guardan en la base).
- Botones para facturar (real o simulacion), editar monto, ver PDF del
  comprobante con QR y verificarlo en ARCA.
"""
import io
from datetime import datetime

from flask import (Flask, flash, redirect, render_template_string, request,
                   send_file, url_for)

import db
from facturar import procesar_cliente
from pdf_comprobante import generar_pdf
from wsaa import WSAA
from wsfe import WSFE

app = Flask(__name__)
app.secret_key = "facturador-local-solo-para-flash"

# Cache de clientes WSAA/WSFE por ambiente (para no releer el WSDL en cada click)
_conexiones = {}

TIPOS_CBTE = {6: "Factura B", 11: "Factura C"}


def get_conexiones(ambiente: str):
    if ambiente not in _conexiones:
        _conexiones[ambiente] = (WSAA(ambiente), WSFE(ambiente))
    return _conexiones[ambiente]


def ejecutar(clientes: list[dict], dry_run: bool) -> None:
    config = db.get_config()
    wsaa, wsfe = get_conexiones(config["ambiente"])
    for cliente in clientes:
        try:
            fila = procesar_cliente(cliente, config, wsaa, wsfe, dry_run)
            db.registrar_emision(fila)
            nro = f"#{fila['numero']}" if fila["numero"] else ""
            if fila["resultado"] == "APROBADA":
                flash(f"✅ {cliente['nombre']}: Factura {nro} aprobada. "
                      f"CAE {fila['cae']}", "ok")
            elif fila["resultado"] == "DRY-RUN":
                flash(f"🔍 {cliente['nombre']}: se emitiría el comprobante {nro}",
                      "info")
            else:
                flash(f"⚠️ {cliente['nombre']}: {fila['resultado']} — "
                      f"{fila['detalle']}", "error")
        except Exception as e:
            flash(f"❌ {cliente['nombre']}: {type(e).__name__}: {e}", "error")


def actividad_fiscal(cliente: dict, config: dict) -> dict:
    """Consulta en vivo a ARCA: estado de servidores, puntos de venta
    y ultimo comprobante autorizado por tipo de factura."""
    crt_pem = (cliente.get("certificado") or "").encode()
    key_pem = (cliente.get("clave_privada") or "").encode()
    if not crt_pem or not key_pem:
        return {"error": "Este CUIT no tiene certificado/clave cargados "
                         "en la base de datos."}
    try:
        wsaa, wsfe = get_conexiones(config["ambiente"])
        auth = wsaa.obtener_token_sign(cliente["cuit"], crt_pem, key_pem)

        ultimos = []
        for tipo, nombre in TIPOS_CBTE.items():
            try:
                nro = wsfe.ultimo_comprobante(
                    auth, cliente["punto_de_venta"], tipo)
                ultimos.append({"tipo": nombre, "numero": nro})
            except Exception as e:
                ultimos.append({"tipo": nombre, "numero": f"error: {e}"})

        return {
            "dummy": wsfe.dummy(),
            "puntos_venta": wsfe.puntos_de_venta(auth),
            "ultimos": ultimos,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


HEAD = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Facturador Monotributo</title>
<style>
  :root { --ok:#16a34a; --err:#dc2626; --info:#2563eb; --bg:#f1f5f9; --card:#fff; }
  * { box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
         margin: 0; color: #1e293b; }
  header { background: #0f172a; color: #fff; padding: 16px 28px;
           display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
  header h1 { font-size: 20px; margin: 0; flex: 1; }
  header a { color: #fff; text-decoration: none; }
  .badge { padding: 4px 12px; border-radius: 999px; font-size: 13px;
           font-weight: 700; letter-spacing: .5px; }
  .badge.prod { background: var(--err); color: #fff; }
  main { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px,1fr));
           gap: 14px; margin-bottom: 24px; }
  .card { background: var(--card); border-radius: 12px; padding: 18px;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card .num { font-size: 28px; font-weight: 700; }
  .card .lbl { font-size: 13px; color: #64748b; margin-top: 4px; }
  .card .num.ok { color: var(--ok); } .card .num.err { color: var(--err); }
  table { width: 100%; border-collapse: collapse; background: var(--card);
          border-radius: 12px; overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 28px; }
  th, td { padding: 11px 14px; text-align: left; font-size: 14px; }
  th { background: #e2e8f0; font-size: 12px; text-transform: uppercase;
       letter-spacing: .5px; color: #475569; }
  tr + tr td { border-top: 1px solid #e2e8f0; }
  h2 { font-size: 17px; margin: 0 0 12px; }
  .pill { padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .pill.APROBADA { background: #dcfce7; color: #166534; }
  .pill.RECHAZADA, .pill.ERROR { background: #fee2e2; color: #991b1b; }
  .pill.BLOQUEADO { background: #fef3c7; color: #92400e; }
  .pill.DRY-RUN { background: #dbeafe; color: #1e40af; }
  .pill.off { background: #e2e8f0; color: #64748b; }
  .btn { border: none; border-radius: 8px; padding: 7px 14px; font-size: 13px;
         font-weight: 600; cursor: pointer; }
  .btn.emitir { background: var(--ok); color: #fff; }
  .btn.dry { background: #e2e8f0; color: #334155; }
  .btn.big { padding: 10px 20px; font-size: 14px; }
  .acciones { display: flex; gap: 8px; margin-bottom: 24px; flex-wrap: wrap;
              align-items: center; }
  .flash { padding: 12px 16px; border-radius: 10px; margin-bottom: 10px; font-size: 14px; }
  .flash.ok { background: #dcfce7; color: #166534; }
  .flash.error { background: #fee2e2; color: #991b1b; }
  .flash.info { background: #dbeafe; color: #1e40af; }
  .mut { color: #94a3b8; font-size: 12px; }
  form { display: inline; }
  select { padding: 9px 14px; border-radius: 8px; border: 1px solid #cbd5e1;
           font-size: 14px; background: #fff; min-width: 320px; cursor: pointer; }
  .volver { color: var(--info); text-decoration: none; font-size: 14px; }
  .dato { font-weight: 600; }
</style>
</head>
"""

SELECTOR = """
<select onchange="if(this.value) location.href='/cliente/'+this.value">
  <option value="">👤 Seleccionar cliente por CUIT…</option>
  {% for c in clientes %}
  <option value="{{ c.cuit }}" {{ 'selected' if seleccionado == c.cuit|string }}>
    {{ c.nombre }} — CUIT {{ c.cuit }}</option>
  {% endfor %}
</select>
"""

TEMPLATE = HEAD + """
<body>
<header>
  <h1><a href="/">🧾 Facturador Monotributo</a></h1>
  <span class="badge prod">PRODUCCIÓN — FACTURAS REALES</span>
</header>
<main>

{% with mensajes = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in mensajes %}
    <div class="flash {{ cat }}">{{ msg }}</div>
  {% endfor %}
{% endwith %}

<div class="cards">
  <div class="card"><div class="num">{{ stats.activos }}</div>
    <div class="lbl">Clientes activos</div></div>
  <div class="card"><div class="num ok">{{ stats.emitidas_mes }}</div>
    <div class="lbl">Facturas emitidas este mes</div></div>
  <div class="card"><div class="num ok">${{ "{:,.0f}".format(stats.facturado_mes) }}</div>
    <div class="lbl">Facturado este mes</div></div>
  <div class="card"><div class="num err">{{ stats.problemas_mes }}</div>
    <div class="lbl">Rechazadas / bloqueadas este mes</div></div>
</div>

<h2>Clientes</h2>
<div class="acciones">
  """ + SELECTOR + """
  <form method="post" action="{{ url_for('facturar_todos') }}"
        onsubmit="return confirm('¿Emitir facturas REALES a todos los clientes activos?')">
    <button class="btn emitir big">🧾 Facturar a todos</button>
  </form>
  <form method="post" action="{{ url_for('facturar_todos') }}">
    <input type="hidden" name="dry_run" value="1">
    <button class="btn dry big">🔍 Simular (dry-run)</button>
  </form>
  <a class="btn emitir big" style="text-decoration:none;" href="{{ url_for('nuevo_cliente') }}">➕ Nuevo cliente</a>
</div>

<table>
  <tr><th>Cliente</th><th>CUIT</th><th>Monto</th><th>Medio pago</th>
      <th>Emitidas (total)</th><th>Último resultado</th><th></th></tr>
  {% for c in clientes %}
  <tr>
    <td><a href="/cliente/{{ c.cuit }}"><b>{{ c.nombre }}</b></a>
        {% if not c.activo %}<span class="pill off">inactivo</span>{% endif %}</td>
    <td>{{ c.cuit }}</td>
    <td>${{ "{:,.2f}".format(c.monto) }}</td>
    <td>{{ c.medio_pago }}</td>
    <td>{{ c.emitidas_total }}</td>
    <td>{% if c.ultimo %}<span class="pill {{ c.ultimo }}">{{ c.ultimo }}</span>
        <div class="mut">{{ c.ultimo_fecha }}</div>{% else %}<span class="mut">—</span>{% endif %}</td>
    <td>{% if c.activo %}
      <form method="post" action="{{ url_for('facturar_uno', cuit=c.cuit) }}"
            onsubmit="return confirm('¿Emitir factura REAL a {{ c.nombre }} por ${{ "{:,.2f}".format(c.monto) }}?')">
        <button class="btn emitir">Facturar</button>
      </form>{% endif %}</td>
  </tr>
  {% endfor %}
</table>

<h2>Historial de emisiones</h2>
<table>
  <tr><th>Fecha</th><th>Cliente</th><th>Comprobante</th><th>Monto</th>
      <th>Resultado</th><th>CAE</th><th>Detalle</th><th></th></tr>
  {% for h in historial %}
  <tr>
    <td class="mut">{{ h.fecha }}</td>
    <td><a href="/cliente/{{ h.cuit }}">{{ h.nombre }}</a></td>
    <td>{{ '#' ~ h.numero if h.numero else '—' }}</td>
    <td>${{ h.monto }}</td>
    <td><span class="pill {{ h.resultado }}">{{ h.resultado }}</span></td>
    <td class="mut">{{ h.cae or '—' }}</td>
    <td class="mut">{{ h.detalle }}</td>
    <td>{% if h.resultado == 'APROBADA' and h.cae %}
      <a class="btn dry" href="{{ url_for('ver_pdf', cuit=h.cuit, numero=h.numero) }}" target="_blank">📄 PDF</a>
    {% endif %}</td>
  </tr>
  {% else %}
  <tr><td colspan="8" class="mut">Todavía no hay emisiones registradas.</td></tr>
  {% endfor %}
</table>

</main>
</body>
</html>
"""

DETALLE = HEAD + """
<body>
<header>
  <h1><a href="/">🧾 Facturador Monotributo</a></h1>
  <span class="badge prod">PRODUCCIÓN — FACTURAS REALES</span>
</header>
<main>

{% with mensajes = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in mensajes %}
    <div class="flash {{ cat }}">{{ msg }}</div>
  {% endfor %}
{% endwith %}

<p><a class="volver" href="/">← Volver al panel general</a></p>

<div class="acciones">
  """ + SELECTOR + """
</div>

<div class="cards">
  <div class="card"><div class="num">{{ emitidas_total }}</div>
    <div class="lbl">Facturas emitidas (total)</div></div>
  <div class="card"><div class="num ok">${{ "{:,.0f}".format(facturado_total) }}</div>
    <div class="lbl">Facturado (total histórico)</div></div>
  <div class="card"><div class="num ok">{{ emitidas_mes }}</div>
    <div class="lbl">Emitidas este mes</div></div>
  <div class="card"><div class="num">{{ cliente.punto_de_venta }}</div>
    <div class="lbl">Punto de venta configurado</div></div>
</div>

<h2>Datos de facturación</h2>
<table>
  <tr><td class="dato">Nombre</td><td>{{ cliente.nombre }}</td></tr>
  <tr><td class="dato">CUIT</td><td>{{ cliente.cuit }}</td></tr>
  <tr><td class="dato">Tipo de comprobante</td>
      <td>{{ tipo_cbte_nombre }} (código {{ cliente.tipo_comprobante }})</td></tr>
  <tr><td class="dato">Concepto</td>
      <td>{{ {1: 'Productos', 2: 'Servicios', 3: 'Productos y Servicios'}[cliente.concepto] }}</td></tr>
  <tr><td class="dato">Monto mensual</td>
      <td><form method="post" action="{{ url_for('editar_monto', cuit=cliente.cuit) }}"
                style="display:flex; gap:8px; align-items:center;">
            $ <input type="number" name="monto" value="{{ cliente.monto }}"
                     min="0" step="0.01" required
                     style="padding:7px 10px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; width:140px;">
            <button class="btn dry">💾 Guardar</button>
          </form></td></tr>
  <tr><td class="dato">Medio de pago</td><td>{{ cliente.medio_pago }}</td></tr>
  <tr><td class="dato">Certificado</td>
      <td>{{ '✅ cargado' if cliente.certificado else '❌ falta — no se puede facturar' }}</td></tr>
  <tr><td class="dato">Estado</td>
      <td>{{ 'Activo' if cliente.activo else 'Inactivo (no se le factura)' }}</td></tr>
</table>

<div class="acciones">
  {% if cliente.activo %}
  <form method="post" action="{{ url_for('facturar_uno', cuit=cliente.cuit) }}"
        onsubmit="return confirm('¿Emitir factura REAL a {{ cliente.nombre }} por ${{ "{:,.2f}".format(cliente.monto) }}?')">
    <input type="hidden" name="volver" value="1">
    <button class="btn emitir big">🧾 Facturar ahora</button>
  </form>
  <form method="post" action="{{ url_for('facturar_uno', cuit=cliente.cuit) }}">
    <input type="hidden" name="dry_run" value="1">
    <input type="hidden" name="volver" value="1">
    <button class="btn dry big">🔍 Simular (dry-run)</button>
  </form>
  {% else %}
  <span class="pill off">Cliente inactivo</span>
  {% endif %}
</div>

<h2>Actividad fiscal en ARCA <span class="mut">(consulta en vivo — {{ ambiente }})</span></h2>
{% if fiscal.error %}
  <div class="flash error">No se pudo consultar ARCA: {{ fiscal.error }}</div>
{% else %}
  <table>
    <tr><th colspan="2">Estado de servidores de ARCA</th></tr>
    <tr><td class="dato">AppServer</td><td>{{ fiscal.dummy.AppServer }}</td></tr>
    <tr><td class="dato">DbServer</td><td>{{ fiscal.dummy.DbServer }}</td></tr>
    <tr><td class="dato">AuthServer</td><td>{{ fiscal.dummy.AuthServer }}</td></tr>
  </table>

  <table>
    <tr><th>Punto de venta</th><th>Tipo de emisión</th><th>Bloqueado</th><th>Fecha baja</th></tr>
    {% for p in fiscal.puntos_venta %}
    <tr><td>{{ p.nro }}</td><td>{{ p.emision }}</td>
        <td>{{ 'Sí ⚠️' if p.bloqueado == 'S' else 'No' }}</td><td>{{ p.fecha_baja }}</td></tr>
    {% else %}
    <tr><td colspan="4" class="mut">Sin puntos de venta dados de alta.</td></tr>
    {% endfor %}
  </table>

  <table>
    <tr><th>Tipo de comprobante</th><th>Último autorizado (pto. vta. {{ cliente.punto_de_venta }})</th></tr>
    {% for u in fiscal.ultimos %}
    <tr><td>{{ u.tipo }}</td><td>{{ u.numero }}</td></tr>
    {% endfor %}
  </table>
{% endif %}

<h2>Historial de este cliente</h2>
<table>
  <tr><th>Fecha</th><th>Comprobante</th><th>Monto</th>
      <th>Resultado</th><th>CAE</th><th>Vto. CAE</th><th>Detalle</th><th>Acciones</th></tr>
  {% for h in historial %}
  <tr>
    <td class="mut">{{ h.fecha }}</td>
    <td>{{ '#' ~ h.numero if h.numero else '—' }}</td>
    <td>${{ h.monto }}</td>
    <td><span class="pill {{ h.resultado }}">{{ h.resultado }}</span></td>
    <td class="mut">{{ h.cae or '—' }}</td>
    <td class="mut">{{ h.cae_vencimiento or '—' }}</td>
    <td class="mut">{{ h.detalle }}</td>
    <td>{% if h.resultado == 'APROBADA' and h.cae %}
      <a class="btn dry" href="{{ url_for('ver_pdf', cuit=h.cuit, numero=h.numero) }}" target="_blank">📄 PDF</a>
      <form method="post" action="{{ url_for('verificar', cuit=h.cuit, numero=h.numero) }}" style="margin-top:4px;">
        <button class="btn dry">✔ Verificar en ARCA</button>
      </form>
    {% endif %}</td>
  </tr>
  {% else %}
  <tr><td colspan="8" class="mut">Todavía no se le emitió nada a este cliente.</td></tr>
  {% endfor %}
</table>

</main>
</body>
</html>
"""

NUEVO = HEAD + """
<body>
<header>
  <h1><a href="/">🧾 Facturador Monotributo</a></h1>
  <span class="badge prod">PRODUCCIÓN — FACTURAS REALES</span>
</header>
<main>

<p><a class="volver" href="/">← Volver al panel general</a></p>
<h2>➕ Nuevo cliente</h2>

{% if errores %}
  {% for e in errores %}<div class="flash error">❌ {{ e }}</div>{% endfor %}
{% endif %}

<form method="post" enctype="multipart/form-data" style="max-width:640px;">
<table>
  <tr><td class="dato">Nombre o razón social *</td>
      <td><input name="nombre" value="{{ f.nombre }}" required
                 style="width:100%; padding:8px; border:1px solid #cbd5e1; border-radius:8px;"></td></tr>
  <tr><td class="dato">CUIT *</td>
      <td><input name="cuit" value="{{ f.cuit }}" required placeholder="20123456789"
                 style="width:100%; padding:8px; border:1px solid #cbd5e1; border-radius:8px;"></td></tr>
  <tr><td class="dato">Punto de venta *</td>
      <td><input name="punto_de_venta" type="number" min="1" value="{{ f.punto_de_venta or 1 }}" required
                 style="width:120px; padding:8px; border:1px solid #cbd5e1; border-radius:8px;">
          <div class="mut">El que figura en ARCA para este CUIT (tipo Web Service). Lo ves en la ficha una vez cargado el certificado.</div></td></tr>
  <tr><td class="dato">Tipo de comprobante</td>
      <td><select name="tipo_comprobante" style="min-width:0; width:100%;">
            <option value="11" {{ 'selected' if f.tipo_comprobante|string == '11' }}>Factura C (monotributo)</option>
            <option value="6" {{ 'selected' if f.tipo_comprobante|string == '6' }}>Factura B (responsable inscripto)</option>
          </select></td></tr>
  <tr><td class="dato">Concepto</td>
      <td><select name="concepto" style="min-width:0; width:100%;">
            <option value="2" {{ 'selected' if f.concepto|string == '2' }}>Servicios</option>
            <option value="1" {{ 'selected' if f.concepto|string == '1' }}>Productos</option>
            <option value="3" {{ 'selected' if f.concepto|string == '3' }}>Productos y Servicios</option>
          </select></td></tr>
  <tr><td class="dato">Descripción en factura</td>
      <td><input name="descripcion" value="{{ f.descripcion or 'Honorarios mensuales - Servicios profesionales' }}"
                 style="width:100%; padding:8px; border:1px solid #cbd5e1; border-radius:8px;"></td></tr>
  <tr><td class="dato">Monto mensual *</td>
      <td>$ <input name="monto" type="number" min="0.01" step="0.01" value="{{ f.monto }}" required
                 style="width:160px; padding:8px; border:1px solid #cbd5e1; border-radius:8px;"></td></tr>
  <tr><td class="dato">Medio de pago</td>
      <td><select name="medio_pago" style="min-width:0; width:100%;">
            <option value="digital" {{ 'selected' if f.medio_pago == 'digital' }}>Digital (transferencia / tarjeta / QR)</option>
            <option value="efectivo" {{ 'selected' if f.medio_pago == 'efectivo' }}>Efectivo</option>
          </select>
          <div class="mut">Define qué tope de Consumidor Final aplica.</div></td></tr>
  <tr><td class="dato">Comprador identificado</td>
      <td><select name="doc_tipo" style="min-width:0; width:48%;">
            <option value="99" {{ 'selected' if f.doc_tipo|string == '99' }}>Sin identificar</option>
            <option value="96" {{ 'selected' if f.doc_tipo|string == '96' }}>DNI</option>
            <option value="80" {{ 'selected' if f.doc_tipo|string == '80' }}>CUIT</option>
          </select>
          <input name="doc_nro" type="number" min="0" value="{{ f.doc_nro or '' }}" placeholder="N° documento"
                 style="width:48%; padding:8px; border:1px solid #cbd5e1; border-radius:8px;">
          <div class="mut">Solo si el monto supera el tope de Consumidor Final.</div></td></tr>
  <tr><td class="dato">Certificado (.crt)</td>
      <td><input type="file" name="certificado" accept=".crt,.pem">
          <div class="mut">El que descargaste de ARCA (Administración de Certificados Digitales). Se guarda en la base de datos.</div></td></tr>
  <tr><td class="dato">Clave privada (.key)</td>
      <td><input type="file" name="clave" accept=".key,.pem">
          <div class="mut">La que generó generar_csr.py para este CUIT. Se guarda en la base de datos. Nunca se sube a ARCA.</div></td></tr>
</table>

<div class="acciones">
  <button class="btn emitir big" type="submit">💾 Guardar cliente</button>
  <a class="btn dry big" style="text-decoration:none;" href="/">Cancelar</a>
</div>
<div class="mut">* El certificado y la clave podés subirlos después: el cliente se crea igual,
pero no vas a poder facturarle ni ver su actividad fiscal hasta que estén.
Antes de cargar un cliente nuevo, generá su CSR con:
<code>python generar_csr.py --cuit CUIT --nombre "Nombre"</code>
y seguí los pasos 2 a 4 de la GUIA_CERTIFICADOS.md.</div>
</form>

</main>
</body>
</html>
"""


def stats_cliente(historial: list[dict], cuit) -> dict:
    suyas = [h for h in historial if str(h["cuit"]) == str(cuit)]
    aprobadas = [h for h in suyas if h["resultado"] == "APROBADA"]
    mes_actual = datetime.now().strftime("%Y-%m")
    return {
        "suyas": suyas,
        "emitidas_total": len(aprobadas),
        "facturado_total": sum(float(h["monto"] or 0) for h in aprobadas),
        "emitidas_mes": sum(1 for h in aprobadas
                            if h["fecha"].startswith(mes_actual)),
    }


@app.route("/")
def index():
    config = db.get_config()
    clientes = db.get_clientes()
    historial = db.historial()
    mes_actual = datetime.now().strftime("%Y-%m")

    emitidas_mes = [h for h in historial
                    if h["fecha"].startswith(mes_actual)
                    and h["resultado"] == "APROBADA"]
    problemas_mes = [h for h in historial
                     if h["fecha"].startswith(mes_actual)
                     and h["resultado"] in ("RECHAZADA", "ERROR", "BLOQUEADO")]

    stats = {
        "activos": sum(1 for c in clientes if c.get("activo")),
        "emitidas_mes": len(emitidas_mes),
        "facturado_mes": sum(float(h["monto"] or 0) for h in emitidas_mes),
        "problemas_mes": len(problemas_mes),
    }

    for c in clientes:
        sc = stats_cliente(historial, c["cuit"])
        c["emitidas_total"] = sc["emitidas_total"]
        ultima = sc["suyas"][-1] if sc["suyas"] else None
        c["ultimo"] = ultima["resultado"] if ultima else None
        c["ultimo_fecha"] = ultima["fecha"] if ultima else ""

    return render_template_string(
        TEMPLATE,
        ambiente=config["ambiente"],
        clientes=clientes,
        stats=stats,
        historial=list(reversed(historial[-50:])),
        seleccionado=None,
    )


@app.route("/cliente/<cuit>")
def cliente_detalle(cuit):
    config = db.get_config()
    cliente = db.get_cliente(cuit)
    if not cliente:
        flash(f"❌ No existe un cliente con CUIT {cuit}", "error")
        return redirect(url_for("index"))

    historial = db.historial()
    sc = stats_cliente(historial, cuit)

    return render_template_string(
        DETALLE,
        ambiente=config["ambiente"],
        cliente=cliente,
        clientes=db.get_clientes(),
        seleccionado=str(cuit),
        tipo_cbte_nombre=TIPOS_CBTE.get(cliente["tipo_comprobante"], "Otro"),
        fiscal=actividad_fiscal(cliente, config),
        historial=list(reversed(sc["suyas"])),
        emitidas_total=sc["emitidas_total"],
        facturado_total=sc["facturado_total"],
        emitidas_mes=sc["emitidas_mes"],
    )


def _buscar_emision(cuit, numero):
    return next(
        (h for h in db.historial()
         if str(h["cuit"]) == str(cuit) and str(h["numero"]) == str(numero)
         and h["resultado"] == "APROBADA"),
        None)


@app.route("/pdf/<cuit>/<int:numero>")
def ver_pdf(cuit, numero):
    cliente = db.get_cliente(cuit)
    fila = _buscar_emision(cuit, numero)
    if not cliente or not fila or not fila["cae"]:
        flash("❌ No se encontró ese comprobante", "error")
        return redirect(url_for("index"))
    pdf_bytes = generar_pdf(fila, cliente)
    nombre = f"Factura_{str(fila['punto_venta']).zfill(4)}_{str(numero).zfill(8)}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=False, download_name=nombre)


@app.route("/verificar/<cuit>/<int:numero>", methods=["POST"])
def verificar(cuit, numero):
    cliente = db.get_cliente(cuit)
    if not cliente:
        flash(f"❌ No existe un cliente con CUIT {cuit}", "error")
        return redirect(url_for("index"))
    try:
        config = db.get_config()
        wsaa, wsfe = get_conexiones(config["ambiente"])
        auth = wsaa.obtener_token_sign(
            cliente["cuit"],
            cliente["certificado"].encode(), cliente["clave_privada"].encode())
        r = wsfe.cliente.service.FECompConsultar(Auth=auth, FeCompConsReq={
            "CbteTipo": cliente["tipo_comprobante"],
            "CbteNro": numero,
            "PtoVta": cliente["punto_de_venta"],
        })
        res = r.ResultGet
        if res and res.Resultado == "A":
            fecha = res.CbteFch
            flash(f"✅ ARCA confirma el comprobante: N° {res.CbteDesde} del "
                  f"{fecha[6:8]}/{fecha[4:6]}/{fecha[:4]} por "
                  f"$ {float(res.ImpTotal):,.2f} — CAE {res.CodAutorizacion} "
                  f"(vto. {res.FchVto[6:8]}/{res.FchVto[4:6]}/{res.FchVto[:4]})", "ok")
        else:
            flash("⚠️ ARCA no encontró ese comprobante como aprobado.", "error")
    except Exception as e:
        flash(f"❌ Error al constatar: {type(e).__name__}: {e}", "error")
    return redirect(url_for("cliente_detalle", cuit=cuit))


@app.route("/nuevo", methods=["GET", "POST"])
def nuevo_cliente():
    config = db.get_config()
    if request.method == "GET":
        return render_template_string(
            NUEVO, ambiente=config["ambiente"], errores=[], f={})

    f = request.form
    errores = []

    nombre = f.get("nombre", "").strip()
    cuit = f.get("cuit", "").replace("-", "").replace(" ", "").strip()
    if not nombre:
        errores.append("El nombre es obligatorio")
    if not (cuit.isdigit() and len(cuit) == 11):
        errores.append("El CUIT debe tener 11 dígitos numéricos")

    try:
        monto = float(f.get("monto", "").replace(",", "."))
        if monto <= 0:
            raise ValueError
    except ValueError:
        errores.append("El monto debe ser un número mayor a cero")
        monto = 0

    try:
        pto = int(f.get("punto_de_venta", "1"))
        if pto < 1:
            raise ValueError
    except ValueError:
        errores.append("El punto de venta debe ser un número entero positivo")
        pto = 1

    if cuit.isdigit() and len(cuit) == 11 and db.get_cliente(cuit):
        errores.append(f"Ya existe un cliente con CUIT {cuit}")

    if errores:
        return render_template_string(
            NUEVO, ambiente=config["ambiente"], errores=errores, f=f)

    crt_pem = ""
    archivo_crt = request.files.get("certificado")
    if archivo_crt and archivo_crt.filename:
        crt_pem = archivo_crt.read().decode("utf-8", errors="replace")
    key_pem = ""
    archivo_key = request.files.get("clave")
    if archivo_key and archivo_key.filename:
        key_pem = archivo_key.read().decode("utf-8", errors="replace")

    doc_tipo = int(f.get("doc_tipo", "99"))
    doc_nro = int(f.get("doc_nro") or 0)
    if doc_tipo == 99:
        doc_nro = 0

    db.crear_cliente({
        "nombre": nombre,
        "cuit": int(cuit),
        "activo": True,
        "punto_de_venta": pto,
        "tipo_comprobante": int(f.get("tipo_comprobante", "11")),
        "concepto": int(f.get("concepto", "2")),
        "descripcion": f.get("descripcion", "").strip()
                       or "Honorarios mensuales - Servicios profesionales",
        "monto": round(monto, 2),
        "medio_pago": f.get("medio_pago", "digital"),
        "doc_tipo": doc_tipo,
        "doc_nro": doc_nro,
        "condicion_iva_receptor": 5,
        "certificado": crt_pem,
        "clave_privada": key_pem,
    })

    aviso = f"✅ Cliente {nombre} (CUIT {cuit}) cargado correctamente."
    if not crt_pem:
        aviso += " Falta subir su certificado .crt para poder facturarle."
    flash(aviso, "ok" if crt_pem else "info")
    return redirect(url_for("cliente_detalle", cuit=cuit))


@app.route("/cliente/<cuit>/monto", methods=["POST"])
def editar_monto(cuit):
    try:
        monto = float(request.form.get("monto", "").replace(",", "."))
        if monto <= 0:
            raise ValueError("El monto debe ser mayor a cero")
    except ValueError as e:
        flash(f"❌ Monto inválido: {e}", "error")
        return redirect(url_for("cliente_detalle", cuit=cuit))

    cliente = db.get_cliente(cuit)
    if not cliente:
        flash(f"❌ No existe un cliente con CUIT {cuit}", "error")
        return redirect(url_for("index"))

    anterior = cliente["monto"]
    db.actualizar_monto(cuit, monto)
    flash(f"💾 {cliente['nombre']}: monto actualizado de "
          f"${anterior:,.2f} a ${monto:,.2f}", "ok")
    return redirect(url_for("cliente_detalle", cuit=cuit))


@app.route("/facturar/<cuit>", methods=["POST"])
def facturar_uno(cuit):
    cliente = db.get_cliente(cuit)
    if not cliente or not cliente.get("activo"):
        flash(f"❌ No hay cliente activo con CUIT {cuit}", "error")
    else:
        ejecutar([cliente], dry_run=request.form.get("dry_run") == "1")
    if request.form.get("volver"):
        return redirect(url_for("cliente_detalle", cuit=cuit))
    return redirect(url_for("index"))


@app.route("/facturar-todos", methods=["POST"])
def facturar_todos():
    dry_run = request.form.get("dry_run") == "1"
    clientes = [c for c in db.get_clientes() if c.get("activo")]
    if not clientes:
        flash("⚠️ No hay clientes activos", "error")
    else:
        ejecutar(clientes, dry_run=dry_run)
    return redirect(url_for("index"))


if __name__ == "__main__":
    db.init_db()
    print("Dashboard en http://localhost:5000  (Ctrl+C para cerrar)")
    app.run(host="127.0.0.1", port=5000, debug=False)
