"""Paso 2 del proceso: transformar un remito de LogiSur al formato de la API de Expreso Andino.

Regla general: si un dato no se puede interpretar con seguridad, NO se adivina.
El remito se rechaza con un motivo claro para que operaciones lo corrija.
Mandar un envío con datos equivocados es peor que no mandarlo.

Se juntan todos los problemas de un remito (no solo el primero), así
operaciones lo corrige de una sola vez.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

SERVICIOS = {
    "normal": "standard",
    "urgente": "express",
}

# Abreviaturas / nombres alternativos de provincias. La clave va normalizada
# (minúsculas, sin acentos ni puntuación). El valor es el nombre oficial de la API.
# Las diferencias de acentos o mayúsculas ("Tucuman", "Neuquen") no hace falta
# listarlas: se resuelven comparando contra la lista de la API normalizada.
ALIAS_PROVINCIAS = {
    "ba": "Buenos Aires",
    "bs as": "Buenos Aires",
    "bsas": "Buenos Aires",
    "pba": "Buenos Aires",
    "provincia de buenos aires": "Buenos Aires",
    "caba": "Ciudad Autónoma de Buenos Aires",
    "capital federal": "Ciudad Autónoma de Buenos Aires",
    "cap fed": "Ciudad Autónoma de Buenos Aires",
    "ciudad de buenos aires": "Ciudad Autónoma de Buenos Aires",
    "cba": "Córdoba",
    "sgo del estero": "Santiago del Estero",
    "tdf": "Tierra del Fuego",
}


def _clave(texto: str) -> str:
    """'Bs. As.' -> 'bs as' | 'Tucumán' -> 'tucuman'."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    sin_puntuacion = re.sub(r"[^\w\s]", " ", sin_acentos.lower())
    return " ".join(sin_puntuacion.split())


class NormalizadorProvincias:
    """Traduce la provincia del export al nombre exacto que acepta la API."""

    def __init__(self, provincias_validas):
        self._validas = set(provincias_validas)
        self._por_clave = {_clave(p): p for p in provincias_validas}
        for alias, oficial in ALIAS_PROVINCIAS.items():
            if oficial in self._validas:  # solo si la API la sigue aceptando
                self._por_clave.setdefault(alias, oficial)

    def normalizar(self, valor) -> Optional[str]:
        if not isinstance(valor, str) or not valor.strip():
            return None
        return self._por_clave.get(_clave(valor))


def parsear_numero(valor) -> Optional[float]:
    """Acepta números o textos con coma decimal: '145,1' -> 145.1, '1.234,5' -> 1234.5."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip().replace(" ", "")
    if "," in texto:
        # Formato argentino: el punto es separador de miles y la coma es decimal.
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def parsear_entero(valor) -> Optional[int]:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float) and valor.is_integer():
        return int(valor)
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    return None


def _texto(valor) -> str:
    return valor.strip() if isinstance(valor, str) else ""


@dataclass
class Transformacion:
    nro_remito: str
    payload: Optional[dict] = None
    errores: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errores


def transformar(remito: dict, provincias: NormalizadorProvincias) -> Transformacion:
    nro = _texto(remito.get("nro_remito"))
    resultado = Transformacion(nro_remito=nro)
    errores = resultado.errores
    dest = remito.get("destinatario") if isinstance(remito.get("destinatario"), dict) else {}

    # Destinatario: campos obligatorios de texto
    obligatorios = {
        "name": ("razon_social", "Falta la razón social del destinatario"),
        "street": ("direccion", "Falta la dirección del destinatario"),
        "city": ("localidad", "Falta la localidad del destinatario"),
        "zip_code": ("codigo_postal", "Falta el código postal del destinatario"),
    }
    recipient = {}
    for campo_api, (campo_export, mensaje) in obligatorios.items():
        valor = _texto(dest.get(campo_export))
        if valor:
            recipient[campo_api] = valor
        else:
            errores.append(mensaje)

    provincia = provincias.normalizar(dest.get("provincia"))
    if provincia:
        recipient["province"] = provincia
    elif _texto(dest.get("provincia")):
        errores.append(f"Provincia no reconocida: '{dest.get('provincia')}'")
    else:
        errores.append("Falta la provincia del destinatario")

    telefono = _texto(dest.get("telefono"))
    if telefono:
        recipient["phone"] = telefono

    # Bultos
    bultos = parsear_entero(remito.get("bultos"))
    if bultos is None:
        errores.append(f"Cantidad de bultos inválida: '{remito.get('bultos')}'")
    elif bultos < 1:
        errores.append(f"Cantidad de bultos debe ser al menos 1 (vino {bultos})")

    # Peso
    peso = parsear_numero(remito.get("peso_kg"))
    if peso is None:
        errores.append(f"Peso inválido: '{remito.get('peso_kg')}'")
    elif peso <= 0:
        errores.append(f"El peso debe ser mayor a 0 (vino {peso})")

    # Servicio
    servicio = SERVICIOS.get(_clave(_texto(remito.get("servicio"))))
    if servicio is None:
        errores.append(f"Servicio desconocido: '{remito.get('servicio')}' (se espera NORMAL o URGENTE)")

    # Valor declarado: opcional en la API, pero si viene y está mal, no lo
    # descartamos en silencio (afecta el seguro del envío): se rechaza.
    valor_declarado = None
    crudo = remito.get("valor_declarado")
    if crudo not in (None, ""):
        valor_declarado = parsear_numero(crudo)
        if valor_declarado is None or valor_declarado < 0:
            errores.append(f"Valor declarado inválido: '{crudo}'")

    if not nro:
        errores.append("Falta el número de remito")

    if errores:
        return resultado

    payload = {
        "external_ref": nro,
        "recipient": recipient,
        "packages": bultos,
        "weight_kg": peso,
        "service": servicio,
    }
    if valor_declarado is not None:
        payload["declared_value"] = valor_declarado
    resultado.payload = payload
    return resultado
