"""
Genera el PDF del comprobante con el QR oficial de ARCA.

El QR sigue la especificacion de ARCA: apunta a
https://www.afip.gob.ar/fe/qr/?p=<json en base64> y permite a cualquiera
verificar la validez del comprobante escaneandolo.
"""
import base64
import io
import json
import unicodedata

import qrcode
from fpdf import FPDF


def _ascii(texto: str) -> str:
    """Las fuentes base de FPDF son latin-1: removemos tildes."""
    return unicodedata.normalize("NFKD", str(texto)).encode(
        "ascii", "ignore").decode()


def _url_qr(fila: dict, cuit) -> str:
    payload = {
        "ver": 1,
        "fecha": fila["fecha"][:10],
        "cuit": int(cuit),
        "ptoVta": int(fila["punto_venta"]),
        "tipoCmp": int(fila["tipo_cbte"]),
        "nroCmp": int(fila["numero"]),
        "importe": round(float(fila["monto"]), 2),
        "moneda": "PES",
        "ctz": 1,
        "tipoDocRec": 99,
        "nroDocRec": 0,
        "tipoCodAut": "E",
        "codAut": int(fila["cae"]),
    }
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    return "https://www.afip.gob.ar/fe/qr/?p=" + b64


def generar_pdf(fila: dict, cliente: dict) -> bytes:
    pto = str(fila["punto_venta"]).zfill(4)
    nro = str(fila["numero"]).zfill(8)
    tipo = "C" if str(fila["tipo_cbte"]) == "11" else "B"
    codigo = "011" if tipo == "C" else "006"
    fecha = fila["fecha"][:10]
    vto_cae = fila.get("cae_vencimiento", "")
    vto_fmt = (f"{vto_cae[6:8]}/{vto_cae[4:6]}/{vto_cae[:4]}"
               if len(vto_cae) == 8 else vto_cae)

    # --- QR ---
    img = qrcode.make(_url_qr(fila, fila["cuit"]))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    pdf = FPDF()
    pdf.add_page()

    # --- Encabezado ---
    pdf.set_font("helvetica", "B", 22)
    pdf.cell(95, 12, _ascii(cliente["nombre"]), ln=0)
    pdf.set_font("helvetica", "B", 28)
    pdf.cell(20, 14, tipo, align="C", border=1)
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 10, "FACTURA", ln=1, align="R")
    pdf.set_font("helvetica", "", 11)
    pdf.cell(95, 6, f"CUIT: {fila['cuit']}", ln=0)
    pdf.cell(20, 6, f"Cod. {codigo}", align="C", ln=0)
    pdf.cell(0, 6, f"Punto de Venta: {pto}  Comp. Nro: {nro}", ln=1, align="R")
    pdf.cell(95, 6, f"Fecha de Emision: {fecha}", ln=0)
    pdf.cell(0, 6, "ORIGINAL", ln=1, align="R")
    pdf.line(10, pdf.get_y() + 2, 200, pdf.get_y() + 2)
    pdf.ln(8)

    # --- Receptor ---
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "Receptor: Consumidor Final", ln=1)
    pdf.set_font("helvetica", "", 11)
    pdf.cell(0, 6, f"Condicion frente al IVA: Consumidor Final", ln=1)
    pdf.ln(6)

    # --- Detalle ---
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(130, 8, "Descripcion", border=1)
    pdf.cell(0, 8, "Importe", border=1, ln=1, align="R")
    pdf.set_font("helvetica", "", 11)
    pdf.cell(130, 8, _ascii(cliente.get("descripcion", "Servicios")), border=1)
    pdf.cell(0, 8, f"$ {float(fila['monto']):,.2f}", border=1, ln=1, align="R")
    pdf.set_font("helvetica", "B", 13)
    pdf.cell(130, 10, "", border=0)
    pdf.cell(0, 10, f"Importe Total: $ {float(fila['monto']):,.2f}",
             ln=1, align="R")
    pdf.ln(20)

    # --- Pie: QR + CAE ---
    y_pie = pdf.get_y()
    pdf.image(buffer, x=10, y=y_pie, w=32, h=32)
    pdf.set_xy(48, y_pie + 6)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 7, "Comprobante Autorizado", ln=1)
    pdf.set_x(48)
    pdf.set_font("helvetica", "", 11)
    pdf.cell(0, 6, f"CAE N: {fila['cae']}", ln=1)
    pdf.set_x(48)
    pdf.cell(0, 6, f"Fecha de Vto. de CAE: {vto_fmt}", ln=1)
    pdf.set_xy(10, y_pie + 34)
    pdf.set_font("helvetica", "I", 8)
    pdf.cell(0, 5, "Consulte la validez de este comprobante escaneando "
                   "el codigo QR o en www.afip.gob.ar/fe/qr/", ln=1)

    return bytes(pdf.output())
