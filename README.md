# SmartCDN-SDN — Smart Content Delivery System

A lab-scale Software-Defined Networking (SDN) content-delivery demonstrator that uses TCP sockets, a small HTTP content server, Mininet, Open vSwitch (OVS), and a Ryu OpenFlow 1.3 controller. Clients access a logical virtual service at **10.0.0.100:8080**; the controller selects one of two backend servers, **CDN-A (h3, 10.0.0.3)** or **CDN-B (h4, 10.0.0.4)**.

> **Scope note:** this is a single-switch Mininet experiment, not a production CDN. Existing connections are not migrated when a backend fails. The current Adaptive policy uses the latency values reported by `monitor.py`; the committed monitor measures TCP connect time, not full HTTP round-trip time, bandwidth, or packet loss.

## Features

- Ryu controller with OpenFlow 1.3 and a virtual service address.
- Proxy ARP for the virtual IP and per-new-connection backend selection.
- Static, Round-Robin, and Adaptive backend-selection policies.
- TCP socket client and threaded TCP/HTTP backend servers.
- `/health` endpoint and active backend health monitoring.
- Flow removal for a backend that transitions to unhealthy.
- REST endpoints for status, health reports, policy selection, and administrative backend enable/disable.
- Client metrics for response time, received bytes, throughput, and backend identity.
- Batch and time-window modes in `benchmark.py`.

## Repository layout

```text
SmartCDN-SDN/
├── controller.py
├── topology.py
├── server.py
├── client.py
├── monitor.py
├── benchmark.py
├── requirements.txt
├── README.md
├── docs/
│   ├── architecture.md
│   ├── algorithms.md
│   ├── api.md
│   └── limitations.md
├── tests/
│   ├── README.md
│   └── test_server.py
├── evidence/
│   ├── logs/
│   ├── screenshots/
│   └── SmartCDN_Collected_Evidence.pdf
└── results/
    ├── performance_summary.csv
    ├── performance_trials.csv
    └── robustness_summary.csv
```

The duplicate `Screenshots/` folder, `client.py.working`, and `monitor_old_*.py` backups from the source archive were intentionally excluded. The authoritative files are the six scripts at the repository root. The PDF is retained as collected evidence, not represented as a final written report.

## Requirements

- Ubuntu VM with Python 3.
- Mininet and Open vSwitch installed and working.
- Ryu controller installed in a Python environment compatible with the VM.
- OpenFlow 1.3 support enabled for the OVS switch.
- Root privileges for Mininet and the health monitor (`mnexec`).

`requirements.txt` lists Ryu as the Python dependency. Mininet and Open vSwitch are system-level dependencies; installing the requirements file alone does **not** set up the full lab. If Ryu is already installed and working in your VM, do not reinstall it just for this repository.

## Network topology

See [`docs/architecture.md`](docs/architecture.md). The topology uses one OVS switch (`s1`), clients `h1` and `h2`, and backend hosts `h3` and `h4`. The VIP is a logical controller-managed address; it is not a fifth host.

| Host | Role | IP address | Switch port |
|---|---|---:|---:|
| h1 | Client 1 / default health-probe origin | 10.0.0.1 | 1 |
| h2 | Client 2 | 10.0.0.2 | 2 |
| h3 | CDN-A | 10.0.0.3 | 3 |
| h4 | CDN-B | 10.0.0.4 | 4 |
| Virtual service | Client-facing VIP | 10.0.0.100:8080 | Logical address |

## Start the system

Use four terminals. The commands below assume you cloned the repository to `/home/bhavan/SmartCDN-SDN`. Replace that path if your clone is in a different location.

### 1. Start the Ryu controller

```bash
ryu-manager --ofp-tcp-listen-port 6653 --wsapi-port 8080 \
  /home/bhavan/SmartCDN-SDN/controller.py
```

Wait for the Smart CDN application startup message. Keep the terminal open.

### 2. Start Mininet

In a second terminal:

```bash
sudo mn -c
sudo mn --custom /home/bhavan/SmartCDN-SDN/topology.py \
  --topo cdntopo \
  --controller remote,ip=127.0.0.1,port=6653 \
  --switch ovs,protocols=OpenFlow13
```

At the Mininet prompt, verify basic connectivity:

```text
mininet> pingall
```

The existing evidence records 0% packet loss (12/12 host pairs reported received). If the controller or switch was restarted, wait for the OpenFlow connection before continuing.

### 3. Start both backend servers

At the Mininet prompt:

```text
mininet> h3 python3 /home/bhavan/SmartCDN-SDN/server.py CDN-A &
mininet> h4 python3 /home/bhavan/SmartCDN-SDN/server.py CDN-B &
```

### 4. Start the health monitor

In a third regular Ubuntu terminal:

```bash
sudo python3 /home/bhavan/SmartCDN-SDN/monitor.py
```

The monitor probes `/health` from Mininet host `h1` approximately once per cycle. It requires two consecutive failed probes to mark a backend unhealthy and two consecutive successful probes to recover it. The controller treats reports as stale after 6 seconds. Keep the monitor running while testing.

Optional one-round diagnostic (does not update controller health):

```bash
sudo python3 /home/bhavan/SmartCDN-SDN/monitor.py --once
```

### 5. Check controller status

In another regular Ubuntu terminal:

```bash
python3 - <<'PY'
import json
import urllib.request
url = "http://127.0.0.1:8080/smartcdn/status"
with urllib.request.urlopen(url, timeout=3) as response:
    print(json.dumps(json.load(response), indent=2))
PY
```

Wait until both backends are shown as `healthy: true` and `eligible: true` before doing baseline tests.

## Run client requests

From the Mininet prompt:

```text
mininet> h1 python3 /home/bhavan/SmartCDN-SDN/client.py 10.0.0.100 /video-demo.txt --count 6
```

Try other supported paths: `/`, `/index.html`, `/about.txt`, `/video-demo.txt`, `/catalog.json`, `/sample.bin`, and `/health`.

## Change the selection policy

The supported names are `roundrobin`, `static`, and `adaptive`. In a regular Ubuntu terminal, use Python's standard library to post a policy update:

```bash
python3 - <<'PY'
import urllib.request
policy = "roundrobin"  # change to: static or adaptive
url = f"http://127.0.0.1:8080/smartcdn/policy/{policy}"
req = urllib.request.Request(url, data=b"", method="POST")
with urllib.request.urlopen(req, timeout=3) as response:
    print(response.read().decode())
PY
```

Policy changes affect backend selection for new connections. Flow rules for already established connections remain until they expire or are explicitly flushed.

## Benchmarking

The committed baseline results came from three trials of ten requests per policy (30 requests per policy). They were measured in the Mininet setup, not by the local smoke test described later in this README.

| Policy | Successful requests | Mean response time | Mean response throughput |
|---|---:|---:|---:|
| Round-Robin | 30/30 (100%) | 248.03 ms | 14,633.12 kbps |
| Static | 30/30 (100%) | 141.71 ms | 17,303.63 kbps |
| Adaptive | 30/30 (100%) | 191.67 ms | 14,446.92 kbps |

Details are in [`results/performance_trials.csv`](results/performance_trials.csv) and [`results/performance_summary.csv`](results/performance_summary.csv). The trials show substantial response-time variation. Static was fastest on these particular measurements; the results do not establish that it will be fastest in other conditions.

A controlled latency-degradation test was performed by applying an 80 ms NetEm delay to CDN-A. Its measured latency increased to approximately 99.98 ms while CDN-B remained near 5.11 ms. Under Adaptive, all 10 client requests were served by CDN-B. This demonstrates the observed behavior in this Mininet scenario, not universal performance superiority.

### Batch benchmark

Run from the Mininet prompt:

```text
mininet> h1 python3 /home/bhavan/SmartCDN-SDN/benchmark.py --label roundrobin_baseline --runs 3 --requests 10 --out /home/bhavan/SmartCDN-SDN/results/generated/roundrobin.csv
```

### Continuous-request benchmark

Useful during a planned backend-failure test:

```text
mininet> h1 python3 /home/bhavan/SmartCDN-SDN/benchmark.py --label failover_window --duration 25 --interval 0.5 --out /home/bhavan/SmartCDN-SDN/results/generated/failover_window.csv
```

The script creates the output directory when needed. For a failover observation, start the benchmark first, stop only the CDN-A server process from the Mininet CLI, observe the monitor/controller state, and restart CDN-A. Do not claim zero-loss failover unless the continuous log shows no failed requests during the transition.

### Direct-backend baseline

To provide a reference measurement without VIP-based SDN backend selection, the benchmark client can send requests directly to each backend. This bypasses the controller's load-balancing decision while retaining the Mininet/OVS network.

Run the following commands from the Mininet prompt with both backend servers running.

**CDN-A (h3):**

```text
mininet> h1 python3 /home/bhavan/SmartCDN-SDN/benchmark.py --target 10.0.0.3 --port 8080 --path /video-demo.txt --label direct_cdn_a_baseline --runs 3 --requests 10 --clients 1 --out /home/bhavan/SmartCDN-SDN/results/direct_baseline.csv
```

**CDN-B (h4):**

```text
mininet> h1 python3 /home/bhavan/SmartCDN-SDN/benchmark.py --target 10.0.0.4 --port 8080 --path /video-demo.txt --label direct_cdn_b_baseline --runs 3 --requests 10 --clients 1 --out /home/bhavan/SmartCDN-SDN/results/direct_baseline.csv
```

Each backend received 30 requests across three runs, for 60 requests total. Both benchmarks completed with 30/30 successful requests and no HTTP or socket errors. The CSV records request success, response time, throughput, and backend identity.

**Measured direct-backend results:**

| Direct backend | Successful requests | Mean response time | Mean response throughput |
|---|---:|---:|---:|
| CDN-A (h3, `10.0.0.3`) | 30/30 (100%) | 4.36 ms | 168,244.79 kbps |
| CDN-B (h4, `10.0.0.4`) | 30/30 (100%) | 4.33 ms | 221,387.19 kbps |

**Interpretation:** These are direct-backend reference results, not a fully non-SDN baseline. Traffic still traverses Mininet and OVS, but bypasses the VIP and controller-based backend selection. Compare these measurements with the VIP-based SDN results while noting this difference in the evaluation.


## REST API

See [`docs/api.md`](docs/api.md) for request bodies, examples, and semantics. Main endpoints:

- `GET /smartcdn/status`
- `POST /smartcdn/health`
- `POST /smartcdn/policy/{roundrobin|static|adaptive}`
- `POST /smartcdn/server/{h3|h4}/{up|down}`

Manual backend `down` is an administrative disable, not the same operation as killing the server and waiting for automatic health detection.

## Evidence and validation status

- `evidence/logs/` contains existing controller status snapshots and client logs from prior Mininet runs.
- `evidence/screenshots/` contains one canonical copy of the collected screenshots.
- `evidence/SmartCDN_Collected_Evidence.pdf` is retained from the uploaded project archive.
- `tests/README.md` distinguishes code checks, local-only smoke tests, and prior Mininet evidence.

Validation status (27 October 2026):

- All six Python source files passed syntax checks.
- The automated server test suite passed 5/5 tests.
- A standalone local server/client/benchmark smoke test passed during repository preparation. Those local-only checks do not establish Mininet integration.
- The recorded Mininet baseline benchmark completed 50/50 requests successfully, evenly distributed between CDN-A and CDN-B.
- During the continuous backend-failure experiment, 114/116 requests succeeded. Two ConnectionRefusedError failures occurred during the transition, and the benchmark measured a 1.51-second outage window.
- After recovery, a separate client test completed 10/10 requests successfully, split evenly between CDN-A and CDN-B.
- HTTP 404 and 405 edge-case checks passed through the virtual service.
- OpenFlow flow-table output was captured for the two backends.

See results/test_results_20261027.md and results/generated/ for the additional evidence. The failure timing and request success rate are measurements from a single run, not guarantees of performance under other conditions.

## Known limitations

Read [`docs/limitations.md`](docs/limitations.md). In brief: one switch only; existing connections are not migrated; monitor probes are sequential and have a finite timeout; adaptive selection uses TCP connect latency only; test sample size is small; no non-SDN baseline is recorded; and one continuous-failure experiment measured a 1.51-second outage window with two connection failures. This measurement applies only to that run and is not a guarantee.
