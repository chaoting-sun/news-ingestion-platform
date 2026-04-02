# Architecture Decisions

## 1. ASGI Server: Daphne vs Gunicorn + Uvicorn

| Criteria | Daphne | Gunicorn + Uvicorn |
| --- | --- | --- |
| **Process model** | Single process | Multi-process (pre-fork, `-w N`) |
| **WebSocket** | Native support (official Django Channels server) | ASGI support via Uvicorn Workers |
| **Throughput ceiling** | ~200–500 QPS | ~1,000+ QPS (4 workers) |
| **Complexity** | Single dependency | Two dependencies, longer command syntax |

### Decision: Gunicorn + Uvicorn

Load testing showed that single-process Daphne could not keep up at 100 QPS — p95 latency hit 494 ms and 4.9% of requests were dropped. Switching to Gunicorn + 2 Uvicorn Workers brought p95 down to 34 ms and the drop rate to 0.4%. See [`performance.md`](performance.md) for full results.

**Trade-off:** Two additional dependencies, but the measurable performance gain and alignment with production-standard deployment patterns justify the added complexity. Existing WebSocket routing (`ProtocolTypeRouter`) required no changes.

**When to revisit:** If higher throughput is needed, increase the `-w` worker count.

---

## 2. Load Testing Tool: wrk vs wrk2 vs k6 vs Locust

| Criteria | wrk | wrk2 | k6 | Locust |
| --- | --- | --- | --- | --- |
| **Load model** | Open-loop (saturate) | Fixed rate (`--rate N`) | Flexible (fixed rate, ramping, etc.) | Closed-loop (control concurrency) |
| **QPS control** | Indirect (`-t`, `-c`) | Direct (`--rate 100`) | Direct (`rate: 100`) | Indirect (`users`, `wait_time`) |
| **Coordinated omission** | Affected | Corrected | Accurate in fixed-rate mode | Affected |
| **Pass/fail thresholds** | None | None | Built-in (`thresholds`) | Manual implementation |
| **macOS ARM install** | Yes | Difficult (LuaJIT build issues) | Yes (`brew install k6`) | Yes (`pip install`) |

### Decision: k6

The goal is to verify the API can sustain 100 QPS. k6's `constant-arrival-rate` executor sends requests at a precise fixed rate, its built-in `thresholds` provide automatic pass/fail judgment, and the `dropped_iterations` metric directly quantifies whether the server kept pace with the target rate.

**When to revisit:** For HdrHistogram-grade latency precision, wrk2 is more suitable on compatible platforms. For complex user journeys with a visual dashboard, Locust is a better fit.

---

## 3. Redis Topology: Shared Instance vs Dedicated Containers

| Criteria | Single instance, separate DBs | Dedicated containers |
| --- | --- | --- |
| **Isolation** | Logical (DBs 0–15 share memory) | Physical (independent processes and memory) |
| **Eviction policy** | Shared (per-instance, not per-DB) | Independent (Cache: `allkeys-lru`, Broker: `noeviction`) |
| **Failure blast radius** | Redis crash affects all functions | Each container fails independently |
| **Complexity** | Zero additional configuration | Extra service, healthcheck, environment variables |

### Decision: Shared instance with DB-number isolation

The project's load is minimal — cache reads at ~100 KB/s, Celery dispatches one task per hour, and WebSocket broadcasts are infrequent. Resource contention and memory pressure are negligible. `cache.clear()` calls `FLUSHDB` on DB 1 only, leaving DB 0 (Celery broker + Channel Layer) untouched.

**When to revisit:** When traffic grows to the point where distinct eviction policies are needed (Cache: `allkeys-lru`, Broker: `noeviction`) or independent failure domains become important, split into two Redis containers.
