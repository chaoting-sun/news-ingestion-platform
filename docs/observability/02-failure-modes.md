# Step 2 — Define What "Going Wrong" Looks Like

For each stage identified in Step 1, define the concrete symptoms of failure, and for the most critical dimensions, set quantitative tolerance baselines (SLOs).
This document answers "what counts as broken" and "how broken requires action" — not "why it broke" or "how to detect it."

---

## Pipeline Level

### Run Did Not Execute Normally

- **Did not run**: an expected pipeline run did not happen.
- **Delayed start**: the run eventually started, but much later than expected.
- **Early termination**: the run stopped before completing the main processing flow.
- **Overlapping execution**: multiple runs for the same source are in progress simultaneously.
- **Abnormally long processing time**: the run took significantly longer than the normal range.

### Abnormal Run Output

- **No output at all**: the run completed, but no new data entered the system.
- **Partial success, partial failure**: within a single run, only some work units were processed successfully.
- **Suspicious idle**: the run completed with no errors, but produced no new output, and this does not match reasonable expectations for the source's content.

---

## Run Startup

### Trigger

- **No trigger**: the run did not start at the expected scheduled time.
- **Delayed trigger**: the run started significantly later than the expected schedule time.

---

## Ingestion Main Flow

The failure modes below mean **data did not successfully enter the system**.

### Discover

- **Unable to obtain work list**: cannot reach the source site, or the request succeeds but no article URLs can be extracted from the response.
- **Abnormal work list**: the number or content of URLs retrieved deviates significantly from expectations — e.g., count is zero or non-article links are mixed in.

### Dedupe

- **Unable to complete existing-data check**: the dedupe query itself fails, blocking the rest of the flow.
- **Over-deduplication**: normal new content is mistakenly identified as already existing, causing articles that should be processed to be skipped.
- **Dedupe miss**: existing content is not correctly identified, allowing duplicate content to flow into the subsequent stages.

### Fetch

- **Unable to retrieve article page content**: HTTP request fails; no response received.
- **Retrieved content is not the expected article page**: request succeeds, but the response is not normal article HTML.
- **Abnormally long retrieval time**: response time significantly exceeds the normal range, slowing down the entire run.

### Parse

- **Unable to extract valid article data**: the page content cannot be parsed into structured article data.
- **Missing required fields**: parsing did not fail, but the output data is missing required fields.
- **Content misplacement**: parsing succeeded and all fields have values, but the content extracted is not from the article body.

### Persist

- **Unable to write to database**: the database operation failed; the new article was not saved.
- **Wrote incomplete or unreliable data**: the write succeeded, but the stored data has quality issues.
- **Duplicate data not handled correctly**: data that should have been identified as a duplicate was written as new data.

---

## Downstream Visibility

The failure modes below mean **data has successfully entered the system, but users cannot temporarily see or receive it**.

### Notify

- **Notification not sent**: new data was created, but the notification was not successfully delivered to the frontend.
- **Notify failure does not affect main flow completion**: the notify flow failed, but the pipeline still reports normal completion — the failure is silently swallowed.

### Cache Invalidate

- **Cache not correctly invalidated**: new data was created, but the cache still holds stale content.
- **User reads stale data**: the API returns a list that does not include newly ingested articles.

---

## Quantitative Baselines (SLI / SLO)

The above defines "what counts as broken." This section adds "how broken requires action."
Values are initial estimates; adjust based on real baselines once running.

| Metric | Definition | Target | Corresponding failure modes |
|--------|------------|--------|-----------------------------|
| Schedule start rate | Proportion of runs with `pipeline.started` within ±5 min of expected time | ≥ 99% | Did not run, delayed trigger |
| Run completion rate | Proportion of runs with `completion_status` ≠ "error" | ≥ 95% | Early termination |
| Run duration | `run_duration` p95 | < 120s | Abnormally long processing time |
| Article processing success rate | (created + skipped) ÷ input_count per run | ≥ 90% | Partial failure, no output at all |

Notify success rate, data freshness, and API response time have no targets set yet.
