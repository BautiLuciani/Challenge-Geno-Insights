"""Test de punta a punta contra la API de prueba real (kit/expreso_api.py).

Levanta la API en un hilo, en un puerto libre, y corre el proceso completo dos
veces sobre el export del día para verificar que la segunda corrida no duplica.
"""
import importlib.util
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from expreso_bridge import load
from expreso_bridge.api_client import ExpresoClient
from expreso_bridge.pipeline import procesar

RAIZ = Path(__file__).resolve().parent.parent
EXPORT = RAIZ / "data" / "remitos_2026-09-30.json"


def cargar_api_de_prueba():
    spec = importlib.util.spec_from_file_location("expreso_api", RAIZ / "kit" / "expreso_api.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)  # cada carga arranca con la API "limpia"
    modulo.H.log_message = lambda *a: None  # silenciar logs en los tests
    return modulo


class TestPuntaAPunta(unittest.TestCase):
    def setUp(self):
        self.api = cargar_api_de_prueba()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.api.H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.client = ExpresoClient(url, self.api.API_KEY, espera_base=0)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_dos_corridas_sin_duplicar(self):
        primera = procesar(EXPORT, self.client)
        self.assertEqual(len(primera.filas), 23)
        self.assertEqual(primera.contar(load.CARGADO, load.CARGADO_TRAS_ERROR), 19)
        self.assertEqual(primera.contar(load.YA_EXISTIA), 1)
        self.assertEqual(primera.contar(load.RECHAZADO_DATOS), 3)
        self.assertEqual(primera.contar(load.ERROR_TEMPORAL, load.ERROR, load.RECHAZADO_API), 0)

        segunda = procesar(EXPORT, self.client)
        self.assertEqual(segunda.contar(load.CARGADO, load.CARGADO_TRAS_ERROR), 0)
        self.assertEqual(segunda.contar(load.YA_EXISTIA), 20)

        # Cada caso trampa terminó como corresponde
        por_remito = {f.nro_remito: f for f in primera.filas}
        self.assertEqual(por_remito["R-10000527"].estado, load.YA_EXISTIA)          # cargado "ayer"
        self.assertEqual(por_remito["R-10000612"].estado, load.CARGADO_TRAS_ERROR)  # 500 pero se creó
        for ref in ("R-10000554", "R-10000582"):                                   # 503, 503, 201
            self.assertEqual((por_remito[ref].estado, por_remito[ref].intentos), (load.CARGADO, 3))

        # Cada remito cargado existe una sola vez en la API
        for fila in primera.filas:
            if fila.estado != load.RECHAZADO_DATOS:
                self.assertEqual(len(self.client.buscar_por_ref(fila.nro_remito)), 1, fila.nro_remito)

    def test_atrasados_despues_de_cargar(self):
        from datetime import date
        from expreso_bridge import atrasados
        from expreso_bridge.extract import leer_export

        procesar(EXPORT, self.client)
        hoy = date(2026, 10, 3)
        seguimientos = atrasados.consultar(leer_export(EXPORT), self.client, hoy)

        self.assertEqual(len(seguimientos), 23)
        no_cargados = {s.nro_remito for s in seguimientos if s.clasificacion == atrasados.NO_CARGADO}
        self.assertEqual(no_cargados, {"R-10000477", "R-10000516", "R-10000541"})
        for s in seguimientos:
            if s.clasificacion == atrasados.ATRASADO:
                self.assertNotEqual(s.status, "DELIVERED")
                self.assertLess(date.fromisoformat(s.estimated_delivery), hoy)

    def test_api_key_que_deja_de_funcionar_a_mitad_de_corrida(self):
        client, api = self.client, self.api

        class ClienteQueSeRompe(ExpresoClient):
            creados = 0

            def crear_envio(self, payload):
                resp = super().crear_envio(payload)
                ClienteQueSeRompe.creados += 1
                if ClienteQueSeRompe.creados == 3:
                    self.api_key = "revocada"
                return resp

        c = ClienteQueSeRompe(client.base_url, api.API_KEY, espera_base=0)
        corrida = procesar(EXPORT, c)
        self.assertTrue(corrida.interrumpida)
        self.assertEqual(corrida.contar(load.CARGADO, load.CARGADO_TRAS_ERROR), 3)  # lo cargado queda registrado
        self.assertGreater(corrida.contar(load.NO_PROCESADO), 0)
        self.assertEqual(len(corrida.filas), 23)                                    # ningún remito se pierde

    def test_atrasados_con_api_caida_avisa_listado_incompleto(self):
        from datetime import date
        from expreso_bridge import atrasados
        from expreso_bridge.extract import leer_export

        caido = ExpresoClient("http://127.0.0.1:9", self.api.API_KEY, max_intentos=1)  # puerto sin servidor
        seguimientos = atrasados.consultar(leer_export(EXPORT), caido, date(2026, 10, 3))
        self.assertTrue(all(s.clasificacion == atrasados.SIN_DATOS for s in seguimientos))
        md = atrasados.generar_markdown(seguimientos, date(2026, 10, 3), EXPORT.name)
        self.assertIn("Listado incompleto", md)

    def test_api_key_invalida(self):
        from expreso_bridge.api_client import ErrorAutenticacion
        self.client.api_key = "mal"
        with self.assertRaises(ErrorAutenticacion):
            procesar(EXPORT, self.client)


if __name__ == "__main__":
    unittest.main()
