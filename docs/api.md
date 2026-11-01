# REST API reference

The Ryu WSGI API is served at `http://127.0.0.1:8080`. These endpoints are intended for the local lab environment; they do not implement authentication.

## `GET /smartcdn/status`

Returns the VIP, active policy, eligible backend list, and per-backend administrative/health state, latency, last health-check timestamp, and selection count.

```bash
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8080/smartcdn/status', timeout=3) as r:
    print(json.dumps(json.load(r), indent=2))
PY
```

## `POST /smartcdn/policy/{policy}`

`{policy}` must be `roundrobin`, `static`, or `adaptive`. The body may be empty. The response contains the current status.

```python
import urllib.request
policy = "adaptive"
req = urllib.request.Request(
    f"http://127.0.0.1:8080/smartcdn/policy/{policy}", data=b"", method="POST"
)
with urllib.request.urlopen(req, timeout=3) as r:
    print(r.read().decode())
```

## `POST /smartcdn/health`

The monitor posts JSON with a backend name, boolean health state, and an optional latency value:

```json
{"server":"h3","healthy":true,"latency_ms":8.4}
```

Valid backend names are `h3` and `h4`. `healthy` must be a JSON boolean. `latency_ms`, when present, must be a finite non-negative number. This endpoint is primarily for the monitor; a direct health POST can alter controller state.

## `POST /smartcdn/server/{h3|h4}/{up|down}`

Changes the administrative `enabled` flag. `down` excludes the backend from new backend selection but is an administrative disable, not a simulated process crash. Existing installed connections may continue until they close or their flows expire. For the automatic failure test, stop the backend server process and let the monitor detect it instead of using this endpoint.

Example:

```python
import urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8080/smartcdn/server/h4/down", data=b"", method="POST"
)
with urllib.request.urlopen(req, timeout=3) as r:
    print(r.read().decode())
```
