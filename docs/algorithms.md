# Backend selection and health logic

## Eligible backend pool

A backend is eligible only when its administrative `enabled` flag is true and its health state is true. The controller starts with both backends unhealthy, so it waits for monitor reports before selecting either one.

## Static

The controller chooses the first eligible backend in the configured backend order. In the normal state this is h3/CDN-A. If h3 is unavailable and h4 remains eligible, h4 becomes the first eligible backend and can serve new connections. Static does not distribute normal traffic across both backends.

## Round-Robin

The controller rotates through the ordered list of eligible backends using a selection counter modulo the eligible-pool length. When both backends are eligible, requests are distributed across h3 and h4. When only one remains eligible, all new connections go to that backend.

## Adaptive

The controller uses the `latency_ms` reports held for eligible backends. It computes a threshold:

`threshold = minimum_known_latency * 2.0 + 5.0 ms`

Eligible backends whose known latency is no greater than the threshold enter the selection pool. Selection then rotates through this pool. In the committed `monitor.py`, `latency_ms` is TCP connection-establishment time (`connect()` elapsed time); it is **not** full HTTP round-trip time and does not measure packet loss, bandwidth, link utilization, or end-to-end content-transfer quality. Unknown latency values are not currently treated as a separate explicit state in the adaptive pool filter.

A controlled latency-degradation experiment was conducted by applying an additional 80 ms NetEm delay to the link connected to CDN-A. During the impairment, the health monitor measured approximately 99.98 ms for CDN-A and 5.11 ms for CDN-B. Under the Adaptive policy, all 10 client requests completed successfully through CDN-B. After the impairment was removed, the measured latency values returned to approximately 4.99 ms for CDN-A and 5.39 ms for CDN-B, and both backends were healthy and eligible again. This experiment demonstrates degradation-aware backend selection under the tested Mininet conditions, but does not establish universal performance superiority for Adaptive.

## Health thresholds and fail-closed behavior

- Monitor interval: approximately one second plus probe execution time; probes are sequential.
- Consecutive failures before unhealthy: 2.
- Consecutive successes before recovery: 2.
- Controller stale-report threshold: 6 seconds.
- On unhealthy transition: controller flushes flows associated with the backend.
- Existing TCP sessions are not migrated to another backend.
