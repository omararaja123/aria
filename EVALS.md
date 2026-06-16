# ARIA Evaluation Layer Documentation

Complete specification for the evaluation system that measures ARIA's performance across runs and enables data-driven improvement.

---

## Overview

The **Evals Layer** (Step 12) computes three metrics after each newsletter is published, tracking whether ARIA is improving over time. Metrics are persisted in SQLite and visualized in the Streamlit dashboard.

**Why Evals?**
- Certification requirement: prove the system learns and improves
- Auditability: every run's performance is queryable and auditable
- Feedback loops: metrics guide tuning (profile weights, source credibility)
- Transparency: show stakeholders that the system works

---

## The Three Metrics

### Metric 1: Relevance Rate

**Purpose**: Measures how well the ranking and article selection matched human preferences.

**Formula**:
```
relevance_rate = approved_articles / (approved_articles + rejected_articles)
```

**Interpretation**:
- 1.0 = human approved every article (perfect ranking)
- 0.7–0.9 = good ranking; most articles matched preferences
- 0.5 = coin flip; half approved, half rejected
- 0.0–0.3 = poor ranking; human rejected most articles
- No feedback = 0.5 (neutral fallback)

**SQLite Query** (evals/relevance_eval.py):
```sql
SELECT feedback, COUNT(*) as count
FROM user_feedback
WHERE run_id = ?
GROUP BY feedback
```

**Details Dict Returned**:
```python
{
    "approved": int,           # Count of approved articles
    "rejected": int,           # Count of rejected articles
    "total": int,              # Total feedback count
    "rate": str,               # Formatted percentage (e.g., "75%")
    "score": float,            # 0.0–1.0 numeric score
}
```

**Real-World Example**:
- Run 1: 12 articles approved, 8 rejected → 60% (need improvement)
- Run 2: 15 articles approved, 5 rejected → 75% (better)
- Run 3: 18 articles approved, 2 rejected → 90% (excellent)

---

### Metric 2: Dedup Precision

**Purpose**: Measures how effectively the deduplicator prevented duplicate articles.

**Formula**:
```
dedup_precision = unique_articles / total_articles_published
```

**Interpretation**:
- 1.0 = all published articles were unique (dedup worked perfectly)
- 0.9 = 90% unique (10% duplicates slipped through)
- 0.8 = 80% unique (20% duplicates slipped through)
- <0.8 = dedup not working; investigate

**SQLite Query** (evals/dedup_eval.py):
```sql
SELECT article_count FROM newsletters WHERE run_id = ?
SELECT COUNT(*) FROM story_fingerprints WHERE newsletter_id = ?
```

**Details Dict Returned**:
```python
{
    "published_articles": int,    # Total articles published
    "unique_articles": int,       # Count with unique fingerprints
    "precision": str,             # Formatted percentage (e.g., "100%")
    "score": float,               # 0.0–1.0 numeric score
    "note": str,                  # "Deduplicator removed exact + fingerprint duplicates"
}
```

**Real-World Example**:
- Run 1: 20 articles published, 20 unique → 100% (dedup working)
- Run 2: 20 articles published, 18 unique → 90% (2 duplicates from RSS republish)
- Run 3: 20 articles published, 20 unique → 100% (back to perfect)

**Note**: Ideally, all published articles should be unique (dedup runs before Publisher). If <1.0, investigate cross-week fingerprint collisions.

---

### Metric 3: Source Calibration

**Purpose**: Measures how well the agent's credibility scores aligned with human feedback.

**Formula** (per source domain):
```
domain_calibration = 1.0 - |agent_credibility_score - human_approval_rate|
overall_calibration = mean(domain_calibration for all domains)
```

**Interpretation**:
- 1.0 = perfect agreement: high-credibility sources had high approval rates (and vice versa)
- 0.7–0.9 = good calibration: agent scores match human signals
- 0.5 = neutral: no correlation between scores and approvals
- 0.0–0.3 = poor calibration: agent scores opposite of human feedback

**SQLite Queries** (evals/source_eval.py):
```sql
-- Get human feedback by source
SELECT source_domain, feedback, COUNT(*) as count
FROM user_feedback
WHERE run_id = ?
GROUP BY source_domain, feedback

-- Get agent's credibility score for each domain
SELECT credibility_score FROM source_scores WHERE domain = ?
```

**Details Dict Returned**:
```python
{
    "overall": float,              # Mean calibration across all sources (0.0–1.0)
    "sources": {
        "example.com": {
            "agent_credibility_score": 0.8,     # From source_scores table
            "human_approval_rate": 0.75,        # From user_feedback
            "calibration": 0.95,                # How well they agree
            "articles_approved": 15,
            "articles_rejected": 5,
            "total_articles": 20,
        },
        "other.com": { ... },
    },
    "sources_analyzed": int,       # Number of unique domains in feedback
    "calibration_range": str,      # E.g., "0.65 - 0.98"
    "score": float,                # Overall calibration (0.0–1.0)
}
```

**Real-World Example**:

Source: `anthropic.com`
- Agent gave score: 0.9 (high credibility)
- Human approved 18/20 articles (90% approval rate)
- Calibration: 1.0 - |0.9 - 0.9| = 1.0 ✅ Perfect agreement

Source: `randomnewsblog.com`
- Agent gave score: 0.3 (low credibility)
- Human approved 2/20 articles (10% approval rate)
- Calibration: 1.0 - |0.3 - 0.1| = 0.8 ✅ Good agreement

Source: `hype.com`
- Agent gave score: 0.6 (moderate credibility)
- Human approved 2/20 articles (10% approval rate)
- Calibration: 1.0 - |0.6 - 0.1| = 0.5 ⚠️ Agent overestimated

---

## Eval Runner (eval_runner.py)

**Main Entry Point**: `run_evals(run_id: str) -> Dict[str, Any]`

**Orchestration Flow**:
```python
def run_evals(run_id):
    # 1. Compute each metric
    relevance_score, relevance_details = relevance_rate_eval(run_id)
    dedup_score, dedup_details = dedup_precision_eval(run_id)
    calibration_score, calibration_details = source_calibration_eval(run_id)
    
    # 2. Log each metric to eval_results table
    for metric_name, value, details in [
        ("relevance_rate", relevance_score, relevance_details),
        ("dedup_precision", dedup_score, dedup_details),
        ("source_calibration", calibration_score, calibration_details),
    ]:
        eval_id = uuid.uuid4()
        INSERT INTO eval_results
            (eval_id, run_id, metric_name, value, details, timestamp)
        VALUES (eval_id, run_id, metric_name, value, json.dumps(details), now())
    
    # 3. Return aggregated summary
    return {
        "run_id": run_id,
        "timestamp": ISO timestamp,
        "metrics": { relevance_rate, dedup_precision, source_calibration },
        "details": { relevance_rate, dedup_precision, source_calibration },
        "summary": human-readable text,
    }
```

**Return Value Structure**:
```python
{
    "run_id": "abc123...",
    "timestamp": "2026-06-15T20:13:50.605601",
    "metrics": {
        "relevance_rate": 0.6,
        "dedup_precision": 1.0,
        "source_calibration": 0.76,
    },
    "details": {
        "relevance_rate": { "approved": 3, "rejected": 2, ... },
        "dedup_precision": { "published_articles": 5, ... },
        "source_calibration": { "overall": 0.76, "sources": {...}, ... },
    },
    "summary": "ARIA Evaluation Results...",
}
```

**Helper Function**: `get_recent_eval_runs(limit: int = 4) -> List[Dict]`

Returns the N most recent runs with all their metrics, used by the Streamlit dashboard:
```python
[
    {
        "run_id": "abc123...",
        "timestamp": "2026-06-15T20:13:50",
        "metrics": { "relevance_rate": 0.6, ... },
        "details": { ... },
    },
    { ... },  # Previous runs
]
```

---

## SQLite Integration

### Tables Queried

**user_feedback** (queries for relevance_rate and source_calibration):
```sql
CREATE TABLE user_feedback (
    feedback_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    article_id TEXT NOT NULL,
    source_domain TEXT,                   -- NEW (Step 12)
    action TEXT NOT NULL,                 -- "keep", "remove", "reorder"
    feedback TEXT,                        -- "approved", "rejected", null
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    reviewer_notes TEXT
)
```

**source_scores** (queries for source_calibration):
```sql
CREATE TABLE source_scores (
    domain TEXT PRIMARY KEY,
    credibility_score REAL DEFAULT 0.5,  -- Agent's assessment (0.0–1.0)
    ...
)
```

**newsletters** (queries for dedup_precision):
```sql
CREATE TABLE newsletters (
    newsletter_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ...
    article_count INTEGER,               -- Total articles published
)
```

**story_fingerprints** (queries for dedup_precision):
```sql
CREATE TABLE story_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    newsletter_id TEXT,                  -- Links to newsletters.newsletter_id
    ...
)
```

**eval_results** (writes all metrics):
```sql
CREATE TABLE eval_results (
    eval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,           -- "relevance_rate", "dedup_precision", "source_calibration"
    value REAL,                          -- Numeric score (0.0–1.0)
    details TEXT,                        -- JSON with supporting stats
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
CREATE INDEX idx_eval_results_run ON eval_results(run_id)
```

### Data Flow

```
Publisher finishes
  ↓
user_feedback table populated (from human_review_edits)
  ↓
run_evals(run_id) called
  ↓
Queries: user_feedback, source_scores, newsletters, story_fingerprints
  ↓
Computes: relevance_rate, dedup_precision, source_calibration
  ↓
Writes: 3 rows to eval_results table
  ↓
Returns: aggregated summary
  ↓
Streamlit dashboard queries eval_results
  ↓
Metrics displayed in UI
```

---

## Streamlit Dashboard Integration

### File: ui/review_app.py

**Metrics Panel** (expandable, enabled by default):

```python
if EVALS_AVAILABLE:
    with st.expander("📊 Performance Metrics (Last 4 Runs)", expanded=True):
        recent_runs = get_recent_eval_runs(limit=4)
        
        # KPI Cards (Latest Run)
        st.metric("Relevance Rate", f"{relevance_rate:.1%}", delta="↑ Human approvals")
        st.metric("Dedup Precision", f"{dedup:.1%}", delta="✅ No duplicates")
        st.metric("Source Calibration", f"{calib:.1%}", delta="✅ Agent & human agree")
        
        # Historical Trend Table (Last 4 Runs)
        st.dataframe(trend_data, columns=["Run ID", "Relevance", "Dedup", "Calibration", "Timestamp"])
```

**Layout**:
1. **Metrics Panel Header** — "📊 Performance Metrics (Last 4 Runs)"
2. **3 KPI Cards** (current run)
   - Relevance Rate: green if >70%, red if <70%
   - Dedup Precision: green if 100%, yellow if <100%
   - Source Calibration: green if >70%, yellow if <70%
3. **Historical Trend Table** — 4 rows (most recent runs, oldest to newest)
   - Columns: Run ID (truncated), Relevance %, Dedup %, Calibration %, Timestamp (date only)

**Color Coding**:
- ✅ Green: metric is good (relevance >70%, dedup 100%, calibration >70%)
- ⚠️ Yellow: metric needs attention (dedup <100%, calibration <70%)
- ❌ Red: metric is poor (relevance <50%)

**Example Dashboard Output**:
```
📊 Performance Metrics (Last 4 Runs)

Relevance Rate          Dedup Precision         Source Calibration
60.0%                   100.0%                  76.0%
↑ Human approvals       ✅ No duplicates        ⚠️ Recalibrate sources

Historical Trend
┌─────────────┬───────────┬───────────┬───────────────┬──────────────┐
│ Run ID      │ Relevance │ Dedup     │ Calibration   │ Timestamp    │
├─────────────┼───────────┼───────────┼───────────────┼──────────────┤
│ abc12345... │ 45%       │ 100%      │ 70%           │ 2026-06-08   │
│ def67890... │ 52%       │ 100%      │ 72%           │ 2026-06-09   │
│ ghi24680... │ 58%       │ 95%       │ 74%           │ 2026-06-10   │
│ jkl13579... │ 60%       │ 100%      │ 76%           │ 2026-06-15   │
└─────────────┴───────────┴───────────┴───────────────┴──────────────┘

Trending: Relevance ↑, Dedup stable, Calibration ↑ → System improving!
```

---

## Usage Pattern

### For End Users

1. **Review Newsletter** in Streamlit UI
2. **Approve/Reject Articles** (feedback recorded in user_feedback table)
3. **Human Edits Saved** (source_domain captured for each article)
4. **Newsletter Published** (Publisher sends email)
5. **Evals Computed** (run_evals logs 3 metrics to eval_results)
6. **Dashboard Updated** (metrics panel shows latest scores + historical trend)
7. **Next Week** → Profile is adjusted based on metrics (manual or automatic)

### For Data Scientists / Analysts

**Query evals for a specific run**:
```python
from memory.db import get_db

run_id = "abc123..."
with get_db() as conn:
    cursor = conn.cursor()
    cursor.execute("""
        SELECT metric_name, value, details, timestamp
        FROM eval_results
        WHERE run_id = ?
    """, (run_id,))
    
    for metric_name, value, details_json, timestamp in cursor.fetchall():
        details = json.loads(details_json)
        print(f"{metric_name}: {value:.1%} ({timestamp})")
        print(f"  Details: {details}")
```

**Compare two runs**:
```python
# Get metrics for Run A and Run B
run_a_metrics = run_evals("abc123...")["metrics"]
run_b_metrics = run_evals("def456...")["metrics"]

# Compare improvement
print(f"Relevance improved: {run_a_metrics['relevance_rate']:.1%} → {run_b_metrics['relevance_rate']:.1%}")
```

**Track improvement over time**:
```python
recent_runs = get_recent_eval_runs(limit=52)  # Last year
relevance_trend = [r["metrics"]["relevance_rate"] for r in recent_runs]
print(f"Average relevance: {sum(relevance_trend) / len(relevance_trend):.1%}")
```

---

## Summary

| Aspect | Details |
|--------|---------|
| **Number of Metrics** | 3 (relevance_rate, dedup_precision, source_calibration) |
| **Data Source** | Real SQLite tables (user_feedback, source_scores, newsletters, story_fingerprints) |
| **Return Format** | (float ∈ [0.0, 1.0], details_dict) for each eval |
| **Logging** | All metrics persisted in eval_results table with full auditability |
| **Dashboard** | Streamlit UI shows latest KPIs + trend table for last 4 runs |
| **Use Case** | Track improvement, A/B test profiles, validate agent learning |
| **Cost** | $0 (all queries, no LLM calls) |

---

## Testing

**Verify evals module imports**:
```bash
python3 -c "
from evals.eval_runner import run_evals
from evals.relevance_eval import relevance_rate_eval
from evals.dedup_eval import dedup_precision_eval
from evals.source_eval import source_calibration_eval
print('✅ All eval modules imported')
"
```

**Test with sample data**:
```python
from evals.eval_runner import run_evals

result = run_evals("test-run-123")
print(result["summary"])
# Output:
# ARIA Evaluation Results for test-run-123
# =====================================
# Relevance Rate:        60.0% (3 approved, 2 rejected)
# Dedup Precision:       100.0% (5 unique articles)
# Source Calibration:    76.0% (agent vs human agreement: 5 sources)
```

