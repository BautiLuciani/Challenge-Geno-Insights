# Expreso Andino · API de envíos (v1)

API REST para cargar envíos y consultar su estado. Todo es JSON (UTF-8).

- **Base URL (entorno de prueba):** `http://localhost:8000` (levantala con `python3 expreso_api.py`)
- **Autenticación:** header `X-Api-Key: andino-test-7f3a91` en todas las llamadas. Sin él: `401`.

## GET /v1/provinces

Lista de provincias válidas. El campo `recipient.province` tiene que coincidir **exactamente** con uno de estos valores.

```json
{ "provinces": ["Buenos Aires", "Ciudad Autónoma de Buenos Aires", "Córdoba", "..."] }
```

## POST /v1/shipments

Crea un envío.

```json
{
  "external_ref": "R-10000451",
  "recipient": {
    "name": "Ferretería El Tornillo",
    "street": "Av. San Martín 1234",
    "city": "San Isidro",
    "province": "Buenos Aires",
    "zip_code": "1642",
    "phone": "1145678901"
  },
  "packages": 3,
  "weight_kg": 25.4,
  "declared_value": 150000.0,
  "service": "standard"
}
```

| Campo | Tipo | Obligatorio | Notas |
| --- | --- | --- | --- |
| `external_ref` | string | sí | Tu identificador. Es único: no puede haber dos envíos con la misma referencia. |
| `recipient.name`, `street`, `city`, `province`, `zip_code` | string | sí | No pueden estar vacíos. |
| `recipient.phone` | string | no | |
| `packages` | entero | sí | Mayor o igual a 1. |
| `weight_kg` | número | sí | Mayor a 0. |
| `declared_value` | número | no | Mayor o igual a 0. |
| `service` | string | sí | `standard` o `express`. |

**Respuestas**

| Código | Cuándo | Cuerpo |
| --- | --- | --- |
| `201` | Envío creado | `{"tracking_id": "AND1A2B3C4D", "external_ref": "..."}` |
| `401` | Falta o está mal la API key | `{"error": "unauthorized", ...}` |
| `409` | Ya existe un envío con ese `external_ref` | `{"error": "duplicate", "tracking_id": "..."}` |
| `422` | Datos inválidos | `{"error": "validation_error", "details": [{"field": "...", "message": "..."}]}` |
| `500` / `503` | Error de nuestro lado | `{"error": "..."}`. Se recomienda reintentar. |

## GET /v1/shipments?external_ref={ref}

Busca envíos por tu referencia. Devuelve `{"items": [{"tracking_id": "...", "external_ref": "..."}]}` (lista vacía si no existe).

## GET /v1/shipments/{tracking_id}

Estado de un envío.

```json
{ "tracking_id": "AND1A2B3C4D", "external_ref": "R-10000451", "status": "IN_TRANSIT", "estimated_delivery": "2026-10-02" }
```

`status` puede ser `CREATED`, `IN_TRANSIT`, `DELIVERED` o `EXCEPTION`.
