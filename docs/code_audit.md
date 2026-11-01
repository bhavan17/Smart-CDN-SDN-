# Source-code audit (repository packaging pass)

## Checks performed

- `python3 -m py_compile controller.py topology.py server.py client.py monitor.py benchmark.py`: PASS.
- `python3 -m unittest discover -s tests -v`: PASS, 5 tests.
- Local-only server/client smoke test on `127.0.0.1:18080`: 2/2 complete HTTP 200 responses.
- Local-only benchmark smoke test: 3/3 complete HTTP 200 responses.
- Local-only protocol checks: unknown GET returned `404 Not Found`; POST returned `405 Method Not Allowed`.

These were performed outside Mininet and do not validate Ryu/OVS dataplane integration.

## Findings and decisions

1. **Preserve current `monitor.py` for this repository pass.** The archive contains an alternate `monitor_old_1425.py` that probes in parallel and measures the whole health-request time, but it is not the evidence-producing canonical file and is not included. The committed `monitor.py` probes sequentially and reports TCP connect time. This behavior is documented rather than changed without a Mininet test.
2. **Adaptive behavior still needs a controlled impairment test.** Existing results show successful requests through both servers, but do not prove the policy reacts differently from Round-Robin when a backend is slow.
3. **Continuous failover timing remains unmeasured in Mininet.** Existing logs establish backend health transition, five requests routed through CDN-B, and recovery; they do not establish zero failed requests across the transition or an outage duration.
4. **No confirmed syntax or standalone HTTP issue was found in these checks.** The Ryu application itself cannot be meaningfully integration-tested without the user's Mininet/OVS/Ryu VM.

## Next validation session

Prioritize one continuous request stream while stopping/restarting only CDN-A's server; record failed requests, observed backend names, monitor transition time, and final controller status. Then test both backends down if time permits, and capture `ovs-ofctl dump-flows`. Do not replace the committed monitor with the alternate version unless the replacement passes that test.
