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

## Recorded Mininet Integration Evidence

The following results were recorded from the Mininet, Open vSwitch, and Ryu environment.

- **Topology connectivity:** `pingall` completed with zero packet loss across the four hosts.
- **Standard backend-selection tests:** Three trials of 10 requests per policy. Round-Robin, Static, and Adaptive each completed 30/30 requests successfully.
- **Concurrent-client testing:** Clients h1 and h2 each sent 10 requests under all three policies. All 60 requests completed successfully.
- **Adaptive latency-degradation test:** An additional 80 ms NetEm delay was applied to the CDN-A link. Measured TCP connection latency was approximately 99.98 ms for CDN-A and 5.11 ms for CDN-B. All 10 requests under Adaptive were served by CDN-B.
- **Automatic failure detection and batch failover:** The controller detected CDN-A failure, excluded it from backend eligibility, and directed new requests through CDN-B. The report documents two five-request cycles under each of the three selection policies, with 30/30 successful requests across the six cycles.
- **Backend recovery:** Recovery and restored eligibility were validated under Round-Robin, Adaptive, and Static. Each policy completed its recorded 10-request post-recovery client run successfully.
- **Continuous-request failover:** A separate time-window benchmark recorded 114 successful requests out of 116, with two connection-refused failures and a measured outage window of 1.51 seconds.
- **Both-backends-down state:** The controller status snapshot recorded both backends as unhealthy and ineligible, with an empty eligible-backend list. Subsequent status evidence recorded restored backend health.
- **OpenFlow inspection:** Captured `ovs-ofctl -O OpenFlow13 dump-flows s1` output contains forward and reverse backend flow rules with IP/MAC rewriting.
- **HTTP edge cases:** Requests to an unsupported path and an unsupported HTTP method returned HTTP 404 and HTTP 405 respectively.

Supporting CSV files, terminal logs, controller status snapshots, screenshots, and flow-table output are retained in the `results/` and `evidence/` directories.

These are previously recorded Mininet experiments. They are separate from the automated unit tests below and are not re-executed by the unit-test command.

## Additional Testing Boundaries

The current test package does not provide automated Mininet/Ryu integration tests. The following areas remain outside the recorded validation:

- Explicit switch-link down/up testing.
- Large-scale client and backend load testing.
- Comparison with a completely non-SDN network implementation.
- Production-scale performance and reliability testing.

Record actual outputs before describing any additional test as completed.
