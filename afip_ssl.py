"""
Adaptador TLS para los servidores de AFIP/ARCA.

Los servidores de produccion de AFIP (servicios1.afip.gov.ar,
wsaa.afip.gov.ar) negocian parametros Diffie-Hellman de 1024 bits,
que OpenSSL 3 (Python 3.10+) rechaza con el error DH_KEY_TOO_SMALL.

Este adaptador baja el security level de OpenSSL a 1 UNICAMENTE para
las conexiones HTTPS de este programa; no afecta al resto del sistema.
"""
import ssl

import requests
from requests.adapters import HTTPAdapter


class _AfipSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        contexto = ssl.create_default_context()
        # SECLEVEL=1 permite DH de 1024 bits (lo que usan los servers de AFIP)
        contexto.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = contexto
        return super().init_poolmanager(connections, maxsize, block, **kwargs)


def crear_sesion() -> requests.Session:
    sesion = requests.Session()
    sesion.mount("https://", _AfipSSLAdapter())
    return sesion
