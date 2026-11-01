# SmartCDN-SDN: Additional Validation Results

Date: 27 October 2026
Environment: Ubuntu VM, Mininet, Open vSwitch, Ryu, OpenFlow 1.3

## 1. Baseline Continuous Benchmark

- Requests: 50
- Successful requests: 50
- HTTP errors: 0
- Socket/other errors: 0
- CDN-A requests: 25
- CDN-B requests: 25
- Average response time: 165.20 ms
- Average throughput: 10350.21 kbps

## 2. Automatic Failure Detection

CDN-A's server process was stopped while continuous requests were running.

The controller subsequently reported:
- CDN-A (h3): enabled=true, healthy=false, eligible=false
- CDN-B (h4): enabled=true, healthy=true, eligible=true

The eligible-backend list contained only h4. This demonstrates automatic
exclusion of the failed backend while CDN-B remained available.

## 3. Continuous Failure Benchmark

- Total requests: 116
- Successful complete HTTP 200 responses: 114
- Success rate: 98.3%
- HTTP errors: 0
- Connection errors: 2
- Error type: ConnectionRefusedError
- First failure: 11.08 seconds
- Last failure: 12.08 seconds
- Measured outage window: 1.51 seconds
- Average response time: 129.38 ms
- Average throughput: 14444.18 kbps
- CDN-A responses recorded: 11
- CDN-B responses recorded: 103

The two connection failures occurred during the failure transition.
The measured outage window is specific to this benchmark and is not a
guarantee of failover time under other conditions.

## 4. Backend Recovery and Post-Recovery Requests

After CDN-A's server was restarted, the controller reported both
backends healthy and eligible.

A separate client test then completed:
- Successful HTTP responses: 10/10
- Completed TCP responses: 10/10
- CDN-A requests: 5
- CDN-B requests: 5
- Average response time: 485.66 ms
- Average response throughput: 8385.42 kbps
- Average body throughput: 8364.03 kbps

Round-Robin selection resumed across both backends.

## 5. HTTP Edge-Case Tests

The manual test script was run through the virtual service:
- GET to a missing path: HTTP 404 — passed
- POST to a valid content path: HTTP 405 — passed

These results apply to the tested requests and server configuration.

## 6. OpenFlow Flow-Table Inspection

Command:

    sudo ovs-ofctl -O OpenFlow13 dump-flows s1

The captured flow table contained client-to-backend and backend-to-client
rules for both CDN-A and CDN-B.

The forward rules rewrite the destination IP and MAC from the virtual
service to the selected backend. Reverse rules rewrite the backend's
source IP and MAC to the virtual service identity before forwarding
responses to the client.

The observed rules used priority 100 and an idle timeout of 120 seconds.
Packet counters were nonzero for the displayed per-connection rules.

Raw output is saved in:

    results/generated/flows_after_recovery.txt

## Evidence Files

- results/generated/failover_20261027.csv
- results/generated/failover_20261027.log
- results/generated/failover_recovery_20261027.csv
- results/generated/failover_recovery_20261027.log
- results/generated/flows_after_recovery.txt

## Limitations

- Two connection failures occurred during the continuous failure test.
- The measured outage window was 1.51 seconds in this run.
- The post-recovery client test was a separate run from the continuous
  failure benchmark.
- Adaptive selection was subsequently evaluated under a controlled backend-latency degradation; see Section 8 and results/generated/adaptive_degradation_20261027.md.
- These tests were performed in a Mininet emulation and are not a
  production-scale CDN benchmark.

## 7. Both-Backends-Down and Recovery Test

Both backend server processes were stopped while Ryu, Mininet, and the
health monitor remained running.

After allowing the monitor to detect the failures, the controller status
was captured in:

    results/generated/status_both_backends_down.json

The observed outage state showed both backends unhealthy and ineligible,
with an empty eligible-backend list.

Both backend servers were subsequently restarted. The controller later
reported both backends healthy and eligible again, confirming recovery
of the backend health state.

Note: This test establishes the controller's observed backend state and
subsequent recovery. No claim about zero-loss delivery during this
both-backends-down interval is made.

## 7. Both-Backends-Down and Recovery Test

Both backend server processes were stopped while Ryu, Mininet, and the
health monitor remained running.

After allowing the monitor to detect the failures, the controller status
was captured in:

    results/generated/status_both_backends_down.json

The observed outage state showed both backends unhealthy and ineligible,
with an empty eligible-backend list.

Both backend servers were subsequently restarted. The controller later
reported both backends healthy and eligible again, confirming recovery
of the backend health state.

Note: This test establishes the controller's observed backend state and
subsequent recovery. No claim about zero-loss delivery during this
both-backends-down interval is made.

## 8. Adaptive Selection Under Controlled Latency Degradation

An 80 ms artificial delay was applied to s1-eth3, the switch interface
connected to CDN-A. During the impairment, the health monitor measured
approximately 99.98 ms for CDN-A and 5.11 ms for CDN-B.

With Adaptive selected, a ten-request test completed 10/10 HTTP 200
responses, all served by CDN-B. Average response time was 187.01 ms,
average response throughput was 15766.43 kbps, and average body
throughput was 15726.21 kbps.

After the delay was removed, measured latencies returned to approximately
4.99 ms for CDN-A and 5.39 ms for CDN-B. Both backends were healthy and
eligible again.

The experiment provides evidence that Adaptive avoided the degraded
backend for new requests in this configuration. It does not establish
that Adaptive is universally faster than other policies.
