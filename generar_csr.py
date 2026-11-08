"""
Genera la clave privada (.key) y el pedido de certificado (.csr) para un CUIT.

El .csr se sube a ARCA y ARCA te devuelve el .crt (certificado digital).

Uso:
    python generar_csr.py --cuit 20123456789 --nombre "Juan Perez"

Salida:
    claves/20123456789.key   <- clave privada (NO compartir, NO subir a ARCA)
    claves/20123456789.csr   <- se sube a ARCA (WSASS en homologacion,
                                "Administracion de Certificados Digitales" en produccion)
"""
import argparse
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CARPETA_CLAVES = "claves"


def generar(cuit: str, nombre: str) -> None:
    os.makedirs(CARPETA_CLAVES, exist_ok=True)

    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # ARCA exige que el subject incluya serialNumber=CUIT xxxxxxxxxxx
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "AR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, nombre),
        x509.NameAttribute(NameOID.COMMON_NAME, nombre),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, f"CUIT {cuit}"),
    ])

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .sign(clave, hashes.SHA256())
    )

    ruta_key = os.path.join(CARPETA_CLAVES, f"{cuit}.key")
    ruta_csr = os.path.join(CARPETA_CLAVES, f"{cuit}.csr")

    with open(ruta_key, "wb") as f:
        f.write(clave.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with open(ruta_csr, "wb") as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))

    print(f"Listo. Se generaron:")
    print(f"  Clave privada : {ruta_key}  (guardala, nunca se sube a ARCA)")
    print(f"  Pedido (CSR)  : {ruta_csr}  (este se sube a ARCA)")
    print()
    print("Proximo paso: segui las instrucciones de GUIA_CERTIFICADOS.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera .key y .csr para un CUIT")
    parser.add_argument("--cuit", required=True, help="CUIT sin guiones, ej: 20123456789")
    parser.add_argument("--nombre", required=True, help="Nombre o razon social del titular")
    args = parser.parse_args()

    cuit_limpio = args.cuit.replace("-", "").strip()
    if not cuit_limpio.isdigit() or len(cuit_limpio) != 11:
        raise SystemExit("El CUIT debe tener 11 digitos numericos.")

    generar(cuit_limpio, args.nombre)
