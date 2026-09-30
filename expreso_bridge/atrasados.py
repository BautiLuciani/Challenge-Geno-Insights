"""Opcional del challenge: consultar el estado de los envíos y listar los atrasados.

Uso:  python3 -m expreso_bridge.atrasados <export.json> [--hoy AAAA-MM-DD]

Criterios:
- Atrasado: no está DELIVERED y su fecha estimada de entrega es ANTERIOR a hoy.
  Si la fecha estimada es hoy, todavía puede llegar en el día: no es atrasado.
- Con incidencia: está en EXCEPTION pero su fecha estimada todavía no pasó.
  No entra en la definición de atrasado, pero es lo que operaciones querría mirar.

Los envíos se buscan en la API por external_ref (nro_remito) a partir del export:
no depende de ningún archivo local de corridas anteriores.
"""
import argparse
import csv
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from .api_client import ErrorApi, ErrorAutenticacion, ExpresoClient
from .extract import filtrar_expreso_andino, leer_export

ATRASADO = "ATRASADO"
INCIDENCIA = "CON_INCIDENCIA"
EN_TIEMPO = "EN_TIEMPO"
ENTREGADO = "ENTREGADO"
NO_CARGADO = "NO_CARGADO"
SIN_DATOS = "SIN_DATOS"

LEGIBLE = {
    ATRASADO: "Atrasado",
    INCIDENCIA: "Con incidencia",
    EN_TIEMPO: "En tiempo",
    ENTREGADO: "Entregado",
    NO_CARGADO: "No está cargado en Expreso Andino",
    SIN_DATOS: "No se pudo consultar",
}


@dataclass
class Seguimiento:
    nro_remito: str
    destinatario: str
    localidad: str
    clasificacion: str
    tracking_id: Optional[str] = None
    status: str = ""
    estimated_delivery: str = ""
    dias_atraso: int = 0
    detalle: str = ""


def clasificar(status: str, eta: Optional[date], hoy: date) -> tuple:
    """Devuelve (clasificación, días de atraso)."""
    if status == "DELIVERED":
        return ENTREGADO, 0
    if eta is not None and eta < hoy:
        return ATRASADO, (hoy - eta).days
    if status == "EXCEPTION":
        return INCIDENCIA, 0
    return EN_TIEMPO, 0


def _fecha(valor) -> Optional[date]:
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return None


def consultar(registros: list, client: ExpresoClient, hoy: date) -> list:
    seguimientos = []
    for remito in filtrar_expreso_andino(registros).remitos:
        dest = remito.get("destinatario") or {}
        s = Seguimiento(str(remito.get("nro_remito")).strip(), str(dest.get("razon_social") or ""),
                        str(dest.get("localidad") or ""), SIN_DATOS)
        try:
            items = client.buscar_por_ref(s.nro_remito)
            if not items:
                s.clasificacion = NO_CARGADO
            else:
                s.tracking_id = items[0].get("tracking_id")
                envio = client.estado_envio(s.tracking_id)
                s.status = envio.get("status", "")
                s.estimated_delivery = envio.get("estimated_delivery") or ""
                eta = _fecha(s.estimated_delivery)
                s.clasificacion, s.dias_atraso = clasificar(s.status, eta, hoy)
                if eta is None and s.clasificacion != ENTREGADO:
                    s.detalle = "La API no informó una fecha estimada válida"
        except ErrorAutenticacion:
            raise
        except ErrorApi as e:
            s.detalle = str(e)
        seguimientos.append(s)
    return seguimientos


def _celda(texto) -> str:
    return str(texto or "").replace("|", "/")


def generar_markdown(seguimientos: list, hoy: date, archivo_export: str) -> str:
    cuenta = lambda c: sum(1 for s in seguimientos if s.clasificacion == c)  # noqa: E731
    lineas = [
        "# Envíos atrasados · Expreso Andino", "",
        f"- **Fecha de referencia (hoy):** {hoy:%d/%m/%Y}",
        f"- **Envíos consultados:** los de Expreso Andino del export `{archivo_export}`",
        "- **Atrasado:** no entregado y con fecha estimada anterior a hoy.", "",
        "| Situación | Cantidad |", "| --- | ---: |",
    ]
    for c in (ATRASADO, INCIDENCIA, EN_TIEMPO, ENTREGADO, NO_CARGADO, SIN_DATOS):
        if cuenta(c) or c in (ATRASADO, INCIDENCIA):
            lineas.append(f"| {LEGIBLE[c]} | {cuenta(c)} |")
    lineas.append("")

    atrasados = sorted((s for s in seguimientos if s.clasificacion == ATRASADO),
                       key=lambda s: (-s.dias_atraso, s.nro_remito))
    lineas += ["## 🔴 Atrasados", ""]
    if atrasados:
        lineas += ["| Remito | Destinatario | Localidad | Tracking | Estado | Fecha estimada | Días de atraso |",
                   "| --- | --- | --- | --- | --- | --- | ---: |"]
        for s in atrasados:
            lineas.append(f"| {s.nro_remito} | {_celda(s.destinatario)} | {_celda(s.localidad)} | `{s.tracking_id}` "
                          f"| {s.status} | {_fecha(s.estimated_delivery):%d/%m/%Y} | {s.dias_atraso} |")
    else:
        lineas.append("No hay envíos atrasados. 🎉")
    lineas.append("")

    incidencias = [s for s in seguimientos if s.clasificacion == INCIDENCIA]
    if incidencias:
        lineas += ["## 🟠 Con incidencia (EXCEPTION, todavía dentro de fecha)", "",
                   "| Remito | Destinatario | Localidad | Tracking | Fecha estimada |",
                   "| --- | --- | --- | --- | --- |"]
        for s in incidencias:
            fecha = _fecha(s.estimated_delivery)
            lineas.append(f"| {s.nro_remito} | {_celda(s.destinatario)} | {_celda(s.localidad)} | `{s.tracking_id}` "
                          f"| {f'{fecha:%d/%m/%Y}' if fecha else '-'} |")
        lineas.append("")

    otros = [s for s in seguimientos if s.clasificacion in (NO_CARGADO, SIN_DATOS)]
    if otros:
        lineas += ["## Sin seguimiento", ""]
        lineas += [f"- {s.nro_remito} ({_celda(s.destinatario)}): {LEGIBLE[s.clasificacion]}"
                   + (f". {s.detalle}" if s.detalle else "") for s in otros]
        lineas.append("")
    return "\n".join(lineas)


def escribir(seguimientos: list, hoy: date, archivo_export: str, carpeta) -> tuple:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = f"atrasados_{hoy:%Y-%m-%d}_{datetime.now():%Y%m%d-%H%M%S}"
    ruta_csv, ruta_md = carpeta / f"{base}.csv", carpeta / f"{base}.md"
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nro_remito", "destinatario", "localidad", "situacion", "tracking_id",
                    "status_api", "fecha_estimada", "dias_atraso", "detalle"])
        for s in seguimientos:
            w.writerow([s.nro_remito, s.destinatario, s.localidad, LEGIBLE[s.clasificacion], s.tracking_id or "",
                        s.status, s.estimated_delivery, s.dias_atraso or "", s.detalle])
    ruta_md.write_text(generar_markdown(seguimientos, hoy, archivo_export), encoding="utf-8")
    return ruta_csv, ruta_md


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m expreso_bridge.atrasados",
                                     description="Lista los envíos de Expreso Andino atrasados.")
    parser.add_argument("export", help="Archivo JSON con el export de remitos")
    parser.add_argument("--hoy", type=date.fromisoformat, default=date.today(),
                        help="Fecha de referencia AAAA-MM-DD (default: hoy)")
    parser.add_argument("--api-url", default=os.environ.get("EXPRESO_API_URL", "http://localhost:8000"))
    parser.add_argument("--salida", default="resultados")
    args = parser.parse_args(argv)

    api_key = os.environ.get("EXPRESO_API_KEY")
    if not api_key:
        print("ERROR: falta la variable de entorno EXPRESO_API_KEY.", file=sys.stderr)
        return 2
    if not os.path.isfile(args.export):
        print(f"ERROR: no existe el archivo {args.export}", file=sys.stderr)
        return 2

    try:
        seguimientos = consultar(leer_export(args.export), ExpresoClient(args.api_url, api_key), args.hoy)
    except ErrorAutenticacion as e:
        print(f"ERROR: {e}. Revisá EXPRESO_API_KEY.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: el export no tiene el formato esperado ({e}).", file=sys.stderr)
        return 2

    ruta_csv, ruta_md = escribir(seguimientos, args.hoy, Path(args.export).name, args.salida)
    atrasados = sum(1 for s in seguimientos if s.clasificacion == ATRASADO)
    incidencias = sum(1 for s in seguimientos if s.clasificacion == INCIDENCIA)
    print(f"Envíos consultados: {len(seguimientos)} · Atrasados al {args.hoy:%d/%m/%Y}: {atrasados} "
          f"· Con incidencia: {incidencias}")
    print(f"Resumen: {ruta_md}")
    print(f"Detalle: {ruta_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
