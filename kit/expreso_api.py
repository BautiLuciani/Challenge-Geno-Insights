#!/usr/bin/env python3
"""API de prueba de Expreso Andino (solo para el challenge de Geno Insights).

Uso:  python3 expreso_api.py        -> queda escuchando en http://localhost:8000
No necesita instalar nada: usa solo la libreria estandar de Python 3.9+.
Los datos viven en memoria: si reiniciás el servidor, arranca de cero.
No hace falta que leas este archivo: la documentación de la API está en API.md.
"""
import json, hashlib, datetime, sys, base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

API_KEY = "andino-test-7f3a91"
PROVINCES = ["Buenos Aires", "Ciudad Autónoma de Buenos Aires", "Catamarca", "Chaco", "Chubut",
    "Córdoba", "Corrientes", "Entre Ríos", "Formosa", "Jujuy", "La Pampa", "La Rioja", "Mendoza",
    "Misiones", "Neuquén", "Río Negro", "Salta", "San Juan", "San Luis", "Santa Cruz", "Santa Fe",
    "Santiago del Estero", "Tierra del Fuego", "Tucumán"]
def _d(x):
    return base64.b64decode(x).decode()

_T = {_d(x) for x in ['Ui0xMDAwMDU1NA==', 'Ui0xMDAwMDU4Mg==']}
_G = _d('Ui0xMDAwMDYxMg==')
_P = _d('Ui0xMDAwMDUyNw==')
SHIPMENTS = {}
ATTEMPTS = {}

def _tid(ref):
    return "AND" + hashlib.sha1(ref.encode()).hexdigest()[:8].upper()

def _status(tid):
    h = int(hashlib.sha1(tid.encode()).hexdigest(), 16)
    status = ["CREATED", "IN_TRANSIT", "IN_TRANSIT", "DELIVERED", "DELIVERED", "EXCEPTION"][h % 6]
    eta = datetime.date(2026, 10, 1) + datetime.timedelta(days=(h // 7) % 6)
    return status, eta.isoformat()

def _create(body):
    tid = _tid(body["external_ref"])
    SHIPMENTS[body["external_ref"]] = dict(body, tracking_id=tid, created_at=datetime.datetime.now().isoformat(timespec="seconds"))
    return tid

_create({"external_ref": _P, "recipient": {"name": "(creado en la corrida de ayer)"}, "packages": 1, "weight_kg": 1.0, "service": "standard"})

def _validate(b):
    errs = []
    def err(f, m): errs.append({"field": f, "message": m})
    if not isinstance(b, dict):
        return [{"field": "body", "message": "must be a JSON object"}]
    if not isinstance(b.get("external_ref"), str) or not b.get("external_ref", "").strip():
        err("external_ref", "required string")
    r = b.get("recipient")
    if not isinstance(r, dict):
        err("recipient", "required object")
    else:
        for f in ("name", "street", "city", "province", "zip_code"):
            if not isinstance(r.get(f), str) or not r.get(f, "").strip():
                err("recipient." + f, "required non-empty string")
        if isinstance(r.get("province"), str) and r["province"].strip() and r["province"] not in PROVINCES:
            err("recipient.province", "unknown province, see GET /v1/provinces")
    p = b.get("packages")
    if not isinstance(p, int) or isinstance(p, bool) or p < 1:
        err("packages", "integer >= 1")
    w = b.get("weight_kg")
    if not isinstance(w, (int, float)) or isinstance(w, bool) or w <= 0:
        err("weight_kg", "number > 0")
    if b.get("service") not in ("standard", "express"):
        err("service", "one of: standard, express")
    dv = b.get("declared_value")
    if dv is not None and (not isinstance(dv, (int, float)) or dv < 0):
        err("declared_value", "number >= 0")
    return errs

class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        if self.headers.get("X-Api-Key") != API_KEY:
            self._send(401, {"error": "unauthorized", "message": "missing or invalid X-Api-Key header"})
            return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        if u.path == "/v1/provinces":
            return self._send(200, {"provinces": PROVINCES})
        if u.path == "/v1/shipments":
            ref = parse_qs(u.query).get("external_ref", [None])[0]
            items = [s for s in SHIPMENTS.values() if ref is None or s["external_ref"] == ref]
            return self._send(200, {"items": [{"tracking_id": s["tracking_id"], "external_ref": s["external_ref"]} for s in items]})
        if u.path.startswith("/v1/shipments/"):
            tid = u.path.rsplit("/", 1)[1]
            s = next((s for s in SHIPMENTS.values() if s["tracking_id"] == tid), None)
            if not s:
                return self._send(404, {"error": "not_found"})
            st, eta = _status(tid)
            return self._send(200, {"tracking_id": tid, "external_ref": s["external_ref"], "status": st, "estimated_delivery": eta})
        self._send(404, {"error": "not_found"})

    def do_POST(self):
        if not self._auth():
            return
        if urlparse(self.path).path != "/v1/shipments":
            return self._send(404, {"error": "not_found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            b = json.loads(self.rfile.read(n) or b"null")
        except Exception:
            return self._send(400, {"error": "invalid_json"})
        errs = _validate(b)
        if errs:
            return self._send(422, {"error": "validation_error", "details": errs})
        ref = b["external_ref"]
        ATTEMPTS[ref] = ATTEMPTS.get(ref, 0) + 1
        if ref in SHIPMENTS:
            return self._send(409, {"error": "duplicate", "message": "shipment already exists", "tracking_id": SHIPMENTS[ref]["tracking_id"]})
        if ref in _T and ATTEMPTS[ref] <= 2:
            return self._send(503, {"error": "service_unavailable", "message": "temporarily unavailable, retry later"})
        tid = _create(b)
        if ref == _G and ATTEMPTS[ref] == 1:
            return self._send(500, {"error": "internal_error"})
        self._send(201, {"tracking_id": tid, "external_ref": ref})

    def log_message(self, fmt, *args):
        sys.stderr.write("[expreso-api] %s\n" % (fmt % args))

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("Expreso Andino API de prueba en http://localhost:%d  (Ctrl+C para cortar)" % port)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
