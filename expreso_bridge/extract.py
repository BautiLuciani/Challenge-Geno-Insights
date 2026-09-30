"""Paso 1 del proceso: leer el export de LogiSur y quedarse con los remitos de Expreso Andino.

El export viene "como viene" de un sistema real, así que acá resolvemos dos cosas:

1. El nombre del transportista está escrito de varias formas
   ("Expreso Andino", "EXPRESO ANDINO ", "Exp. Andino", ...). Lo normalizamos
   antes de comparar.
2. Puede haber remitos repetidos. Si son copias idénticas, cargamos uno solo.
   Si comparten número pero tienen datos distintos, no sabemos cuál es el bueno:
   no cargamos ninguno y lo informamos para que operaciones lo revise.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TRANSPORTISTA_OBJETIVO = "expreso andino"

# Abreviaturas que vimos (o que es razonable esperar) en el campo transportista.
_ABREVIATURAS = {"exp": "expreso"}


def normalizar_transportista(valor) -> str:
    """Lleva el nombre del transportista a una forma comparable.

    "  EXPRESO ANDINO " -> "expreso andino"
    "Exp. Andino"       -> "expreso andino"
    """
    if not isinstance(valor, str):
        return ""
    texto = valor.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)  # puntuación -> espacio ("exp." -> "exp ")
    palabras = [_ABREVIATURAS.get(p, p) for p in texto.split()]
    return " ".join(palabras)


def es_expreso_andino(remito: dict) -> bool:
    return normalizar_transportista(remito.get("transportista")) == TRANSPORTISTA_OBJETIVO


@dataclass
class ResultadoLectura:
    total_export: int = 0
    otros_transportes: int = 0
    remitos: list = field(default_factory=list)            # remitos de Andino, únicos, listos para transformar
    duplicados_identicos: list = field(default_factory=list)  # nro_remito repetido con los mismos datos
    conflictos: list = field(default_factory=list)          # nro_remito repetido con datos distintos
    sin_numero: int = 0                                     # registros de Andino sin nro_remito


def leer_export(ruta) -> list:
    """Lee el archivo JSON del export y valida que sea una lista de registros."""
    with open(Path(ruta), encoding="utf-8") as f:
        datos = json.load(f)
    if not isinstance(datos, list):
        raise ValueError(f"El export {ruta} debería ser una lista de remitos y es {type(datos).__name__}")
    return datos


def filtrar_expreso_andino(registros: list) -> ResultadoLectura:
    """Filtra los remitos de Expreso Andino y resuelve los duplicados."""
    resultado = ResultadoLectura(total_export=len(registros))
    por_numero = {}  # nro_remito -> lista de apariciones (en orden)

    for registro in registros:
        if not isinstance(registro, dict) or not es_expreso_andino(registro):
            resultado.otros_transportes += 1
            continue
        nro = str(registro.get("nro_remito") or "").strip()
        if not nro:
            resultado.sin_numero += 1
            continue
        por_numero.setdefault(nro, []).append(registro)

    for nro, apariciones in por_numero.items():
        primera = apariciones[0]
        if len(apariciones) == 1:
            resultado.remitos.append(primera)
        elif all(r == primera for r in apariciones[1:]):
            resultado.remitos.append(primera)
            resultado.duplicados_identicos.append(nro)
        else:
            resultado.conflictos.append(nro)

    return resultado
