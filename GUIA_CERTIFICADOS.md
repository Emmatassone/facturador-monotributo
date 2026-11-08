# Guía: Certificados digitales en ARCA — PRODUCCIÓN

Este sistema opera **únicamente en producción**: todo lo que emite tiene
validez fiscal real. Cada cliente necesita **su propio certificado**. No se
puede facturar para varios CUITs con un solo certificado. Repetí este proceso
una vez por CUIT.

## Paso 1 — Generar clave privada y pedido (CSR)

```powershell
.venv\Scripts\python generar_csr.py --cuit 20123456789 --nombre "Juan Perez"
```

Esto crea `claves/20123456789.key` (privada, **nunca se sube a ARCA**) y
`claves/20123456789.csr` (se sube a ARCA).

## Paso 2 — Obtener el certificado (.crt) en ARCA

1. Entrá con la **Clave Fiscal del cliente** (nivel 3 o superior) a
   https://www.afip.gob.ar
2. Servicio **Administración de Certificados Digitales**
3. "Agregar alias/certificado" → nombre simbólico (ej: `facturacion`), pegá el
   contenido del `.csr` completo (incluyendo las líneas BEGIN/END)
4. Descargá el certificado y guardalo como `claves/{cuit}.crt`

> Como contador podés gestionar esto si el cliente te delega el servicio a tu
> CUIT, pero el certificado y la clave fiscal siempre son del cliente.

## Paso 3 — Delegar el servicio wsfe

1. Servicio **Administrador de Relaciones de Clave Fiscal**
2. **Nueva Relación** → en el árbol elegí:
   **ARCA → Web Service → Facturación Electrónica** (ese es `wsfe`)
3. Seleccioná el alias/certificado creado y confirmá

> La delegación puede tardar unos minutos en impactar. Si el sistema responde
> "Computador no autorizado a acceder al servicio", esperá 5-10 minutos.

## Paso 4 — Dar de alta el punto de venta (una sola vez por CUIT)

En producción el punto de venta hay que crearlo:

- Servicio **Administración de Puntos de Venta y Domicilios** → agregá el
  punto de venta con tipo de emisión **Web Service**
  (ej: "Factura Electrónica - Monotributo - Web Services")

Si falta este paso, ARCA rechaza la factura con error de punto de venta
inválido.

## Paso 5 — Cargar el cliente

Desde el dashboard (http://localhost:5000) → **➕ Nuevo cliente**, completá
el formulario y subí el `.crt` y `.key` (se guardan en la base de datos).
Los datos equivalentes son:

```json
{
  "nombre": "Juan Perez",
  "cuit": 20123456789,
  "activo": true,
  "punto_de_venta": 1,
  "tipo_comprobante": 11,
  "concepto": 2,
  "descripcion": "Honorarios mensuales - Servicios profesionales",
  "monto": 85000.00,
  "medio_pago": "digital",
  "certificado": "claves/20123456789.crt",
  "clave_privada": "claves/20123456789.key"
}
```

- `tipo_comprobante`: 11 = Factura C, 6 = Factura B
- `concepto`: 1 = Productos, 2 = Servicios, 3 = Ambos
- Si el monto supera el tope de Consumidor Final (ver `config.json`), agregá
  `"doc_tipo": 96` (DNI) y `"doc_nro": 30111222` para identificar al comprador.

## Paso 6 — Facturar

Desde la web (http://localhost:5000) con los botones, o por línea de comandos:

```powershell
.venv\Scripts\python facturar.py --dry-run   # simula: muestra el proximo N°, no emite
.venv\Scripts\python facturar.py             # emite facturas REALES
```

**Flujo recomendado cada mes:** primero `--dry-run` (o el botón 🔍 Simular),
verificá los números que se emitirían, y recién después facturá en serio.

⚠️ Las facturas emitidas **no se pueden borrar**: los errores se corrigen con
Nota de Crédito. Nunca borres la carpeta `resultados/`: es tu respaldo de
número de comprobante y CAE.

## Automatización mensual (local)

Usá el **Programador de tareas de Windows**: creá una tarea que corra el día
25 de cada mes con acción:

```
Programa:   C:\Users\Emanuel\Desktop\facturador-monotributo\.venv\Scripts\python.exe
Argumentos: facturar.py
Iniciar en: C:\Users\Emanuel\Desktop\facturador-monotributo
```

> Recordatorio: esto automatiza la **emisión de facturas**. El **pago** del
> monotributo no se puede automatizar por API — la solución real es adherir a
> cada cliente al débito automático en el portal Monotributo (además ARCA le
> reintegra una cuota al año por cumplimiento).
