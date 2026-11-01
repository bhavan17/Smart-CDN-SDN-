#!/usr/bin/env python3
"""Smart CDN backend health monitor for Mininet.  Run with sudo (needs mnexec).

Probes each backend over the network FROM a client host (default h1), so the
probe crosses the switch and the backend's link. Detects: server process down
(connection refused), link down / path failure (timeout), and degraded links
(rising connect latency). Results go to the Ryu REST API.

Usage:  sudo python3 monitor.py [--probe-from h1] [--once]
"""
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

BACKENDS = {"h3": "10.0.0.3", "h4": "10.0.0.4"}
SERVER_PORT = 8080
CHECK_INTERVAL = 1.0
PROBE_TIMEOUT = 1.0
FAILURE_THRESHOLD = 2      # consecutive failures before UNHEALTHY
RECOVERY_THRESHOLD = 2     # consecutive successes before HEALTHY
CONTROLLER_URL = "http://127.0.0.1:8080/smartcdn/health"

# Exit code 2 = backend unreachable/refused (a real health failure).
# Any other non-zero code = probe infrastructure problem (state unchanged).
PROBE_SCRIPT = r"""
import http.client, socket, sys, time
ip, port = sys.argv[1], int(sys.argv[2])
conn = http.client.HTTPConnection(ip, port, timeout=1.0)
try:
    started = time.perf_counter()
    conn.connect()
    connect_ms = (time.perf_counter() - started) * 1000
    conn.request("GET", "/health", headers={"Connection": "close", "User-Agent": "SmartCDN-HealthMonitor/1.0"})
    response = conn.getresponse()
    body = response.read(4096)
    if response.status != 200:
        print("HTTP health check returned status " + str(response.status), file=sys.stderr)
        sys.exit(2)
    if b'"status": "ok"' not in body:
        print("HTTP health endpoint returned an unexpected body", file=sys.stderr)
        sys.exit(2)
    print("%.3f" % connect_ms)
except (OSError, socket.timeout, http.client.HTTPException) as e:
    print(type(e).__name__ + ": " + str(e), file=sys.stderr)
    sys.exit(2)
finally:
    conn.close()
"""


def ts():
    return time.strftime("%H:%M:%S")


def find_host_pid(host):
    """PID of the newest Mininet shell for <host> (ignores stale old sessions)."""
    found = []
    try:
        out = subprocess.run(["pgrep", "-f", f"mininet:{host}"],
                             capture_output=True, text=True, timeout=2).stdout
    except (subprocess.TimeoutExpired, OSError):
        return None
    for line in out.split():
        try:
            pid = int(line)
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\x00", b" ").decode(errors="replace")
            if f"mininet:{host}" not in cmd or "bash" not in cmd:
                continue
            with open(f"/proc/{pid}/stat") as f:
                start = int(f.read().rsplit(")", 1)[1].split()[19])
            found.append((start, pid))
        except (ValueError, OSError, IndexError):
            continue
    return max(found)[1] if found else None


def probe(pid, ip):
    """Return (True, latency_ms) / (False, None) / (None, None)=infra error."""
    try:
        r = subprocess.run(
            ["mnexec", "-a", str(pid), "python3", "-c", PROBE_SCRIPT,
             ip, str(SERVER_PORT)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT + 2)
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[{ts()}] [PROBE ERROR] {ip}: {exc}", flush=True)
        return None, None
    if r.returncode == 0:
        try:
            return True, float(r.stdout.strip())
        except ValueError:
            return None, None
    if r.returncode == 2:
        print(f"[{ts()}] [PROBE FAILED] {ip}: {r.stderr.strip()}", flush=True)
        return False, None
    print(f"[{ts()}] [PROBE ERROR] {ip}: rc={r.returncode} {r.stderr.strip()}",
          flush=True)
    return None, None


def report(server, healthy, latency_ms):
    body = json.dumps({"server": server, "healthy": healthy,
                       "latency_ms": latency_ms}).encode()
    req = urllib.request.Request(CONTROLLER_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[{ts()}] [API ERROR] {server}: {exc}", flush=True)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-from", default="h1",
                    help="Mininet host the probes originate from")
    ap.add_argument("--once", action="store_true",
                    help="single diagnostic round, no reporting")
    args = ap.parse_args()

    if os.geteuid() != 0:
        print("[MONITOR] Run with sudo (mnexec needs root).")
        return

    if args.once:
        # Diagnostic-only mode deliberately does not report health to the controller.
        pass

    st = {n: {"healthy": None, "fail": 0, "ok": 0, "first_fail": None,
              "first_ok": None} for n in BACKENDS}
    print(f"[{ts()}] [MONITOR] probing from {args.probe_from}; "
          f"interval={CHECK_INTERVAL}s fail>={FAILURE_THRESHOLD} "
          f"recover>={RECOVERY_THRESHOLD}", flush=True)

    try:
        while True:
            pid = find_host_pid(args.probe_from)
            if pid is None:
                print(f"[{ts()}] [PROBE ERROR] no Mininet host "
                      f"{args.probe_from} found", flush=True)
            else:
                for name, ip in BACKENDS.items():
                    s = st[name]
                    ok, lat = probe(pid, ip)
                    if args.once:
                        print(f"  {name} {ip}: healthy={ok} latency={lat}")
                        continue
                    if ok is None:
                        continue
                    now = time.time()
                    if ok:
                        s["ok"] += 1; s["fail"] = 0; s["first_fail"] = None
                        s["first_ok"] = s["first_ok"] or now
                    else:
                        s["fail"] += 1; s["ok"] = 0; s["first_ok"] = None
                        s["first_fail"] = s["first_fail"] or now

                    new = s["healthy"]
                    if not ok and s["healthy"] is not False \
                            and s["fail"] >= FAILURE_THRESHOLD:
                        new = False
                    elif ok and s["healthy"] is not True \
                            and s["ok"] >= RECOVERY_THRESHOLD:
                        new = True

                    if new is not s["healthy"]:
                        if report(name, new, lat if new else None):
                            delay = now - (s["first_ok"] if new
                                           else s["first_fail"])
                            s["healthy"] = new
                            print(f"[{ts()}] [HEALTH] {name} ({ip}) = "
                                  f"{'HEALTHY' if new else 'UNHEALTHY'} "
                                  f"(detected {delay:.1f}s after first "
                                  f"{'good' if new else 'failed'} probe)",
                                  flush=True)
                    elif ok and s["healthy"]:
                        report(name, True, lat)   # live latency every cycle
            if args.once:
                break
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("\n[MONITOR] Stopped.")


if __name__ == "__main__":
    main()
