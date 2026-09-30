import unittest
from datetime import date

from expreso_bridge.atrasados import ATRASADO, EN_TIEMPO, ENTREGADO, INCIDENCIA, clasificar

HOY = date(2026, 10, 3)


class TestClasificar(unittest.TestCase):
    def test_entregado_nunca_es_atrasado(self):
        self.assertEqual(clasificar("DELIVERED", date(2026, 10, 1), HOY), (ENTREGADO, 0))

    def test_fecha_pasada_sin_entregar_es_atrasado(self):
        self.assertEqual(clasificar("IN_TRANSIT", date(2026, 10, 1), HOY), (ATRASADO, 2))
        self.assertEqual(clasificar("CREATED", date(2026, 10, 2), HOY), (ATRASADO, 1))

    def test_fecha_de_hoy_no_es_atrasado(self):
        self.assertEqual(clasificar("IN_TRANSIT", HOY, HOY), (EN_TIEMPO, 0))

    def test_exception_vencido_es_atrasado(self):
        self.assertEqual(clasificar("EXCEPTION", date(2026, 10, 1), HOY), (ATRASADO, 2))

    def test_exception_en_fecha_es_incidencia(self):
        self.assertEqual(clasificar("EXCEPTION", date(2026, 10, 5), HOY), (INCIDENCIA, 0))

    def test_sin_fecha_no_se_marca_atrasado(self):
        self.assertEqual(clasificar("IN_TRANSIT", None, HOY), (EN_TIEMPO, 0))


if __name__ == "__main__":
    unittest.main()
