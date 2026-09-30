"""Orquesta la corrida completa: leer -> filtrar -> transformar -> cargar.

Devuelve una `Corrida` con una fila por remito de Expreso Andino, que después
report.py convierte en el resumen para operaciones.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import load
from .api_client import ErrorAutenticacion, ExpresoClient
from .extract import filtrar_expreso_andino, leer_export
from .transform import NormalizadorProvincias, transformar


@dataclass
class Fila:
    nro_remito: str
    cliente: str
    destinatario: str
    localidad: str
    estado: str
    tracking_id: Optional[str] = None
    intentos: int = 0
    detalle: str = ""


@dataclass
class Corrida:
    archivo_export: str
    inicio: datetime
    fin: Optional[datetime] = None
    total_export: int = 0
    otros_transportes: int = 0
    sin_numero: int = 0
    duplicados_identicos: list = field(default_factory=list)
    filas: list = field(default_factory=list)
    interrumpida: str = ""  # motivo, si la corrida se cortó a mitad de camino

    @property
    def filas_andino(self) -> int:
        """Filas de Expreso Andino en el export, contando las repetidas."""
        return self.total_export - self.otros_transportes

    def contar(self, *estados) -> int:
        return sum(1 for f in self.filas if f.estado in estados)


def _datos_remito(remito: dict) -> dict:
    dest = remito.get("destinatario") if isinstance(remito.get("destinatario"), dict) else {}
    return {
        "nro_remito": str(remito.get("nro_remito") or "").strip(),
        "cliente": str(remito.get("cliente") or ""),
        "destinatario": str(dest.get("razon_social") or ""),
        "localidad": str(dest.get("localidad") or ""),
    }


def procesar(ruta_export, client: ExpresoClient, registros: Optional[list] = None) -> Corrida:
    corrida = Corrida(archivo_export=Path(ruta_export).name, inicio=datetime.now())
    registros = leer_export(ruta_export) if registros is None else registros

    lectura = filtrar_expreso_andino(registros)
    corrida.total_export = lectura.total_export
    corrida.otros_transportes = lectura.otros_transportes
    corrida.sin_numero = lectura.sin_numero
    corrida.duplicados_identicos = lectura.duplicados_identicos

    # Remitos con el mismo número y datos distintos: no se cargan.
    for nro in lectura.conflictos:
        apariciones = [r for r in registros if isinstance(r, dict) and str(r.get("nro_remito") or "").strip() == nro]
        corrida.filas.append(Fila(
            **_datos_remito(apariciones[0]), estado=load.CONFLICTO,
            detalle=f"El remito aparece {len(apariciones)} veces en el export con datos distintos",
        ))

    # La lista de provincias válidas la define la API: se pide una vez por corrida.
    provincias = NormalizadorProvincias(client.provincias())

    for remito in lectura.remitos:
        datos = _datos_remito(remito)
        if corrida.interrumpida:
            corrida.filas.append(Fila(**datos, estado=load.NO_PROCESADO, detalle=corrida.interrumpida))
            continue

        t = transformar(remito, provincias)
        if not t.ok:
            corrida.filas.append(Fila(**datos, estado=load.RECHAZADO_DATOS, detalle="; ".join(t.errores)))
            continue

        try:
            r = load.cargar_envio(client, t.payload)
        except ErrorAutenticacion as e:
            # Si la key deja de funcionar a mitad de camino, no seguimos (van a fallar todos),
            # pero sí dejamos registro de lo que ya se cargó y de lo que quedó sin procesar.
            corrida.interrumpida = f"La corrida se cortó: {e}"
            corrida.filas.append(Fila(**datos, estado=load.NO_PROCESADO, detalle=corrida.interrumpida))
            continue
        detalle = r.detalle
        if datos["nro_remito"] in lectura.duplicados_identicos:
            detalle = " ".join(x for x in [detalle, "Venía duplicado en el export: se procesó una sola vez."] if x)
        corrida.filas.append(Fila(**datos, estado=r.estado, tracking_id=r.tracking_id,
                                  intentos=r.intentos, detalle=detalle))

    corrida.filas.sort(key=lambda f: f.nro_remito)
    corrida.fin = datetime.now()
    return corrida
