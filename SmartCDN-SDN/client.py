#!/usr/bin/env python3
"""TCP client for requesting content through the Smart CDN virtual IP."""

import argparse
import socket
import time

DEFAULT_VIP = "10.0.0.100"
DEFAULT_PORT = 8080
MAX_RESPONSE_HEADER_BYTES = 64 * 1024


def fetch_once(target_ip, port, path, timeout):
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {target_ip}:{port}\r\n"
        "Connection: close\r\n"
        "Accept-Encoding: identity\r\n"
        "User-Agent: SmartCDN-Lab/1.0\r\n\r\n"
    ).encode("ascii")

    start = time.perf_counter()
    phase = "connecting"
    response = bytearray()
    connect_ms = 0.0

    try:
        with socket.create_connection(
            (target_ip, port), timeout=timeout
        ) as sock:
            connect_ms = (time.perf_counter() - start) * 1000
            sock.settimeout(timeout)

            phase = "sending request"
            sock.sendall(request)

            phase = "reading HTTP headers"

            # Read until the complete HTTP header is available.
            while b"\r\n\r\n" not in response:
                chunk = sock.recv(8192)

                if not chunk:
                    raise ConnectionError(
                        "Connection closed before HTTP headers completed"
                    )

                response.extend(chunk)

                if len(response) > MAX_RESPONSE_HEADER_BYTES:
                    raise ValueError("HTTP headers exceed size limit")

            header_end = response.index(b"\r\n\r\n")
            header_bytes = bytes(response[:header_end])
            body = bytearray(response[header_end + 4:])

            headers_text = header_bytes.decode(
                "iso-8859-1", errors="replace"
            )
            lines = headers_text.split("\r\n")
            status_line = lines[0] if lines else ""

            headers = {}

            for line in lines[1:]:
                key, separator, value = line.partition(":")
                if separator:
                    headers[key.strip().lower()] = value.strip()

            content_length = None

            if "content-length" in headers:
                try:
                    content_length = int(headers["content-length"])
                except ValueError:
                    raise ValueError("Invalid Content-Length header")

                if content_length < 0:
                    raise ValueError("Negative Content-Length")

            server_header = headers.get("x-cdn-server", "unknown")

            if content_length is not None:
                if len(body) > content_length:
                    body = body[:content_length]

                phase = "reading HTTP body"

                # Read until the declared body length has arrived.
                while len(body) < content_length:
                    chunk = sock.recv(
                        min(8192, content_length - len(body))
                    )

                    if not chunk:
                        raise ConnectionError(
                            f"Incomplete body: received {len(body)} "
                            f"of {content_length} bytes"
                        )

                    body.extend(chunk)

            else:
                # Fallback for responses without Content-Length.
                phase = "reading body until connection closes"

                while True:
                    chunk = sock.recv(8192)

                    if not chunk:
                        break

                    body.extend(chunk)

            end = time.perf_counter()

    except (OSError, ValueError, ConnectionError) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(
            f"[ERROR] {phase} failed for "
            f"{target_ip}:{port}{path} after "
            f"{elapsed_ms:.2f} ms: {exc}"
        )

        return None

    # Calculate metrics only after a complete response has been received.
    elapsed_seconds = max(end - start, 1e-9)

    # Complete HTTP response = headers + separator + body.
    total_bytes = len(header_bytes) + 4 + len(body)

    try:
        status_code = int(status_line.split()[1])
    except (IndexError, ValueError):
        status_code = 0

    body_complete = (
        content_length is not None
        and len(body) == content_length
    )

    success = status_code == 200 and body_complete

    response_throughput = (
        total_bytes * 8 / elapsed_seconds
    ) / 1000

    body_throughput = (
        len(body) * 8 / elapsed_seconds
    ) / 1000

    body_preview = bytes(body[:500]).decode(
        "utf-8", errors="replace"
    )

    if len(body) > 500:
        body_preview += "\n... (body preview truncated)"

    print("\n" + "=" * 58)
    print(f"Request                 : GET {path}")
    print(f"Destination             : {target_ip}:{port}")
    print(f"Selected server         : {server_header}")
    print(f"TCP connect time        : {connect_ms:.2f} ms")
    print(f"Total response          : {(end - start) * 1000:.2f} ms")
    print(f"Received total bytes    : {total_bytes}")
    print(
        f"Received body bytes     : "
        f"{len(body)} / "
        f"{content_length if content_length is not None else 'unknown'}"
    )
    print(f"Response throughput     : {response_throughput:.2f} kbps")
    print(f"Body throughput         : {body_throughput:.2f} kbps")
    print(f"HTTP status             : {status_line}")
    print(f"Response complete       : {'YES' if body_complete else 'NO'}")
    print(f"Request result          : {'SUCCESS' if success else 'FAILED'}")
    print("Body preview            :\n" + body_preview)
    print("=" * 58)

    return {
        "elapsed_ms": (end - start) * 1000,
        "bytes": total_bytes,
        "body_bytes": len(body),
        "throughput_kbps": response_throughput,
        "body_throughput_kbps": body_throughput,
        "server": server_header,
        "status_code": status_code,
        "response_complete": body_complete,
        "success": success,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Request content through the Smart CDN"
    )

    parser.add_argument("target_ip", nargs="?", default=DEFAULT_VIP)
    parser.add_argument("path", nargs="?", default="/")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=5.0)

    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be at least 1")

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    if not args.path.startswith("/"):
        parser.error("path must begin with '/'")

    results = []

    for i in range(args.count):
        print(f"\n[Request {i + 1}/{args.count}]")

        result = fetch_once(
            args.target_ip,
            args.port,
            args.path,
            args.timeout,
        )

        if result is not None:
            results.append(result)

    successful = [r for r in results if r["success"]]

    print("\nSUMMARY")
    print(
        f"Successful complete HTTP 200 : "
        f"{len(successful)}/{args.count}"
    )
    print(
        f"Completed TCP responses     : "
        f"{len(results)}/{args.count}"
    )

    if successful:
        print(
            "Average response            : "
            f"{sum(r['elapsed_ms'] for r in successful) / len(successful):.2f} ms"
        )

        print(
            "Average response throughput : "
            f"{sum(r['throughput_kbps'] for r in successful) / len(successful):.2f} kbps"
        )

        print(
            "Average body throughput     : "
            f"{sum(r['body_throughput_kbps'] for r in successful) / len(successful):.2f} kbps"
        )

        print(
            "Servers observed            : "
            + ", ".join(r["server"] for r in successful)
        )

    else:
        print("No complete successful HTTP 200 responses.")


if __name__ == "__main__":
    main()
