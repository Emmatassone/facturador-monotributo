"""
Capa de acceso a datos (PostgreSQL / Neon).

Toda la informacion sensible vive aca: clientes (con sus certificados y
claves privadas en formato PEM), configuracion y el historial de emisiones.
El repo de git NO contiene datos: solo codigo.

La conexion se toma de la variable de entorno DATABASE_URL o del
archivo .env (que esta en .gitignore).
"""
import os
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clientes (
    cuit BIGINT PRIMARY KEY,
    nombre TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    punto_de_venta INT NOT NULL DEFAULT 1,
    tipo_comprobante INT NOT NULL DEFAULT 11,
    concepto INT NOT NULL DEFAULT 2,
    descripcion TEXT NOT NULL DEFAULT '',
    monto NUMERIC(12,2) NOT NULL,
    medio_pago TEXT NOT NULL DEFAULT 'digital',
    doc_tipo INT NOT NULL DEFAULT 99,
    doc_nro BIGINT NOT NULL DEFAULT 0,
    condicion_iva_receptor INT NOT NULL DEFAULT 5,
    certificado TEXT NOT NULL DEFAULT '',
    clave_privada TEXT NOT NULL DEFAULT '',
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS emisiones (
    id SERIAL PRIMARY KEY,
    fecha TIMESTAMPTZ NOT NULL DEFAULT now(),
    cuit BIGINT NOT NULL,
    nombre TEXT,
    punto_venta INT,
    tipo_cbte INT,
    numero INT,
    monto NUMERIC(12,2),
    resultado TEXT,
    cae TEXT,
    cae_vencimiento TEXT,
    detalle TEXT
);
"""


def _url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url and os.path.exists(".env"):
        with open(".env", encoding="utf-8") as f:
            for linea in f:
                if linea.strip().startswith("DATABASE_URL="):
                    url = linea.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        raise RuntimeError(
            "Falta la conexion a la base de datos: definí DATABASE_URL "
            "como variable de entorno o en el archivo .env")
    return url


def conn():
    return psycopg.connect(_url(), row_factory=dict_row)


def init_db() -> None:
    with conn() as c:
        for sentencia in SCHEMA.split(";"):
            if sentencia.strip():
                c.execute(sentencia)


# ---------------------------------------------------------------- config ---

def get_config() -> dict:
    with conn() as c:
        filas = c.execute("SELECT clave, valor FROM config").fetchall()
    raw = {f["clave"]: f["valor"] for f in filas}
    return {
        "ambiente": raw.get("ambiente", "produccion"),
        "tope_consumidor_final_digital": float(
            raw.get("tope_consumidor_final_digital", 344488)),
        "tope_consumidor_final_efectivo": float(
            raw.get("tope_consumidor_final_efectivo", 172244)),
        "email": {
            "habilitado": raw.get("email_habilitado", "false") == "true",
            "smtp_host": raw.get("email_smtp_host", "smtp.gmail.com"),
            "smtp_port": int(raw.get("email_smtp_port", 465)),
            "usuario": raw.get("email_usuario", ""),
            "password": raw.get("email_password", ""),
            "destinatario": raw.get("email_destinatario", ""),
        },
    }


def set_config(clave: str, valor: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO config (clave, valor) VALUES (%s, %s) "
            "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
            (clave, valor))


# -------------------------------------------------------------- clientes ---

def _normalizar_cliente(fila: dict) -> dict:
    fila["cuit"] = int(fila["cuit"])
    fila["monto"] = float(fila["monto"])
    fila["doc_nro"] = int(fila["doc_nro"])
    return fila


def get_clientes() -> list[dict]:
    with conn() as c:
        filas = c.execute(
            "SELECT * FROM clientes ORDER BY nombre").fetchall()
    return [_normalizar_cliente(f) for f in filas]


def get_cliente(cuit) -> dict | None:
    with conn() as c:
        fila = c.execute(
            "SELECT * FROM clientes WHERE cuit = %s", (int(cuit),)).fetchone()
    return _normalizar_cliente(fila) if fila else None


def crear_cliente(datos: dict) -> None:
    with conn() as c:
        c.execute("""
            INSERT INTO clientes (cuit, nombre, activo, punto_de_venta,
                tipo_comprobante, concepto, descripcion, monto, medio_pago,
                doc_tipo, doc_nro, condicion_iva_receptor,
                certificado, clave_privada)
            VALUES (%(cuit)s, %(nombre)s, %(activo)s, %(punto_de_venta)s,
                %(tipo_comprobante)s, %(concepto)s, %(descripcion)s,
                %(monto)s, %(medio_pago)s, %(doc_tipo)s, %(doc_nro)s,
                %(condicion_iva_receptor)s, %(certificado)s, %(clave_privada)s)
        """, datos)


def actualizar_monto(cuit, monto: float) -> None:
    with conn() as c:
        c.execute("UPDATE clientes SET monto = %s WHERE cuit = %s",
                  (round(monto, 2), int(cuit)))


# -------------------------------------------------------------- emisiones ---

def registrar_emision(fila: dict) -> None:
    with conn() as c:
        c.execute("""
            INSERT INTO emisiones (fecha, cuit, nombre, punto_venta,
                tipo_cbte, numero, monto, resultado, cae, cae_vencimiento,
                detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            datetime.now(),
            int(fila["cuit"]), fila.get("nombre", ""),
            fila.get("punto_venta") or None, fila.get("tipo_cbte") or None,
            int(fila["numero"]) if fila.get("numero") else None,
            float(fila["monto"]) if fila.get("monto") not in (None, "") else None,
            fila.get("resultado", ""), fila.get("cae", ""),
            fila.get("cae_vencimiento", ""), fila.get("detalle", ""),
        ))


def historial() -> list[dict]:
    with conn() as c:
        filas = c.execute("""
            SELECT id, to_char(fecha, 'YYYY-MM-DD HH24:MI') AS fecha,
                   cuit, nombre, punto_venta, tipo_cbte, numero, monto,
                   resultado, cae, cae_vencimiento, detalle
            FROM emisiones ORDER BY id
        """).fetchall()
    for f in filas:
        f["cuit"] = int(f["cuit"])
        f["monto"] = float(f["monto"]) if f["monto"] is not None else 0.0
        f["numero"] = f["numero"] if f["numero"] is not None else ""
        for campo in ("cae", "cae_vencimiento", "detalle", "nombre"):
            f[campo] = f[campo] or ""
    return filas
