"""Tests de la lógica de carga con un cliente falso que devuelve respuestas guionadas.

Así probamos cada escenario (503, 500 que igual crea, 409, 422, 401, caída de red)
sin depender de la API ni esperar los backoff reales.
"""
import unittest

from expreso_bridge import load
from expreso_bridge.api_client import ErrorAutenticacion, ErrorRed, ExpresoClient, Respuesta

PAYLOAD = {"external_ref": "R-1"}


class ClienteFalso(ExpresoClient):
    def __init__(self, respuestas, max_intentos=4):
        super().__init__("http://falso", "key", max_intentos=max_intentos, dormir=self._dormir)
        self.respuestas = list(respuestas)
        self.esperas = []
        self.llamadas = 0

    def _dormir(self, segundos):
        self.esperas.append(segundos)

    def crear_envio(self, payload):
        self.llamadas += 1
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def R(status, body=None):
    return Respuesta(status, body)


class TestCargarEnvio(unittest.TestCase):
    def test_201_cargado(self):
        c = ClienteFalso([R(201, {"tracking_id": "AND1"})])
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, r.tracking_id, r.intentos), (load.CARGADO, "AND1", 1))

    def test_409_sin_errores_previos_es_ya_existia(self):
        c = ClienteFalso([R(409, {"error": "duplicate", "tracking_id": "AND1"})])
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, r.tracking_id), (load.YA_EXISTIA, "AND1"))

    def test_503_se_reintenta_con_backoff(self):
        c = ClienteFalso([R(503), R(503), R(201, {"tracking_id": "AND1"})])
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, r.intentos), (load.CARGADO, 3))
        self.assertEqual(c.esperas, [1.0, 2.0])

    def test_500_que_igual_creo_el_envio(self):
        c = ClienteFalso([R(500), R(409, {"error": "duplicate", "tracking_id": "AND1"})])
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, r.tracking_id), (load.CARGADO_TRAS_ERROR, "AND1"))

    def test_caida_de_red_se_reintenta(self):
        c = ClienteFalso([ErrorRed("timed out"), R(201, {"tracking_id": "AND1"})])
        self.assertEqual(load.cargar_envio(c, PAYLOAD).estado, load.CARGADO)

    def test_falla_siempre_queda_error_temporal(self):
        c = ClienteFalso([R(503)] * 4)
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, c.llamadas), (load.ERROR_TEMPORAL, 4))
        self.assertEqual(c.esperas, [1.0, 2.0, 4.0])  # no espera después del último intento

    def test_422_no_se_reintenta(self):
        body = {"error": "validation_error", "details": [{"field": "recipient.province", "message": "unknown"}]}
        c = ClienteFalso([R(422, body)])
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, c.llamadas), (load.RECHAZADO_API, 1))
        self.assertIn("recipient.province", r.detalle)

    def test_401_corta_la_corrida(self):
        with self.assertRaises(ErrorAutenticacion):
            load.cargar_envio(ClienteFalso([R(401)]), PAYLOAD)

    def test_respuesta_inesperada_no_se_reintenta(self):
        c = ClienteFalso([R(400, {"error": "invalid_json"})])
        r = load.cargar_envio(c, PAYLOAD)
        self.assertEqual((r.estado, c.llamadas), (load.ERROR, 1))


if __name__ == "__main__":
    unittest.main()
