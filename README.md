# Facturador Monotributo (ARCA/AFIP)

Sistema local para contadores: emite Facturas C/B a Consumidor Final para
múltiples clientes (CUITs) vía el web service WSFEv1 de ARCA, con dashboard
web, PDF con QR oficial y verificación de comprobantes.

**El código NO contiene datos sensibles.** Toda la información (clientes,
certificados, claves privadas, configuración e historial de emisiones) vive
en una base de datos PostgreSQL externa (Neon), por lo que el sistema se
puede correr desde cualquier computadora.

## Funcionalidades

- **Multi-cliente**: cada CUIT firma con su propio certificado digital
- **Dashboard web** (`http://localhost:5000`): panel de clientes, ficha
  individual con actividad fiscal consultada en vivo a ARCA, historial
- **Emisión individual o masiva** con validación de topes de Consumidor
  Final (RG: bloquea si el monto supera el tope sin identificar comprador)
- **PDF del comprobante** con QR oficial de ARCA (`afip.gob.ar/fe/qr/`)
- **Verificación de comprobantes** contra los registros de ARCA
  (`FECompConsultar`)
- **Alta de clientes** desde la web, con subida de `.crt`/`.key` a la base
- **Dry-run**: simulación que consulta el próximo número sin emitir
- **CLI** para correr mensualmente con el Programador de tareas de Windows

## Estructura

| Archivo | Rol |
|---|---|
| `app.py` | Dashboard web (Flask) |
| `facturar.py` | Motor de emisión / CLI |
| `wsaa.py` | Autenticación WSAA (firma CMS del ticket) |
| `wsfe.py` | Web service WSFEv1 (emisión, consultas) |
| `db.py` | Capa de datos PostgreSQL (clientes, config, emisiones) |
| `pdf_comprobante.py` | PDF + QR oficial |
| `afip_ssl.py` | Fix TLS para los servidores de producción de AFIP |
| `generar_csr.py` | Genera clave privada + CSR por CUIT |
| `migrar_a_db.py` | Migración única de datos locales → PostgreSQL |
| `GUIA_CERTIFICADOS.md` | Paso a paso ARCA: certificado, delegación wsfe, punto de venta |

## Setup en una computadora nueva

```powershell
git clone <URL-DEL-REPO>
cd facturador-monotributo
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Crear el archivo `.env` con la cadena de conexión (pedirla al dueño del
sistema, **nunca** subirla al repo):

```
DATABASE_URL=postgresql://usuario:password@host/neondb?sslmode=require
```

Y listo:

```powershell
.venv\Scripts\python app.py          # dashboard en http://localhost:5000
.venv\Scripts\python facturar.py --dry-run   # simular desde CLI
.venv\Scripts\python facturar.py             # emitir (REAL)
```

## Alta de un cliente nuevo

1. `python generar_csr.py --cuit <CUIT> --nombre "Nombre"` → genera `.key` y `.csr`
2. En ARCA con la Clave Fiscal del cliente: subir el CSR en *Administración
   de Certificados Digitales*, delegar **Web Service → Facturación
   Electrónica** en el *Administrador de Relaciones*, y verificar el punto
   de venta tipo *Web Service* (ver `GUIA_CERTIFICADOS.md`)
3. En el dashboard: **➕ Nuevo cliente** → completar y subir `.crt` y `.key`

## Notas de seguridad

- Las claves privadas y certificados se guardan **solo** en la base de
  datos; protegé la cadena de conexión (`DATABASE_URL`) como una contraseña.
- El servidor web escucha solo en `127.0.0.1` (tu máquina).
- Las facturas emitidas no se pueden borrar: los errores se corrigen con
  Nota de Crédito.
