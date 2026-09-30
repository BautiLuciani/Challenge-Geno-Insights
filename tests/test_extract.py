import unittest
from pathlib import Path

from expreso_bridge.extract import (
    filtrar_expreso_andino,
    leer_export,
    normalizar_transportista,
)

EXPORT = Path(__file__).resolve().parent.parent / "data" / "remitos_2026-09-30.json"


def remito(nro, transportista="Expreso Andino", **extra):
    return {"nro_remito": nro, "transportista": transportista, **extra}


class TestNormalizarTransportista(unittest.TestCase):
    def test_variantes_del_export(self):
        for variante in ["Expreso Andino", "EXPRESO ANDINO", "EXPRESO ANDINO ", "expreso andino", "Exp. Andino"]:
            self.assertEqual(normalizar_transportista(variante), "expreso andino", variante)

    def test_otros_transportes_no_matchean(self):
        for otro in ["Cruz del Norte", "RETIRA CLIENTE", "TRANSPORTE LITORAL", "Andino", "", None]:
            self.assertNotEqual(normalizar_transportista(otro), "expreso andino", otro)


class TestFiltrar(unittest.TestCase):
    def test_duplicado_identico_se_carga_una_vez(self):
        r = filtrar_expreso_andino([remito("R-1", bultos=1), remito("R-1", bultos=1)])
        self.assertEqual([x["nro_remito"] for x in r.remitos], ["R-1"])
        self.assertEqual(r.duplicados_identicos, ["R-1"])

    def test_duplicado_con_datos_distintos_es_conflicto(self):
        r = filtrar_expreso_andino([remito("R-1", bultos=1), remito("R-1", bultos=2)])
        self.assertEqual(r.remitos, [])
        self.assertEqual(r.conflictos, ["R-1"])

    def test_descarta_otros_transportes(self):
        r = filtrar_expreso_andino([remito("R-1"), remito("R-2", "Cruz del Norte")])
        self.assertEqual(r.otros_transportes, 1)
        self.assertEqual(len(r.remitos), 1)

    def test_export_real(self):
        r = filtrar_expreso_andino(leer_export(EXPORT))
        self.assertEqual(r.total_export, 51)
        self.assertEqual(r.otros_transportes, 27)
        self.assertEqual(len(r.remitos), 23)
        self.assertEqual(r.duplicados_identicos, ["R-10000507"])
        self.assertEqual(r.conflictos, [])


if __name__ == "__main__":
    unittest.main()
