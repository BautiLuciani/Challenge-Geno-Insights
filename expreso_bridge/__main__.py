"""Punto de entrada: python3 -m expreso_bridge <export.json>

Códigos de salida (para cuando se automatice con un cron / tarea programada):
  0 -> corrida completa. Puede haber remitos rechazados por datos: eso lo
       resuelve operaciones, el proceso hizo bien su trabajo.
  1 -> quedaron envíos sin cargar por fallas de Expreso Andino (conviene volver
       a correr más tarde, no duplica) o por una respuesta inesperada de la API.
  2 -> error de configuración o de entrada (API key, archivo, API caída al inicio).
       Si la API key deja de funcionar a mitad de la corrida, igual se genera
       el resumen con lo que se alcanzó a cargar.
"""
import argparse
import os
import sys

from . import load
from .api_client import ErrorApi, ErrorAutenticacion, ExpresoClient
from .pipeline import procesar
from .report import CARGADOS, REQUIEREN_ATENCION, escribir_resumen


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m expreso_bridge",
        description="Carga en Expreso Andino los remitos del export diario de LogiSur.",
    )
    parser.add_argument("export", help="Archivo JSON con el export de remitos del día")
    parser.add_argument("--api-url", default=os.environ.get("EXPRESO_API_URL", "http://localhost:8000"),
                        help="URL base de la API (default: $EXPRESO_API_URL o http://localhost:8000)")
    parser.add_argument("--salida", default="resultados", help="Carpeta donde se guarda el resumen (default: resultados)")
    parser.add_argument("--max-intentos", type=int, default=4, help="Intentos por envío ante errores de la API (default: 4)")
    args = parser.parse_args(argv)

    api_key = os.environ.get("EXPRESO_API_KEY")
    if not api_key:
        print("ERROR: falta la variable de entorno EXPRESO_API_KEY con la API key de Expreso Andino.", file=sys.stderr)
        return 2
    if not os.path.isfile(args.export):
        print(f"ERROR: no existe el archivo {args.export}", file=sys.stderr)
        return 2

    client = ExpresoClient(args.api_url, api_key, max_intentos=args.max_intentos)
    try:
        corrida = procesar(args.export, client)
    except ErrorAutenticacion as e:
        print(f"ERROR: {e}. Revisá EXPRESO_API_KEY.", file=sys.stderr)
        return 2
    except ErrorApi as e:
        print(f"ERROR: no se pudo consultar la API de Expreso Andino ({e}). No se cargó nada.", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: el export no tiene el formato esperado ({e}).", file=sys.stderr)
        return 2

    ruta_csv, ruta_md = escribir_resumen(corrida, args.salida)

    c = corrida.contar
    print(f"Remitos de Expreso Andino: {len(corrida.filas)} (de {corrida.total_export} en el export)")
    print(f"  Cargados:        {c(*CARGADOS)}")
    print(f"  Ya existían:     {c(load.YA_EXISTIA)}")
    print(f"  No cargados:     {c(*REQUIEREN_ATENCION)}")
    print(f"Resumen: {ruta_md}")
    print(f"Detalle: {ruta_csv}")

    if corrida.interrumpida:
        print(f"ERROR: {corrida.interrumpida}. Revisá EXPRESO_API_KEY.", file=sys.stderr)
        return 2
    return 1 if c(load.ERROR_TEMPORAL, load.ERROR) else 0


if __name__ == "__main__":
    sys.exit(main())
