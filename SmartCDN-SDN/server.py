"""Threaded low-level TCP/HTTP content server for the Smart CDN demo."""
import argparse
import datetime
import json
import socket
import threading
import urllib.parse

HOST = "0.0.0.0"
DEFAULT_PORT = 8080
MAX_HEADER_BYTES = 16 * 1024

_log_lock = threading.Lock()


def log(message):
    with _log_lock:
        print(message, flush=True)


def get_content(path, server_name):
    """Return (status, content_type, body_bytes) for a supported content path."""
    clean_path = urllib.parse.urlsplit(path).path
    if clean_path in ("", "/"):
        clean_path = "/index.html"

    now = datetime.datetime.now().isoformat(timespec="seconds")
    catalog = {
        "/health": (
            "application/json; charset=utf-8",
            json.dumps({"status": "ok", "server": server_name, "time": now}).encode("utf-8"),
        ),
        "/index.html": (
            "text/html; charset=utf-8",
            (
                "<!doctype html><html><body>"
                "<h1>Smart Content Delivery System</h1>"
                f"<p>Delivered by {server_name}</p><p>Time: {now}</p>"
                "<p>Try /about.txt, /video-demo.txt, /catalog.json, or /sample.bin.</p>"
                "</body></html>"
            ).encode("utf-8"),
        ),
        "/about.txt": (
            "text/plain; charset=utf-8",
            f"Smart CDN demonstration content. Served by {server_name} at {now}.\n".encode("utf-8"),
        ),
        "/video-demo.txt": (
            "text/plain; charset=utf-8",
            (
                f"Demo media segment delivered by {server_name}.\n".encode("utf-8")
                + (b"SMART-CDN-SEGMENT-0123456789\n" * 2048)
            ),
        ),
        "/catalog.json": (
            "application/json; charset=utf-8",
            json.dumps(
                {
                    "server": server_name,
                    "generated_at": now,
                    "content": ["/", "/about.txt", "/video-demo.txt", "/catalog.json", "/sample.bin"],
                },
                indent=2,
            ).encode("utf-8"),
        ),
        # Larger deterministic payload for throughput measurements.
        "/sample.bin": ("application/octet-stream", (b"SMART-CDN-PAYLOAD-0123456789abcdef\n" * 16384)),
    }

    item = catalog.get(clean_path)
    if item is None:
        body = f"Not found: {clean_path}\n".encode("utf-8")
        return "404 Not Found", "text/plain; charset=utf-8", body
    content_type, body = item
    return "200 OK", content_type, body


def read_http_headers(client_socket):
    """Read until the end of the HTTP header or a conservative size limit."""
    request = bytearray()
    terminator = b"\r\n\r\n"
    while terminator not in request:
        remaining = MAX_HEADER_BYTES + 1 - len(request)
        if remaining <= 0:
            raise ValueError("HTTP request headers are too large")
        chunk = client_socket.recv(min(2048, remaining))
        if not chunk:
            break
        request.extend(chunk)
        end = request.find(terminator)
        if end >= 0:
            if end + len(terminator) > MAX_HEADER_BYTES:
                raise ValueError("HTTP request headers are too large")
            break
        if len(request) > MAX_HEADER_BYTES:
            raise ValueError("HTTP request headers are too large")
    return bytes(request)


def handle_client(client_socket, client_address, server_name):
    try:
        client_socket.settimeout(5.0)
        raw_request = read_http_headers(client_socket)
        if not raw_request:
            return

        first_line = raw_request.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
        parts = first_line.split()
        if len(parts) < 2:
            status, content_type, body = "400 Bad Request", "text/plain; charset=utf-8", b"Malformed HTTP request\n"
            path = "(malformed)"
        elif parts[0].upper() != "GET":
            status, content_type, body = "405 Method Not Allowed", "text/plain; charset=utf-8", b"Only GET is supported\n"
            path = parts[1]
        else:
            path = parts[1]
            status, content_type, body = get_content(path, server_name)

        headers = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"X-CDN-Server: {server_name}\r\n"
            f"X-CDN-Path: {urllib.parse.urlsplit(path).path}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("iso-8859-1")
        client_socket.sendall(headers + body)
        log(f"[{server_name}] {client_address[0]}:{client_address[1]} {first_line!r} -> {status} ({len(body)} body bytes)")
    except (OSError, ValueError) as exc:
        log(f"[{server_name}] Error handling {client_address}: {exc}")
    finally:
        try:
            client_socket.close()
        except OSError:
            pass


def start_server(server_name, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((HOST, port))
        server_socket.listen(64)
        log(f"[{server_name}] Listening on {HOST}:{port}")
        try:
            while True:
                client_socket, client_address = server_socket.accept()
                worker = threading.Thread(
                    target=handle_client,
                    args=(client_socket, client_address, server_name),
                    daemon=True,
                )
                worker.start()
        except KeyboardInterrupt:
            log(f"[{server_name}] Shutting down")


def main():
    parser = argparse.ArgumentParser(description="Smart CDN TCP content server")
    parser.add_argument("name", nargs="?", default="CDN-Server", help="Name reported in responses")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    start_server(args.name, args.port)


if __name__ == "__main__":
    main()
