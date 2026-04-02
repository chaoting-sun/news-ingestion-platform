# Performance Benchmark

## Test Setup

- **Tool:** k6 with the `constant-arrival-rate` executor
- **Rate:** 100 requests per second
- **Duration:** 30 seconds
- **Target endpoint:** `GET /api/news/` (paginated list API)
- **Stack:** PostgreSQL 16, Redis 7 response cache (TTL 60 s)

### k6 Script

```javascript
export const options = {
  scenarios: {
    constant_rate: {
      executor: "constant-arrival-rate",
      rate: 100,
      timeUnit: "1s",
      duration: "30s",
      preAllocatedVUs: 20,
      maxVUs: 50,
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
  },
};
```

### Understanding `dropped_iterations`

The `constant-arrival-rate` executor attempts to start exactly 100 iterations per second. When all VUs are busy, k6 skips ("drops") scheduled iterations. A high `dropped_iterations` count means the server cannot keep up with the target load; near-zero means the target rate is effectively sustained.

---

## Test A — Daphne (single process) — Baseline

**Server:** `daphne -b 0.0.0.0 -p 8000 config.asgi:application`

```
  █ THRESHOLDS

    http_req_duration
    ✓ 'p(95)<500' p(95)=493.99ms

    http_req_failed
    ✓ 'rate<0.01' rate=0.00%

  █ TOTAL RESULTS

    HTTP
    http_req_duration..............: avg=78.65ms min=2.41ms med=4.85ms max=1.15s p(90)=327.49ms p(95)=493.99ms
    http_req_failed................: 0.00%  0 out of 2855
    http_reqs......................: 2855   95.145316/s

    EXECUTION
    dropped_iterations.............: 146    4.865575/s
    iterations.....................: 2855   95.145316/s
    vus_max........................: 50     min=20        max=50
```

---

## Test B — Gunicorn + 2 Uvicorn Workers — Optimised Deployment

**Server:** `gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:8000`

```
  █ THRESHOLDS

    http_req_duration
    ✓ 'p(95)<500' p(95)=33.96ms

    http_req_failed
    ✓ 'rate<0.01' rate=0.00%

  █ TOTAL RESULTS

    HTTP
    http_req_duration..............: avg=12.34ms min=1.76ms med=3.54ms max=441.37ms p(90)=9.53ms p(95)=33.96ms
    http_req_failed................: 0.00%  0 out of 2989
    http_reqs......................: 2989   99.597604/s

    EXECUTION
    dropped_iterations.............: 12     0.399857/s
    iterations.....................: 2989   99.597604/s
    vus_max........................: 32     min=20        max=32
```

---

## Comparison

| Metric | Daphne (1 process) | Gunicorn + 2 Uvicorn Workers | Improvement |
| --- | --- | --- | --- |
| Throughput | 95.1 req/s | 99.6 req/s | +4.7% |
| Avg Latency | 78.65 ms | 12.34 ms | 6.4× faster |
| Median Latency | 4.85 ms | 3.54 ms | 1.4× faster |
| p90 Latency | 327.49 ms | 9.53 ms | 34× faster |
| p95 Latency | 493.99 ms | 33.96 ms | 14.5× faster |
| Max Latency | 1.15 s | 441 ms | 2.6× faster |
| Dropped Iterations | 146 (4.9/s) | 12 (0.4/s) | 92% fewer |
| Max VUs Needed | 50 | 32 | 36% fewer |
| Error Rate | 0.00% | 0.00% | Same |

Note: throughput is the average sustained rate reported by k6, not an instantaneous peak.

Over the 30-second window the expected total is 3,000 iterations (30 s × 100 req/s). Daphne dropped 146 (4.9%), while Gunicorn + Uvicorn dropped only 12 (0.4%).

### Goal Assessment

| Configuration | Status | Details |
| --- | --- | --- |
| Daphne (1 process) | Near target but could not fully sustain 100 req/s | 146 dropped iterations; actual throughput 95.1 req/s |
| Gunicorn + 2 Uvicorn Workers | Target achieved | 12 dropped iterations; actual throughput ~100 req/s |

### Key Takeaways

1. **Tail latency dramatically improved.** Single-process Daphne suffered severe request queuing under load, with p95 reaching ~494 ms. Switching to 2 Uvicorn Workers for parallel processing brought p95 down to 34 ms — a 14.5× improvement.
2. **Near-zero dropped iterations.** Daphne dropped 146 iterations (unable to keep pace with the target rate), while Gunicorn + Uvicorn dropped only 12, effectively absorbing the full 100 req/s load.
3. **Headroom remains.** Higher fixed-rate tests are needed to determine the true ceiling of the optimised deployment.

---

## Conclusion

Under the single-process Daphne baseline, the system approached but could not fully sustain the 100 QPS target (95.1 req/s, 146 dropped iterations). Switching to Gunicorn managing 2 Uvicorn ASGI Workers brought the API to the target load at ~99.6 req/s with a 0% error rate and significantly reduced tail latency.

---

## Applied Optimisations

1. **Redis response cache** (`django-redis`) — list API uses the `cache_page` decorator with a 60-second TTL
2. **`defer("content")`** — list queries skip loading the large HTML body field, reducing database I/O
3. **Cache invalidation** — the scraper calls `cache.clear()` after inserting new articles. This is a simplified strategy suitable for low-traffic projects; production workloads should use fine-grained key-based invalidation or cache versioning
4. **Deployment optimisation** — Gunicorn manages 2 Uvicorn ASGI Workers, enabling parallel request handling via the pre-fork model
