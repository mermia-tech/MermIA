"""MR-36: the synthetic CFDI 4.0 builder shared by test_cfdi.py and test_cfdi_hardening.py."""

UUID_ = "5D3E8A1C-7B2F-4E9A-9C61-0F4A2B7D8E13"


def concepto(
    desc: str = "CEBOLLA BLANCA",
    cantidad: str = "5",
    valor: str = "26.00",
    importe: str = "130.00",
    *,
    unidad: str = "KGM",
    descuento: str | None = None,
    impuestos: str = "",
) -> str:
    dto = f' Descuento="{descuento}"' if descuento is not None else ""
    return (
        f'<cfdi:Concepto ClaveProdServ="50404900" Cantidad="{cantidad}" ClaveUnidad="{unidad}" '
        f'Descripcion="{desc}" ValorUnitario="{valor}" Importe="{importe}"{dto} ObjetoImp="02">'
        f"{impuestos}</cfdi:Concepto>"
    )


def traslado(impuesto: str, base: str = "130.00", importe: str = "0.00") -> str:
    return (
        f'<cfdi:Impuestos><cfdi:Traslados><cfdi:Traslado Base="{base}" Impuesto="{impuesto}" '
        f'TipoFactor="Tasa" TasaOCuota="0.080000" Importe="{importe}"/>'
        "</cfdi:Traslados></cfdi:Impuestos>"
    )


def cfdi(
    *conceptos: str,
    ns: str = "4",
    version: str = "4.0",
    tipo: str = "I",
    moneda: str = "MXN",
    fecha: str = "2026-10-08T09:15:00",
    subtotal: str = "130.00",
    descuento: str | None = None,
    total: str = "130.00",
    uuid: str | None = UUID_,
) -> bytes:
    dto = f' Descuento="{descuento}"' if descuento is not None else ""
    timbre = (
        f'<cfdi:Complemento><tfd:TimbreFiscalDigital Version="1.1" UUID="{uuid}"/>'
        "</cfdi:Complemento>"
        if uuid is not None
        else ""
    )
    body = "".join(conceptos or (concepto(),))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/{ns}" '
        'xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" '
        f'Version="{version}" Fecha="{fecha}" SubTotal="{subtotal}"{dto} Moneda="{moneda}" '
        f'Total="{total}" TipoDeComprobante="{tipo}" LugarExpedicion="37000">'
        '<cfdi:Emisor Rfc="CSB150301AB1" Nombre="CARNES SELECTAS DEL BAJIO" RegimenFiscal="601"/>'
        '<cfdi:Receptor Rfc="TEG190415MX2" Nombre="TAQUERIA EL GUERO" UsoCFDI="G01"/>'
        f"<cfdi:Conceptos>{body}</cfdi:Conceptos>{timbre}</cfdi:Comprobante>"
    ).encode()
