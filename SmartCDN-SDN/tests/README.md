# Test and validation notes

## Automated unit tests

From the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile controller.py topology.py server.py client.py monitor.py benchmark.py
```

The unit tests cover the content lookup logic in `server.py`. They do not start Ryu or Mininet.

## Local standalone smoke test (not an SDN integration test)

During preparation of this repository, `server.py` was started locally on TCP port 18080. The raw-socket client completed 2/2 `/about.txt` requests with HTTP 200 and complete bodies; the benchmark completed 3/3 requests; and direct socket requests returned `404 Not Found` for an unknown GET path and `405 Method Not Allowed` for POST. These checks validate only the server/client/benchmark logic on localhost, not the controller, OVS, Mininet, health monitor, or failover.

## Previously recorded Mininet evidence

The uploaded evidence logs and CSV files record:

- `pingall`: 0% packet loss (12/12 pairs recorded in the screenshot/report).
- Three trials of 10 requests for each policy (30/30 successes per policy).
- Concurrent clients h1 and h2 (10/10 successful responses each).
- Two Round-Robin failure/recovery cycles and one Adaptive failure/recovery cycle, each recording h3 unhealthy/ineligible, five successful requests routed through CDN-B, and subsequent recovery.

These results are retained from the source evidence bundle; they were not re-executed as part of this packaging task.

## Still to test in Mininet

- Continuous requests across a failure and measured interruption window.
- Both backends unavailable.
- `ovs-ofctl dump-flows` inspection.
- A controlled degradation experiment that demonstrates Adaptive behavior.

Record actual outputs and skip any test that fails; do not write expected results as if observed.
