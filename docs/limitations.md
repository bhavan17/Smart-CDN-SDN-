# Limitations and evidence gaps

The report and demonstration should describe these limitations honestly.

1. **Single switch:** the emulated topology uses one OVS switch. It demonstrates controller-driven backend selection, not alternate physical network paths or multi-switch resilience.
2. **Existing connections:** flows are selected per new TCP connection. The controller does not migrate an established TCP session when a backend fails.
3. **Monitor timing:** `monitor.py` probes h3 then h4 sequentially. A slow or hung probe can delay the next report; the controller treats health reports as stale after six seconds. The parallel-probe variant in the original archive was not the authoritative tested monitor and is not included.
4. **Latency scope:** the committed monitor reports TCP connect time. It does not measure full HTTP response time, packet loss, throughput, or link utilization.
5. **Adaptive validation:** a controlled 80 ms NetEm delay test increased CDN-A latency to approximately 99.98 ms while CDN-B remained near 5.11 ms. The Adaptive client test then sent 10/10 successful requests through CDN-B. This supports degradation-aware selection in the tested scenario, but does not establish universal performance superiority.
6. **Sample size and variability:** the current comparison uses three trials of ten requests per policy. Individual trial response times varied considerably; no production-scale claim should be made.
7. **No external baseline:** there is no baseline comparison against a non-SDN implementation.
8. **Additional validation:** continuous requests during a backend failure, a measured 1.51-second outage window, the both-backends-down controller state, OpenFlow flow-table inspection, HTTP 404/405 handling, and a NetEm latency-degradation test have been recorded. Explicit link down/up testing and a non-SDN baseline remain outside the current evidence.
9. **API trust model:** the REST API is bound to the lab controller environment and has no authentication. Do not expose it to an untrusted network.
