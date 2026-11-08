"""
WSFEv1 - Web Service de Facturacion Electronica (ARCA/AFIP).

Operaciones usadas:
- FECompUltimoAutorizado: ultimo numero de comprobante emitido
- FECAESolicitar:         autoriza el comprobante y devuelve el CAE
- FEParamGetTiposCbte:    sanity check de tipos de comprobante

Tipos de comprobante frecuentes:
    6  = Factura B
    11 = Factura C
DocTipo 99 con DocNro 0 = Consumidor Final SIN identificar.
"""
from datetime import datetime

from zeep import Client
from zeep.transports import Transport

from afip_ssl import crear_sesion

WSDL_HOMO = "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
WSDL_PROD = "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL"

DOC_CONSUMIDOR_FINAL = 99


class WSFE:
    def __init__(self, ambiente: str = "homologacion"):
        wsdl = WSDL_PROD if ambiente == "produccion" else WSDL_HOMO
        self.cliente = Client(wsdl, transport=Transport(session=crear_sesion()))

    def dummy(self) -> dict:
        r = self.cliente.service.FEDummy()
        return {"AppServer": r.AppServer, "DbServer": r.DbServer, "AuthServer": r.AuthServer}

    def ultimo_comprobante(self, auth: dict, punto_venta: int, tipo_cbte: int) -> int:
        r = self.cliente.service.FECompUltimoAutorizado(
            Auth=auth, PtoVta=punto_venta, CbteTipo=tipo_cbte
        )
        return int(r.CbteNro)

    def puntos_de_venta(self, auth: dict) -> list[dict]:
        """Puntos de venta habilitados del CUIT."""
        r = self.cliente.service.FEParamGetPtosVenta(Auth=auth)
        resultado = []
        # La respuesta puede venir como ResultGet o Resultado segun la version
        contenedor = getattr(r, "ResultGet", None) or getattr(r, "Resultado", None)
        if contenedor and getattr(contenedor, "PtoVenta", None):
            for p in contenedor.PtoVenta:
                resultado.append({
                    "nro": p.Nro,
                    "emision": p.EmisionTipo,
                    "bloqueado": p.Bloqueado,
                    "fecha_baja": getattr(p, "FchBaja", None) or "-",
                })
        return resultado

    def emitir_factura(self, auth: dict, punto_venta: int, tipo_cbte: int,
                       numero: int, monto: float, concepto: int,
                       doc_tipo: int = DOC_CONSUMIDOR_FINAL, doc_nro: int = 0,
                       condicion_iva_receptor: int = 5,
                       fecha: datetime = None) -> dict:
        """Solicita el CAE para un comprobante. Devuelve dict con resultado, CAE y vencimiento."""
        fecha = fecha or datetime.now()
        fecha_str = fecha.strftime("%Y%m%d")

        detalle = {
            "Concepto": concepto,          # 1=Productos, 2=Servicios, 3=Ambos
            "DocTipo": doc_tipo,           # 99 = Consumidor Final sin identificar
            "DocNro": doc_nro,
            "CbteDesde": numero,
            "CbteHasta": numero,
            "CbteFch": fecha_str,
            "ImpTotal": round(monto, 2),
            "ImpTotConc": 0,               # neto no gravado
            "ImpNeto": round(monto, 2),    # Factura C: todo es neto, sin IVA discriminado
            "ImpOpEx": 0,
            "ImpTrib": 0,
            "ImpIVA": 0,
            "MonId": "PES",
            "MonCotiz": 1,
            # RG 5616: obligatorio desde 2024.
            # 1=IVA Resp. Inscripto, 4=Exento, 5=Consumidor Final,
            # 6=Responsable Monotributo, 13=Monotributista Social
            "CondicionIVAReceptorId": condicion_iva_receptor,
        }

        # Concepto 2 o 3 exige fechas de servicio y vencimiento de pago
        if concepto in (2, 3):
            detalle["FchServDesde"] = fecha_str
            detalle["FchServHasta"] = fecha_str
            detalle["FchVtoPago"] = fecha_str

        request = {
            "FeCabReq": {"CantReg": 1, "PtoVta": punto_venta, "CbteTipo": tipo_cbte},
            "FeDetReq": {"FECAEDetRequest": [detalle]},
        }

        r = self.cliente.service.FECAESolicitar(Auth=auth, FeCAEReq=request)

        cabecera = r.FeCabResp
        detalle_resp = r.FeDetResp.FECAEDetResponse[0]

        observaciones = []
        if getattr(detalle_resp, "Observaciones", None):
            observaciones = [
                f"{o.Code}: {o.Msg}" for o in detalle_resp.Observaciones.Obs
            ]

        errores = []
        if getattr(r, "Errors", None):
            errores = [f"{e.Code}: {e.Msg}" for e in r.Errors.Err]

        return {
            "resultado": cabecera.Resultado,       # "A" = Aprobado, "R" = Rechazado
            "reproceso": cabecera.Reproceso,
            "numero": detalle_resp.CbteDesde,
            "cae": getattr(detalle_resp, "CAE", "") or "",
            "cae_vencimiento": getattr(detalle_resp, "CAEFchVto", "") or "",
            "observaciones": observaciones,
            "errores": errores,
        }
