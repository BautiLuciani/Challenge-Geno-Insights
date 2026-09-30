"""Paso 3 del proceso: cargar un envío en la API y decidir qué pasó.

Cómo se evita duplicar envíos
-----------------------------
La API garantiza que `external_ref` (nuestro nro_remito) es único y responde
409 si ya existe. Esa es la fuente de verdad: no guardamos estado local.
Correr el proceso dos veces sobre el mismo export no duplica nada: la segunda
vez todos los que ya estaban vuelven como "ya existía".

El caso fino: error del servidor pero el envío se creó igual
------------------------------------------------------------
Un 500 (o un timeout) no garantiza que el envío NO se haya creado. Por eso,
si después de un error reintentamos y recibimos 409, no es un duplicado de otra
corrida: es nuestro propio envío que sí se había creado. Lo marcamos como
"cargado (confirmado al reintentar)".
"""
from dataclasses import dataclass
from typing import Optional

from .api_client import ErrorAutenticacion, ErrorRed, ExpresoClient, es_error_transitorio

# Estados posibles de cada remito en el resumen de la corrida
CARGADO = "CARGADO"
CARGADO_TRAS_ERROR = "CARGADO_CONFIRMADO_AL_REINTENTAR"
YA_EXISTIA = "YA_EXISTIA"
RECHAZADO_DATOS = "RECHAZADO_DATOS"      # lo rechazamos nosotros antes de enviar
RECHAZADO_API = "RECHAZADO_API"          # 422 de la API
CONFLICTO = "CONFLICTO_DUPLICADO"        # nro_remito repetido con datos distintos en el export
ERROR_TEMPORAL = "ERROR_TEMPORAL"        # la API siguió fallando: se reintenta en la próxima corrida
ERROR = "ERROR"                          # respuesta inesperada, revisar


@dataclass
class ResultadoCarga:
    nro_remito: str
    estado: str
    tracking_id: Optional[str] = None
    intentos: int = 0
    detalle: str = ""


def _detalle_422(body) -> str:
    detalles = (body or {}).get("details") or []
    partes = [f"{d.get('field')}: {d.get('message')}" for d in detalles if isinstance(d, dict)]
    return "; ".join(partes) or "La API rechazó los datos (422) sin detalle"


def cargar_envio(client: ExpresoClient, payload: dict) -> ResultadoCarga:
    ref = payload["external_ref"]
    hubo_error_servidor = False
    ultimo_error = ""

    for intento in range(1, client.max_intentos + 1):
        try:
            resp = client.crear_envio(payload)
        except ErrorRed as e:
            hubo_error_servidor = True
            ultimo_error = f"sin respuesta de la API ({e})"
        else:
            body = resp.body or {}
            if resp.status == 201:
                return ResultadoCarga(ref, CARGADO, body.get("tracking_id"), intento)

            if resp.status == 409:
                tracking = body.get("tracking_id") or _tracking_por_ref(client, ref)
                if hubo_error_servidor:
                    return ResultadoCarga(ref, CARGADO_TRAS_ERROR, tracking, intento,
                                          f"La API respondió '{ultimo_error}' pero el envío se había creado")
                return ResultadoCarga(ref, YA_EXISTIA, tracking, intento,
                                      "Ya estaba cargado en Expreso Andino (corrida anterior o carga manual)")

            if resp.status == 422:
                return ResultadoCarga(ref, RECHAZADO_API, None, intento, _detalle_422(resp.body))

            if resp.status == 401:
                raise ErrorAutenticacion("API key inválida o faltante (401)")

            if not es_error_transitorio(resp.status):
                return ResultadoCarga(ref, ERROR, None, intento,
                                      f"Respuesta inesperada de la API: HTTP {resp.status} {resp.body}")

            hubo_error_servidor = True
            ultimo_error = f"HTTP {resp.status}"

        if intento < client.max_intentos:
            client.dormir(client.espera(intento))

    return ResultadoCarga(ref, ERROR_TEMPORAL, None, client.max_intentos,
                          f"La API siguió fallando después de {client.max_intentos} intentos "
                          f"({ultimo_error}). Se puede volver a correr sin riesgo de duplicar.")


def _tracking_por_ref(client: ExpresoClient, ref: str) -> Optional[str]:
    """Si el 409 no trajo el tracking_id, lo buscamos. Si esa búsqueda falla, no es grave."""
    try:
        items = client.buscar_por_ref(ref)
    except Exception:
        return None
    return items[0].get("tracking_id") if items else None
