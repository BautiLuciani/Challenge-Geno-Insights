import copy
import unittest
from pathlib import Path

from expreso_bridge.extract import filtrar_expreso_andino, leer_export
from expreso_bridge.transform import (
    NormalizadorProvincias,
    parsear_numero,
    transformar,
)

EXPORT = Path(__file__).resolve().parent.parent / "data" / "remitos_2026-09-30.json"

# Misma lista que devuelve GET /v1/provinces en la API de prueba.
PROVINCIAS_API = [
    "Buenos Aires", "Ciudad Autónoma de Buenos Aires", "Catamarca", "Chaco", "Chubut",
    "Córdoba", "Corrientes", "Entre Ríos", "Formosa", "Jujuy", "La Pampa", "La Rioja", "Mendoza",
    "Misiones", "Neuquén", "Río Negro", "Salta", "San Juan", "San Luis", "Santa Cruz", "Santa Fe",
    "Santiago del Estero", "Tierra del Fuego", "Tucumán",
]
PROV = NormalizadorProvincias(PROVINCIAS_API)

BASE = {
    "nro_remito": "R-1",
    "destinatario": {
        "razon_social": "Ferretería El Tornillo",
        "direccion": "Av. San Martín 1234",
        "localidad": "San Isidro",
        "provincia": "Buenos Aires",
        "codigo_postal": "1642",
        "telefono": "1145678901",
    },
    "bultos": 3,
    "peso_kg": "25,4",
    "valor_declarado": 150000.0,
    "servicio": "NORMAL",
}


def con(**cambios):
    r = copy.deepcopy(BASE)
    for clave, valor in cambios.items():
        if clave in r["destinatario"]:
            r["destinatario"][clave] = valor
        else:
            r[clave] = valor
    return r


class TestProvincias(unittest.TestCase):
    def test_variantes_del_export(self):
        casos = {
            "Buenos Aires": "Buenos Aires", "BA": "Buenos Aires", "Bs. As.": "Buenos Aires",
            "CABA": "Ciudad Autónoma de Buenos Aires", "Capital Federal": "Ciudad Autónoma de Buenos Aires",
            "Córdoba": "Córdoba", "Cba": "Córdoba", "Tucuman": "Tucumán", "Neuquen": "Neuquén",
            "Entre Ríos": "Entre Ríos", "Santa Fe": "Santa Fe", "Mendoza": "Mendoza",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(PROV.normalizar(entrada), esperado, entrada)

    def test_desconocida(self):
        self.assertIsNone(PROV.normalizar("Narnia"))


class TestNumeros(unittest.TestCase):
    def test_formatos(self):
        self.assertEqual(parsear_numero("145,1"), 145.1)
        self.assertEqual(parsear_numero("1.234,5"), 1234.5)
        self.assertEqual(parsear_numero(12.5), 12.5)
        self.assertEqual(parsear_numero("12.5"), 12.5)
        self.assertIsNone(parsear_numero("abc"))
        self.assertIsNone(parsear_numero(""))
        self.assertIsNone(parsear_numero(True))


class TestTransformar(unittest.TestCase):
    def test_remito_valido(self):
        t = transformar(con(), PROV)
        self.assertTrue(t.ok, t.errores)
        self.assertEqual(t.payload, {
            "external_ref": "R-1",
            "recipient": {
                "name": "Ferretería El Tornillo", "street": "Av. San Martín 1234", "city": "San Isidro",
                "zip_code": "1642", "province": "Buenos Aires", "phone": "1145678901",
            },
            "packages": 3,
            "weight_kg": 25.4,
            "service": "standard",
            "declared_value": 150000.0,
        })

    def test_urgente_es_express(self):
        self.assertEqual(transformar(con(servicio="URGENTE"), PROV).payload["service"], "express")

    def test_rechazos(self):
        casos = {
            "sin CP": (con(codigo_postal=""), "código postal"),
            "dirección en blanco": (con(direccion="  "), "dirección"),
            "cero bultos": (con(bultos=0), "bultos"),
            "peso cero": (con(peso_kg="0"), "peso"),
            "provincia rara": (con(provincia="Narnia"), "Provincia no reconocida"),
            "servicio raro": (con(servicio="PRIORITARIO"), "Servicio desconocido"),
            "valor negativo": (con(valor_declarado=-5), "Valor declarado"),
        }
        for nombre, (remito, texto) in casos.items():
            t = transformar(remito, PROV)
            self.assertFalse(t.ok, nombre)
            self.assertIsNone(t.payload, nombre)
            self.assertTrue(any(texto in e for e in t.errores), f"{nombre}: {t.errores}")

    def test_junta_todos_los_errores(self):
        t = transformar(con(codigo_postal="", bultos=0), PROV)
        self.assertEqual(len(t.errores), 2)

    def test_telefono_opcional(self):
        t = transformar(con(telefono=""), PROV)
        self.assertTrue(t.ok)
        self.assertNotIn("phone", t.payload["recipient"])

    def test_export_real(self):
        remitos = filtrar_expreso_andino(leer_export(EXPORT)).remitos
        resultados = [transformar(r, PROV) for r in remitos]
        rechazados = {t.nro_remito for t in resultados if not t.ok}
        self.assertEqual(rechazados, {"R-10000477", "R-10000516", "R-10000541"})
        self.assertEqual(sum(t.ok for t in resultados), 20)


if __name__ == "__main__":
    unittest.main()
