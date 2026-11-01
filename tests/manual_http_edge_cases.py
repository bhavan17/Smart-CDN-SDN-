import http.client

VIP = "10.0.0.100"
PORT = 8080

tests = [
    ("GET", "/__smartcdn_missing_test__", 404),
    ("POST", "/about.txt", 405),
]

failures = 0

for method, path, expected in tests:
    conn = http.client.HTTPConnection(VIP, PORT, timeout=5)

    try:
        if method == "POST":
            conn.request(method, path, body=b"")
        else:
            conn.request(method, path)

        response = conn.getresponse()
        body = response.read()
        server = response.getheader("X-CDN-Server", "unknown")

        passed = response.status == expected

        print(
            f"{'PASS' if passed else 'FAIL'} | "
            f"{method} {path} | "
            f"HTTP {response.status} | "
            f"Backend={server} | "
            f"Body={len(body)} bytes"
        )

        if not passed:
            failures += 1

    except Exception as exc:
        failures += 1
        print(f"FAIL | {method} {path} | {type(exc).__name__}: {exc}")

    finally:
        conn.close()

print(f"\nResult: {len(tests) - failures}/{len(tests)} checks passed")

raise SystemExit(1 if failures else 0)
