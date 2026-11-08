"""
WSAA - Web Service de Autenticacion y Autorizacion (ARCA/AFIP).

Flujo por cada CUIT:
1. Arma un TRA (Ticket de Requerimiento de Acceso) en XML.
2. Lo firma criptograficamente (CMS/PKCS#7) con el certificado del CUIT.
3. Llama a loginCms y obtiene Token + Sign, validos por ~12 horas.
4. Cachea el ticket en tokens/{cuit}.json para no pedirlo en cada corrida.
"""
import base64
import json
import os
import time
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7
from zeep import Client
from zeep.transports import Transport

from afip_ssl import crear_sesion

WSDL_HOMO = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms?WSDL"
WSDL_PROD = "https://wsaa.afip.gov.ar/ws/services/LoginCms?WSDL"

CARPETA_TOKENS = "tokens"
# Argentina no tiene cambio de horario: UTC-3 fijo
OFFSET_AR = "-03:00"


class WSAA:
    def __init__(self, ambiente: str = "homologacion"):
        self.ambiente = ambiente
        self.wsdl = WSDL_PROD if ambiente == "produccion" else WSDL_HOMO
        os.makedirs(CARPETA_TOKENS, exist_ok=True)

    def _armar_tra(self, servicio: str = "wsfe") -> bytes:
        ahora = datetime.now()
        unique_id = int(time.time())
        generacion = (ahora - timedelta(minutes=10)).strftime(f"%Y-%m-%dT%H:%M:%S{OFFSET_AR}")
        expiracion = (ahora + timedelta(hours=12)).strftime(f"%Y-%m-%dT%H:%M:%S{OFFSET_AR}")
        tra = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<loginTicketRequest version="1.0">'
            f"<header><uniqueId>{unique_id}</uniqueId>"
            f"<generationTime>{generacion}</generationTime>"
            f"<expirationTime>{expiracion}</expirationTime></header>"
            f"<service>{servicio}</service>"
            "</loginTicketRequest>"
        )
        return tra.encode("utf-8")

    def _firmar_tra(self, tra: bytes, crt_pem: bytes, key_pem: bytes) -> str:
        cert = x509.load_pem_x509_certificate(crt_pem)
        clave = serialization.load_pem_private_key(key_pem, password=None)

        cms = (
            pkcs7.PKCS7SignatureBuilder()
            .set_data(tra)
            .add_signer(cert, clave, hashes.SHA256())
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
        )
        return base64.b64encode(cms).decode("ascii")

    def obtener_token_sign(self, cuit: int, crt_pem: bytes, key_pem: bytes,
                           servicio: str = "wsfe") -> dict:
        """Devuelve {'Token':..., 'Sign':..., 'Cuit':...} reutilizando el cache si sigue vigente.

        crt_pem y key_pem son el contenido PEM del certificado y la clave
        (vienen de la base de datos, no de archivos)."""
        # Asegurar la carpeta en cada llamada (puede haberse borrado en runtime)
        os.makedirs(CARPETA_TOKENS, exist_ok=True)
        # El cache incluye el ambiente: un token de homologacion NO sirve en produccion
        ruta_cache = os.path.join(
            CARPETA_TOKENS, f"{cuit}_{servicio}_{self.ambiente}.json")

        if os.path.exists(ruta_cache):
            with open(ruta_cache, "r", encoding="utf-8") as f:
                cache = json.load(f)
            expira = datetime.fromisoformat(cache["expiration_time"])
            # Renovar 15 minutos antes de que venza
            if expira - timedelta(minutes=15) > datetime.now():
                return {"Token": cache["token"], "Sign": cache["sign"], "Cuit": cuit}

        tra = self._armar_tra(servicio)
        cms_firmado = self._firmar_tra(tra, crt_pem, key_pem)

        cliente = Client(self.wsdl, transport=Transport(session=crear_sesion()))
        respuesta_xml = cliente.service.loginCms(in0=cms_firmado)

        import xml.etree.ElementTree as ET
        raiz = ET.fromstring(respuesta_xml)
        token = raiz.findtext(".//token")
        sign = raiz.findtext(".//sign")
        expiracion_txt = raiz.findtext(".//expirationTime")

        # expirationTime viene como "2026-11-08T17:30:00.000-03:00"
        expira = datetime.fromisoformat(expiracion_txt).replace(tzinfo=None)

        with open(ruta_cache, "w", encoding="utf-8") as f:
            json.dump({
                "token": token,
                "sign": sign,
                "expiration_time": expira.isoformat(),
            }, f, indent=2)

        return {"Token": token, "Sign": sign, "Cuit": cuit}
