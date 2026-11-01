# Adaptive Selection Under Controlled Latency Degradation

Date: 27 October 2026
Environment: Ubuntu, Mininet, Open vSwitch, Ryu, OpenFlow 1.3

## Objective

Evaluate Adaptive backend selection when one backend experiences
controlled additional latency.

## Method

Adaptive selection was activated. An artificial 80 ms delay was applied
to switch interface s1-eth3, connected to CDN-A (h3). CDN-B (h4) was
left unchanged.

Client requests were sent to the virtual service
10.0.0.100:8080.

## Measurements

| Stage | CDN-A latency | CDN-B latency |
|---|---:|---:|
| Before impairment | 5.04 ms | 5.71 ms |
| During impairment | 99.98 ms | 5.11 ms |
| After impairment removal | 4.99 ms | 5.39 ms |

## Client results during impairment

- Successful complete HTTP 200 responses: 10/10
- Completed TCP responses: 10/10
- Average response time: 187.01 ms
- Average response throughput: 15766.43 kbps
- Average body throughput: 15726.21 kbps
- Requests served by CDN-A: 0
- Requests served by CDN-B: 10

## Interpretation

CDN-A's measured latency increased substantially during the controlled
impairment while CDN-B remained close to its baseline latency. All ten
client requests were served successfully by CDN-B.

This observed behavior is consistent with Adaptive selection avoiding
the degraded backend for new requests in this Mininet configuration.

After the impairment was removed, both latencies returned to
approximately 5 ms and both backends were healthy and eligible again.

## Limitations

This is a controlled Mininet experiment, not a production CDN benchmark.
The results describe this test run and do not establish universal
performance superiority for Adaptive selection. Existing connections
are not migrated by a backend-selection change.
