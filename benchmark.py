#!/usr/bin/env python3
"""Smart CDN benchmark: records every request to a CSV and prints a summary.

Run INSIDE Mininet from a client host, for example:
  mininet> h1 python3 /home/bhavan/src/benchmark.py --label roundrobin_normal \
           --runs 10 --requests 20 --out /home/bhavan/results/results.csv

Modes
  batch    (default) --runs R, each run = --clients C threads x --requests N
  duration --duration S --interval I : one request every I seconds for S
           seconds; reports failures and the outage window (failover time).
Success = HTTP 200 AND complete body. Socket errors and HTTP errors are
counted separately.
"""
import argparse
import csv
import os
import socket
import statistics
import threading
import time

FIELDS = ["label", "mode", "run", "client", "seq", "t_rel_s", "server",
          "status", "success", "error", "connect_ms", "total_ms",
          "bytes", "kbps"]


def fetch(ip, port, path, timeout):
    """One HTTP GET over a raw TCP socket. Never raises; returns a dict."""
    req = (f"GET {path} HTTP/1.1\r\nHost: {ip}:{port}\r\nConnection: close\r\n"
           "Accept-Encoding: identity\r\nUser-Agent: SmartCDN-Bench/1.0\r\n\r\n"
           ).encode()
    out = {"server": "", "status": 0, "success": 0, "error": "",
           "connect_ms": "", "total_ms": "", "bytes": 0, "kbps": ""}
    t0 = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            out["connect_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            s.settimeout(timeout)
            s.sendall(req)
            buf = bytearray()
            while b"\r\n\r\n" not in buf:
                c = s.recv(8192)
                if not c:
                    raise ConnectionError("closed before headers")
                buf += c
                if len(buf) > 65536:
                    raise ValueError("headers too large")
            i = buf.index(b"\r\n\r\n")
            head = bytes(buf[:i]).decode("iso-8859-1").split("\r\n")
            body = bytearray(buf[i + 4:])
            hdr = {}
            for ln in head[1:]:
                k, sep, v = ln.partition(":")
                if sep:
                    hdr[k.strip().lower()] = v.strip()
            try:
                out["status"] = int(head[0].split()[1])
            except (IndexError, ValueError):
                out["status"] = 0
            out["server"] = hdr.get("x-cdn-server", "")
            clen = int(hdr["content-length"]) if "content-length" in hdr else None
            while clen is None or len(body) < clen:
                c = s.recv(8192)
                if not c:
                    break
                body += c
            complete = clen is not None and len(body) == clen
            el = max(time.perf_counter() - t0, 1e-9)
            out["total_ms"] = round(el * 1000, 3)
            out["bytes"] = i + 4 + len(body)
            out["kbps"] = round(out["bytes"] * 8 / el / 1000, 2)
            out["success"] = int(out["status"] == 200 and complete)
            if not complete:
                out["error"] = "incomplete_body"
            elif out["status"] != 200:
                out["error"] = f"http_{out['status']}"
    except (OSError, ValueError, ConnectionError) as exc:
        out["error"] = type(exc).__name__
        out["total_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return out


def write_csv(path, rows):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def mean_sd(v):
    if not v:
        return "n/a"
    return f"{statistics.mean(v):.2f} +/- {statistics.stdev(v) if len(v) > 1 else 0:.2f}"


def summarize(rows):
    ok = [r for r in rows if r["success"]]
    http_err = [r for r in rows if r["error"].startswith("http_")]
    sock_err = [r for r in rows if r["error"] and not r["error"].startswith("http_")]
    print(f"Requests            : {len(rows)}")
    print(f"Success (200+full)  : {len(ok)}  ({100 * len(ok) / max(len(rows), 1):.1f}%)")
    print(f"HTTP errors         : {len(http_err)}")
    print(f"Socket/other errors : {len(sock_err)}")
    if sock_err:
        kinds = {}
        for r in sock_err:
            kinds[r["error"]] = kinds.get(r["error"], 0) + 1
        print(f"  error types       : {kinds}")
    servers = {}
    for r in ok:
        servers[r["server"]] = servers.get(r["server"], 0) + 1
    print(f"Served by           : {servers}")
    if ok:
        print(f"Response ms         : {mean_sd([r['total_ms'] for r in ok])}  (mean +/- sd)")
        print(f"Throughput kbps     : {mean_sd([r['kbps'] for r in ok])}")


def batch_mode(a):
    rows, lock = [], threading.Lock()
    run_means = []
    for run in range(1, a.runs + 1):
        run_rows = []

        def worker(cid):
            for seq in range(1, a.requests + 1):
                t = time.perf_counter()
                r = fetch(a.target, a.port, a.path, a.timeout)
                r.update(label=a.label, mode="batch", run=run, client=cid,
                         seq=seq, t_rel_s=round(t - t_start, 3))
                with lock:
                    run_rows.append(r)

        t_start = time.perf_counter()
        th = [threading.Thread(target=worker, args=(c,)) for c in range(1, a.clients + 1)]
        [t.start() for t in th]
        [t.join() for t in th]
        rows += run_rows
        ok = [r["total_ms"] for r in run_rows if r["success"]]
        if ok:
            run_means.append(statistics.mean(ok))
        print(f"run {run:>2}/{a.runs}: ok {len(ok)}/{len(run_rows)}  "
              f"mean {statistics.mean(ok) if ok else float('nan'):.2f} ms")
    print("\n=== SUMMARY:", a.label, "===")
    summarize(rows)
    if len(run_means) > 1:
        print(f"Per-run mean ms     : {mean_sd(run_means)}  (across {len(run_means)} runs)")
    return rows


def duration_mode(a):
    rows, seq, t_start = [], 0, time.perf_counter()
    while time.perf_counter() - t_start < a.duration:
        seq += 1
        t = time.perf_counter()
        r = fetch(a.target, a.port, a.path, a.timeout)
        r.update(label=a.label, mode="duration", run=1, client=1, seq=seq,
                 t_rel_s=round(t - t_start, 3))
        rows.append(r)
        tag = r["server"] or r["error"]
        print(f"t={r['t_rel_s']:>6.2f}s  #{seq:<4} {'OK ' if r['success'] else 'FAIL'} {tag}", flush=True)
        time.sleep(max(0.0, a.interval - (time.perf_counter() - t)))
    print("\n=== SUMMARY:", a.label, "===")
    summarize(rows)
    fails = [r for r in rows if not r["success"]]
    if fails:
        first = fails[0]["t_rel_s"]
        later_ok = [r for r in rows if r["success"] and r["t_rel_s"] > first]
        last_fail = fails[-1]["t_rel_s"]
        print(f"First failure at    : t={first:.2f}s")
        print(f"Last failure at     : t={last_fail:.2f}s")
        rec = [r for r in later_ok if r["t_rel_s"] > last_fail]
        if rec:
            print(f"Outage window       : {rec[0]['t_rel_s'] - first:.2f} s "
                  f"(first failure -> first success after last failure)")
        else:
            print("Service had not recovered by the end of the test.")
    else:
        print("No failures observed.")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default="10.0.0.100")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--path", default="/video-demo.txt")
    p.add_argument("--label", required=True, help="condition name, e.g. adaptive_degraded")
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--requests", type=int, default=20, help="requests per client per run")
    p.add_argument("--clients", type=int, default=1, help="concurrent threads")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--duration", type=float, help="duration mode: total seconds")
    p.add_argument("--interval", type=float, default=0.5, help="duration mode: seconds between requests")
    p.add_argument("--out", help="CSV file to append rows to")
    a = p.parse_args()
    rows = duration_mode(a) if a.duration else batch_mode(a)
    if a.out:
        write_csv(a.out, rows)
        print(f"\nAppended {len(rows)} rows to {a.out}")


if __name__ == "__main__":
    main()
