"""Resumen de la corrida para el equipo de operaciones.

Genera dos archivos:
- CSV: una fila por remito. Separado por ';' y con BOM UTF-8 para que Excel en
  español lo abra bien de un doble clic (acentos y columnas incluidos).
- Markdown: resumen corto para leer rápido o pegar en un mail / chat.
"""
import csv
from pathlib import Path

from . import load
from .pipeline import Corrida

ESTADO_LEGIBLE = {
    load.CARGADO: "Cargado",
    load.CARGADO_TRAS_ERROR: "Cargado (confirmado al reintentar)",
    load.YA_EXISTIA: "Ya existía en Expreso Andino",
    load.RECHAZADO_DATOS: "No enviado: datos incompletos o inválidos",
    load.RECHAZADO_API: "Rechazado por Expreso Andino",
    load.CONFLICTO: "No enviado: remito duplicado con datos distintos",
    load.ERROR_TEMPORAL: "Pendiente: Expreso Andino no respondió",
    load.ERROR: "Error inesperado",
    load.NO_PROCESADO: "No procesado: la corrida se interrumpió",
}

ACCION = {
    load.CARGADO: "",
    load.CARGADO_TRAS_ERROR: "",
    load.YA_EXISTIA: "",
    load.RECHAZADO_DATOS: "Corregir el remito en el sistema de LogiSur y volver a correr el proceso",
    load.RECHAZADO_API: "Revisar el detalle, corregir el remito y volver a correr el proceso",
    load.CONFLICTO: "Definir cuál es el remito correcto, corregir el export y volver a correr",
    load.ERROR_TEMPORAL: "Volver a correr el proceso más tarde (no duplica envíos)",
    load.ERROR: "Avisar a sistemas con el detalle",
    load.NO_PROCESADO: "Revisar la API key y volver a correr el proceso (no duplica)",
}

CARGADOS = (load.CARGADO, load.CARGADO_TRAS_ERROR)
REQUIEREN_ATENCION = (load.RECHAZADO_DATOS, load.RECHAZADO_API, load.CONFLICTO,
                      load.ERROR_TEMPORAL, load.ERROR, load.NO_PROCESADO)

COLUMNAS = ["nro_remito", "cliente", "destinatario", "localidad", "estado", "estado_codigo",
            "tracking_id", "intentos", "detalle", "accion_sugerida"]


def escribir_csv(corrida: Corrida, ruta: Path) -> None:
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(COLUMNAS)
        for fila in corrida.filas:
            w.writerow([
                fila.nro_remito, fila.cliente, fila.destinatario, fila.localidad,
                ESTADO_LEGIBLE.get(fila.estado, fila.estado), fila.estado,
                fila.tracking_id or "", fila.intentos or "", fila.detalle, ACCION.get(fila.estado, ""),
            ])


def _celda(texto) -> str:
    return str(texto or "").replace("|", "/").replace("\n", " ")


def generar_markdown(corrida: Corrida) -> str:
    c = corrida.contar
    andino = len(corrida.filas)
    lineas = [
        "# Resumen de carga · Expreso Andino",
        "",
        f"- **Export:** `{corrida.archivo_export}`",
        f"- **Corrida:** {corrida.inicio:%d/%m/%Y %H:%M:%S}"
        + (f" (duró {(corrida.fin - corrida.inicio).total_seconds():.1f} s)" if corrida.fin else ""),
        f"- **Remitos en el export:** {corrida.total_export} "
        f"({corrida.otros_transportes} de otros transportes, se ignoran)",
        f"- **Expreso Andino:** {corrida.filas_andino} filas → **{andino} remitos únicos**"
        + (f" ({corrida.filas_andino - andino} fila(s) repetida(s) o sin número, ver Notas)"
           if corrida.filas_andino != andino else ""),
        "",
    ]
    if corrida.interrumpida:
        lineas += [f"> ⛔ **{corrida.interrumpida}.** Los remitos marcados como \"No procesado\" "
                   "no se enviaron: revisar la API key y volver a correr (no duplica).", ""]
    lineas += [
        "## Totales",
        "",
        "| Resultado | Cantidad |",
        "| --- | ---: |",
        f"| ✅ Cargados en esta corrida | {c(*CARGADOS)} |",
        f"| ♻️ Ya existían (no se duplicaron) | {c(load.YA_EXISTIA)} |",
        f"| ❌ No cargados, requieren acción | {c(*REQUIEREN_ATENCION)} |",
        f"| **Total Expreso Andino** | **{andino}** |",
        "",
    ]

    atencion = [f for f in corrida.filas if f.estado in REQUIEREN_ATENCION]
    lineas += ["## ⚠️ Requieren atención", ""]
    if atencion:
        lineas += ["| Remito | Cliente | Destinatario | Problema | Qué hacer |", "| --- | --- | --- | --- | --- |"]
        for f in atencion:
            problema = f"**{ESTADO_LEGIBLE[f.estado]}**: {f.detalle}" if f.detalle else ESTADO_LEGIBLE[f.estado]
            lineas.append(f"| {f.nro_remito} | {_celda(f.cliente)} | {_celda(f.destinatario)} "
                          f"| {_celda(problema)} | {ACCION[f.estado]} |")
    else:
        lineas.append("Nada: todos los remitos quedaron cargados. 🎉")
    lineas.append("")

    ok = [f for f in corrida.filas if f.estado in CARGADOS + (load.YA_EXISTIA,)]
    if ok:
        lineas += ["## Cargados en Expreso Andino", "",
                   "| Remito | Destinatario | Localidad | Tracking | Estado | Nota |",
                   "| --- | --- | --- | --- | --- | --- |"]
        for f in ok:
            lineas.append(f"| {f.nro_remito} | {_celda(f.destinatario)} | {_celda(f.localidad)} "
                          f"| `{f.tracking_id or '-'}` | {ESTADO_LEGIBLE[f.estado]} | {_celda(f.detalle)} |")
        lineas.append("")

    notas = []
    if corrida.duplicados_identicos:
        notas.append("Remitos repetidos en el export con datos idénticos (se procesaron una sola vez): "
                     + ", ".join(corrida.duplicados_identicos) + ".")
    if corrida.sin_numero:
        notas.append(f"{corrida.sin_numero} registro(s) de Expreso Andino sin número de remito: no se pudieron procesar.")
    if notas:
        lineas += ["## Notas", ""] + [f"- {n}" for n in notas] + [""]
    return "\n".join(lineas)


def escribir_resumen(corrida: Corrida, carpeta) -> tuple:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = f"resumen_{Path(corrida.archivo_export).stem}_{corrida.inicio:%Y%m%d-%H%M%S}"
    ruta_csv, ruta_md = carpeta / f"{base}.csv", carpeta / f"{base}.md"
    escribir_csv(corrida, ruta_csv)
    ruta_md.write_text(generar_markdown(corrida), encoding="utf-8")
    return ruta_csv, ruta_md
