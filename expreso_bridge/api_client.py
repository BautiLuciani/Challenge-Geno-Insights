"""Cliente HTTP mínimo para la API de Expreso Andino.

Usa solo la librería estándar (urllib), igual que la API de prueba: no hay que
instalar nada. Este módulo solo sabe "hablar HTTP"; qué hacer con cada respuesta
al cargar un envío lo decide load.py.
"""
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


class ErrorAutenticacion(Exception):
    """401: la API key falta o es inválida. No tiene sentido seguir con la corrida."""


class ErrorRed(Exception):
    """No hubo respuesta HTTP: timeout, conexión rechazada, DNS, etc."""


class ErrorApi(Exception):
    """La API respondió algo que no esperábamos y no se resuelve reintentando."""


@dataclass
class Respuesta:
    status: int
    body: Optional[dict]


def es_error_transitorio(status: int) -> bool:
    """Errores del lado del expreso que la doc recomienda reintentar (+429 por las dudas)."""
    return status >= 500 or status == 429


class ExpresoClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0,
                 max_intentos: int = 4, espera_base: float = 1.0, dormir=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_intentos = max_intentos
        self.espera_base = espera_base
        self.dormir = dormir  # inyectable para que los tests no esperen de verdad

    def espera(self, intento: int) -> float:
        """Backoff exponencial: 1s, 2s, 4s, ..."""
        return self.espera_base * (2 ** (intento - 1))

    # --- HTTP crudo: un solo intento -------------------------------------------------
    def request(self, metodo: str, ruta: str, body: Optional[dict] = None) -> Respuesta:
        datos = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + ruta, data=datos, method=metodo)
        req.add_header("X-Api-Key", self.api_key)
        req.add_header("Accept", "application/json")
        if datos is not None:
            req.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return Respuesta(resp.status, _leer_json(resp.read()))
        except urllib.error.HTTPError as e:  # 4xx / 5xx: hubo respuesta, la devolvemos
            return Respuesta(e.code, _leer_json(e.read()))
        except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
            raise ErrorRed(str(getattr(e, "reason", e))) from e

    # --- Lecturas (GET): son idempotentes, así que se reintentan acá mismo ----------
    def _get(self, ruta: str) -> dict:
        ultimo = ""
        for intento in range(1, self.max_intentos + 1):
            try:
                resp = self.request("GET", ruta)
            except ErrorRed as e:
                ultimo = f"sin respuesta ({e})"
            else:
                if resp.status == 401:
                    raise ErrorAutenticacion("API key inválida o faltante (401)")
                if resp.status == 200 and isinstance(resp.body, dict):
                    return resp.body
                if not es_error_transitorio(resp.status):
                    raise ErrorApi(f"GET {ruta} respondió {resp.status}: {resp.body}")
                ultimo = f"HTTP {resp.status}"
            if intento < self.max_intentos:
                self.dormir(self.espera(intento))
        raise ErrorApi(f"GET {ruta} falló después de {self.max_intentos} intentos ({ultimo})")

    def provincias(self) -> list:
        return self._get("/v1/provinces")["provinces"]

    def buscar_por_ref(self, external_ref: str) -> list:
        query = urllib.parse.urlencode({"external_ref": external_ref})
        return self._get(f"/v1/shipments?{query}")["items"]

    def estado_envio(self, tracking_id: str) -> dict:
        return self._get(f"/v1/shipments/{urllib.parse.quote(tracking_id)}")

    # --- Escritura (POST): un solo intento; la lógica de reintento vive en load.py ---
    def crear_envio(self, payload: dict) -> Respuesta:
        return self.request("POST", "/v1/shipments", payload)


def _leer_json(crudo: bytes) -> Optional[dict]:
    try:
        valor = json.loads(crudo.decode("utf-8")) if crudo else None
    except (ValueError, UnicodeDecodeError):
        return None
    return valor if isinstance(valor, dict) else None
