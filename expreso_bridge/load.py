"""Paso 3 del proceso: cargar un envío en la API y decidir qué pasó.

Cómo se evita duplicar envíos
-----------------------------
La API garantiza que `external_ref` (nuestro nro_remito) es único y responde
409 si ya existe. Esa es la fuente de verdad: no guardamos estado local.

Antes de crear cada envío, lo buscamos por `external_ref`:
- Si ya existe, es "ya existía" (corrida anterior o carga manual) y no se hace
  ningún POST. Correr el proceso dos veces no duplica nada.
- Si no existe, recién ahí se crea.

El caso fino: error del servidor pero el envío se creó igual
------------------------------------------------------------
Un 500 (o un timeout) no garantiza que el envío NO se haya creado. Como ya
verificamos que no existía antes de empezar, si después de un error
reintentamos y recibimos 409, ese envío lo creamos nosotros: se marca como
"cargado (confirmado al reintentar)".

Queda un único caso que no se puede distinguir: que otra persona o proceso
cargue ese mismo remito justo en los segundos entre nuestra consulta y nuestro
POST. Es muy poco probable y, aun así, no genera duplicados.
"""
from dataclasses import dataclass
from typing import Optional

from .api_client import ErrorApi, ErrorAutenticacion, ErrorRed, ExpresoClient, es_error_transitorio

# Estados posibles de cada remito en el resumen de la corrida
CARGADO = "CARGADO"
CARGADO_TRAS_ERROR = "CARGADO_CONFIRMADO_AL_REINTENTAR"
YA_EXISTIA = "YA_EXISTIA"
RECHAZADO_DATOS = "RECHAZADO_DATOS"      # lo rechazamos nosotros antes de enviar
RECHAZADO_API = "RECHAZADO_API"          # 422 de la API
CONFLICTO = "CONFLICTO_DUPLICADO"        # nro_remito repetido con datos distintos en el export
ERROR_TEMPORAL = "ERROR_TEMPORAL"        # la API siguió fallando: se reintenta en la próxima corrida
ERROR = "ERROR"                          # respuesta inesperada, revisar
NO_PROCESADO = "NO_PROCESADO"            # la corrida se cortó (API key rechazada) antes de llegar a este remito


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

    # 1) ¿Ya existe? (los GET se reintentan solos ante fallas de la API)
    try:
        existentes = client.buscar_por_ref(ref)
    except ErrorApi as e:
        return ResultadoCarga(ref, ERROR_TEMPORAL, None, 0,
                              f"No se pudo verificar si el envío ya existía ({e}). "
                              "No se envió nada: se puede volver a correr sin riesgo de duplicar.")
    if existentes:
        return ResultadoCarga(ref, YA_EXISTIA, existentes[0].get("tracking_id"), 0,
                              "Ya estaba cargado en Expreso Andino (corrida anterior o carga manual).")

    # 2) No existe: se crea, reintentando ante fallas del lado del expreso
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
                detalle = f"Se cargó en el intento {intento} (antes: {ultimo_error})" if intento > 1 else ""
                return ResultadoCarga(ref, CARGADO, body.get("tracking_id"), intento, detalle)

            if resp.status == 409:
                tracking = body.get("tracking_id") or _tracking_por_ref(client, ref)
                if hubo_error_servidor:
                    return ResultadoCarga(ref, CARGADO_TRAS_ERROR, tracking, intento,
                                          f"La API respondió '{ultimo_error}' pero el envío se había creado")
                # No existía hace un instante y no tuvimos errores: lo cargó alguien más en paralelo.
                return ResultadoCarga(ref, YA_EXISTIA, tracking, intento,
                                      "Lo cargó otra persona o proceso mientras corría este proceso.")

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
    except ErrorAutenticacion:
        raise
    except Exception:
        return None
    return items[0].get("tracking_id") if items else None
