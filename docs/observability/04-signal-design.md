# Step 4 — Signal Design Blueprint

## A. Signal Design Overview

The skeleton of this observability version is composed of two forms:

- **Event**: each significant action (run started, run finished, stage completed/failed) emits a structured event with enough fields to reconstruct what happened at that moment. This is the primary source of truth.
- **Metric**: numeric aggregations derived from events (duration distributions, processing counts), used for trend observation and anomaly detection without needing to look up individual events.

Three layers:

1. **Run-level**: is the system running? What are the overall results? — the first thing to look at.
2. **Stage-level**: which step broke or slowed down? — used for pinpointing problems.
3. **Quality + downstream visibility**: is the output correct? Did the downstream see the update? — used for catching silent failures.

Each layer builds on the previous one. You can start with only the run-level layer, then progressively add stage-level and quality layers.

---

## B. Signal Design Table

### Run-level

| Signal | Covers which failure modes | Form | Minimum required fields | Priority | Needs to be read with |
|--------|---------------------------|------|------------------------|----------|----------------------|
| Run started | Did not run, delayed trigger, overlapping execution | event | run_id, source, timestamp | P0 | Run finished |
| Run finished | Early termination, abnormally long processing time, no output at all, partial success/partial failure, suspicious idle | event | run_id, source, timestamp, completion_status, duration, input_count, success_count, failure_count, skip_count | P0 | Run started |
| Run duration | Abnormally long processing time | metric | source | P0 | — |
| Processing counts | No output at all, partial success/partial failure, suspicious idle | metric | source, outcome | P0 | — |

**Run started + Run finished** form a pair. Run started alone can tell you whether a run happened and whether the trigger frequency is stable. Together, they can tell you whether the run completed, how long it took, and what it produced. Two consecutive Run started events with no Run finished in between indicates overlapping execution or a mid-run crash.

**Run duration** and **Processing counts** are metric forms of information already in the Run finished event, letting you see trends without querying individual events.

---

### Stage-level

| Signal | Covers which failure modes | Form | Minimum required fields | Priority | Needs to be read with |
|--------|---------------------------|------|------------------------|----------|----------------------|
| Stage outcome | All stage-level failure modes (general) | event | run_id, source, stage, duration, outcome, error_type (on failure); item-level stages additionally carry url | P0 | Run finished |
| Stage duration | Fetch duration anomaly, pinpointing which stage is slow | metric | source, stage | P0 | Run duration |

**Stage outcome** is a shared event template, but its emission granularity varies by stage. Discover and Cache invalidate emit one event per run (run-level); Dedupe / Fetch / Parse / Persist emit one event per URL (item-level). Shared fields (run_id, source, stage, duration, outcome) are consistent; item-level events additionally carry url. This is the primary signal for problem localization: after detecting an anomaly from Run finished, query Stage outcome by run_id to pinpoint the specific stage (and which URL, if it is item-level).

**Stage duration** tracks the duration distribution of each stage as a metric, used for observing trends (e.g., is fetch getting progressively slower).

---

### Quality Enrichments

The following are not independent signals, but **additional fields on Stage outcome events**. They let the same event answer more questions about output quality.

| Enrichment | Covers which failure modes | Added fields | Priority | Needs to be read with |
|------------|---------------------------|-------------|----------|----------------------|
| Discover: URL count | Abnormal work list, suspicious idle | url_count | P1 | Run finished |
| Fetch: response size | Retrieved non-expected content | response_size | P1 | — |
| Parse: field completeness | Missing required fields, wrote incomplete data | fields_present, fields_missing | P1 | Persist result type |
| Persist: result type | Unable to write, duplicate data not handled correctly, dedupe miss | result_type | P1 | Dedupe Stage outcome |

**How these enrichments help distinguish failure modes:**

- **Discover URL count** distinguishes "discover succeeded but retrieved 0 URLs" (abnormal work list) from "retrieved a normal quantity but all are existing" (requires cross-referencing Run finished's skip_count to determine — may be suspicious idle).
- **Fetch response size** catches "HTTP success but received an auth page or shell page" — the size will deviate significantly from a normal article page.
- **Parse field completeness + Persist result type** together catch "data went through the entire pipeline but is incomplete" — parse tells you which fields are missing, persist confirms it was still written.
- **Persist result type + Dedupe Stage outcome** together catch "dedupe says it is new, but persist finds it is a duplicate" — indicating a gap in the dedupe logic.

---

### Downstream Visibility

| Signal | Covers which failure modes | Form | Minimum required fields | Priority | Needs to be read with |
|--------|---------------------------|------|------------------------|----------|----------------------|
| Notify outcome | Notification not sent, notify failure does not affect main flow | event | run_id, article_id, delivery_result | P2 | Run finished |
| Cache invalidation outcome | Cache not correctly invalidated, user reads stale data | event | run_id, invalidation_result | P2 | Run finished |

These two signals confirm that "after data enters the system, the downstream can actually see it." They are P2 because the failure modes they cover (visibility delay) are less severe than "data never entered the system at all," and some cases can be indirectly inferred via Run finished's success_count combined with manual observation.

---

## C. Summary

### 1. Minimum signal set to implement in v1 (P0)

**Events (3):**
- Run started
- Run finished (with output summary)
- Stage outcome (per stage per URL, with duration and outcome)

**Metrics (3):**
- Run duration (by source)
- Stage duration (by source + stage)
- Processing counts (by source + outcome)

These 6 signals cover the following failure modes: did not run, delayed trigger, overlapping execution, early termination, abnormally long processing time, no output at all, partial success/partial failure, suspicious idle, and success/failure detection for all stage-level failure modes.

### 2. Things that are easiest to over-build — avoid these now

- **Do not add content-quality heuristics**. "Content misplacement" in parse is very difficult to detect automatically; attempting it in v1 would be high effort and low reliability. Mark it as a known blind spot.
- **Do not add end-to-end freshness probing**. Comparing API response vs. DB state requires additional probing infrastructure; not worth it in v1.
- **Do not break parse fields into independent metrics**. Field completeness as an event's additional field (P1) is sufficient; splitting into independent metrics causes dimension explosion with little benefit.
- **Do not add notify delivery confirmation**. Confirming that WebSocket consumers actually received the message requires frontend instrumentation; leave it for later.

### 3. How this design connects to the next step

This document is a **signal design blueprint**, not an implementation plan. The next step is to:

- Compare against the system's existing instrumentation to find which signals are already present and which are missing
- Determine the specific emission point for each signal
- Define naming conventions and field structure
- Build the first-version visualization around P0 signals

But that is for another phase.
