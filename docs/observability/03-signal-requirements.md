# Step 3 — Work Backwards from Failure Modes to Required Signals

For each failure mode defined in Step 2, answer: "What signals do I need to see to know this might be happening?"
This step is signal requirements analysis only — no tool selection, no metric naming, no thresholds.

---

## Pipeline Level

Pipeline-level failure modes (did not run, early termination, abnormal output, etc.) do not require dedicated signals.
Instead, they are inferred from two sets of signals combined:

**A. Run lifecycle events**

The start time, end time, and whether each run completed normally.

- Questions answered: Did the run happen? When did it start? How long did it take? Did it finish normally or terminate midway? How many runs were active at the same time?
- Failure modes covered: did not run, delayed start, early termination, overlapping execution, abnormally long processing time.

**B. Run output summary**

At the end of each run: how many work units were fed in, how many succeeded, how many failed, how many were skipped.

- Questions answered: Did this run produce new data? Is the success rate reasonable? Given the input volume, does the result look suspicious?
- Failure modes covered: no output at all, partial success/partial failure, suspicious idle.

These two sets of signals form the skeleton of the entire pipeline. Every stage-level signal below adds detail on top of this skeleton.

---

## Run Startup

#### Trigger

**Failure modes:** no trigger, delayed trigger.

**Required signals:**

- Timestamp of the run-start event — answers "did the run start near the expected time."
- Gap since the previous run start — answers "is the trigger frequency stable."

**Minimum required:** run-start event (from it you can derive the gap and detect lateness).

**Defer:** the delta between scheduled time and actual start time (requires knowing when the task was enqueued; this information may not currently be available).

---

## Ingestion Main Flow

### Discover

**Failure modes:** unable to obtain work list, abnormal work list.

**Required signals:**

- Success or failure event for the discover stage — answers "was the work list successfully retrieved."
- Number of URLs retrieved — answers "is the quantity within a reasonable range."

**Minimum required:** success/failure event + URL count. Together these distinguish "complete failure" from "succeeded but abnormal quantity."

**Defer:** historical trend comparison for URL count (detecting "deviation from expectation" requires a baseline; initially can rely on human review).

---

### Dedupe

**Failure modes:** unable to complete existing-data check, over-deduplication, dedupe miss.

**Required signals:**

- Dedupe result per URL (pass vs. skip) — answers "how many URLs were identified as already existing."
- Skip ratio per run — answers "is the skip ratio for this run abnormally high."

How to interpret these two signals:

| Signal combination | Possible corresponding failure mode |
|--------------------|-------------------------------------|
| Dedupe query fails, run aborts | Unable to complete existing-data check (reflected in pipeline-level "early termination") |
| Abnormally high skip ratio, and source genuinely has new content | Over-deduplication |
| Normal skip ratio, but persist stage shows duplicate writes | Dedupe miss (requires cross-referencing persist signals) |

**Minimum required:** dedupe result per URL. From this you can compute the skip ratio.

**Defer:** cross-referencing with persist stage duplicate-write events (to detect dedupe misses).

---

### Fetch

**Failure modes:** unable to retrieve article page content, retrieved content is not the expected article page, abnormally long retrieval time.

**Required signals:**

- Success or failure event per fetch — answers "was a response received."
- Duration per fetch — answers "is the response speed normal."
- Basic response characteristics (status code, content size) — answers "does what was retrieved resemble a normal article page."

These three signals together distinguish the three failure modes: failure events → "unable to retrieve"; abnormal characteristics → "not expected content"; high duration → "abnormally long."

**Minimum required:** success/failure event + duration + at least one basic response characteristic (e.g., content size). The first two cover "unable to retrieve" and "abnormally long," but "content is not the expected article page" requires response characteristics — HTTP success, normal duration, but receiving a shell page or auth page cannot be detected from success/failure events alone.

**Defer:** finer-grained response characteristic analysis (e.g., content type, presence of specific page structure).

---

### Parse

**Failure modes:** unable to extract valid article data, missing required fields, content misplacement.

**Required signals:**

- Success or failure event per parse — answers "did parsing successfully produce structured data."
- List of fields present in each parse output (which fields have values, which do not) — answers "how complete is the data."

These two signals distinguish the first two failure modes: failure events → "unable to extract"; field list → "missing required fields."

**Minimum required:** success/failure event + field completeness.

**Defer:** content quality signals (e.g., body length, expected language or format characteristics). "Content misplacement" is the hardest failure mode to detect with automated signals; initially can only rely on manual sampling or downstream user reports.

---

### Persist

**Failure modes:** unable to write to database, wrote incomplete or unreliable data, duplicate data not handled correctly.

**Required signals:**

- Persist result per attempt (created, duplicate, failed) — answers "did this piece of data successfully enter the system, or was it rejected."

This single signal covers most failure modes: failure → "unable to write"; duplicate event patterns → "whether duplicate handling is correct."

**Minimum required:** persist result event.

**Defer:** "wrote incomplete data" cannot be detected from persist's own signals — it depends on the parse stage's field completeness signal. If the parse stage already tracks field completeness, persist does not need to track it again.

---

## Downstream Visibility

### Notify

**Failure modes:** notification not sent, notify failure does not affect main flow completion.

**Required signals:**

- Success or failure event for the notify stage — answers "was the notification successfully sent."
- When notify fails, the pipeline-level completion status — answers "was this failure reflected in the pipeline's result."

The second failure mode is not about notify itself, but the gap between notify failing and pipeline succeeding. This requires looking at the notify result alongside the run output summary.

**Minimum required:** notify success/failure event.

**Defer:** whether the downstream actually received it (requires frontend instrumentation or connection count information; not needed initially).

---

### Cache Invalidate

**Failure modes:** cache not correctly invalidated, user reads stale data.

**Required signals:**

- Cache invalidation event (whether it executed, whether it succeeded) — answers "when there is new data, was the cache cleared."

The second failure mode (user reads stale data) is an end-to-end outcome that cannot be fully confirmed from pipeline-internal signals alone. However, if persist has a creation event and the cache invalidation event also succeeded, it is reasonable to infer that the downstream should be able to read new data.

**Minimum required:** cache invalidation event.

**Defer:** end-to-end data freshness check (e.g., the latest article time in the API response vs. the latest article time in the database).

---

## Summary

The signal skeleton to build first, in priority order:

**Layer 1: Run-level (answers "is the system operating normally")**

1. Start and end event for each run (with timestamp, whether it completed normally)
2. Output summary for each run (input count, success count, failure count, skip count)

With these two, you can detect: did not run, delayed, terminated, too slow, no output, partial failure, suspicious idle.

**Layer 2: Stage-level (answers "which step went wrong")**

3. Success/failure event per stage
4. Duration per stage

With these two, you can localize anomalies found at the run level to a specific stage.

**Layer 3: Quality-level (answers "is the output correct")**

5. Discover URL count
6. Parse field completeness
7. Persist result classification (created / duplicate / failed)

With these three, you can detect quality failure modes (abnormal work list, missing fields, dedupe anomalies).

**Layer 4: Downstream visibility (answers "did the user see the update")**

8. Notify success/failure event
9. Cache invalidation event

Initially, build Layer 1 and 2. This already covers the majority of pipeline-level and stage-level failure modes.
Layers 3 and 4 can be added incrementally after Layers 1 and 2 are stable.
