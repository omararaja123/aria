# Credibility Skill

**Version**: 1.0  
**Purpose**: Score source credibility 0–1 for a domain (used rarely, mostly cached).  
**Model**: Claude Sonnet 4.6  
**Temperature**: 0.1 (very deterministic; credibility is binary-ish)  
**Max tokens**: 200

---

## System Prompt

```
You are an expert evaluating the credibility of AI news and research sources.

For each domain, assess its credibility based on:
- Authorship: Are articles by named experts with verified credentials?
- Fact-checking: Does the publication correct errors? Do readers trust it?
- Bias: Is coverage balanced or heavily promotional?
- Track record: Does it break important stories or mostly echo others?
- Update frequency: Is it current and actively maintained?

Score 0–1:
- 0.9–1.0: Highly credible (peer-reviewed journals, major publications like Nature, ICML)
- 0.7–0.8: Credible (technical blogs by known researchers, reputable tech news)
- 0.5–0.6: Moderate (most tech blogs, medium-sized publications)
- 0.3–0.4: Low credibility (promotional content, unverified claims, outdated info)
- 0.0–0.2: Very low (spam, misinformation, abandoned projects)

Output as JSON:
{
  "domain": "arxiv.org",
  "credibility_score": 0.95,
  "signals": [
    "Peer-reviewed research papers only",
    "Hosted by Cornell University",
    "Actively maintained for 30+ years"
  ],
  "confidence": 0.98
}
```

---

## Example Input

```json
{
  "domain": "thegradient.pub",
  "context": {
    "domain_age_years": 5,
    "article_count": 87,
    "topics": ["AI safety", "ML theory", "ethics"]
  }
}
```

---

## Example Output

```json
{
  "domain": "thegradient.pub",
  "credibility_score": 0.82,
  "signals": [
    "Founded by AI researchers (Nika Haghtalab, etc.)",
    "Published in reputable venues and respected by ML community",
    "Consistent, in-depth technical coverage",
    "No apparent promotional bias"
  ],
  "confidence": 0.85
}
```

---

## Key Parameters

- **Temperature**: 0.1 (extremely deterministic; credibility should be stable)
- **Top-p**: 0.95
- **Max tokens**: 200
- **Stop sequences**: None

---

## Estimated Costs

- **Tokens per call**: ~200 input + 80 output = 280 total
- **Cost per domain**: ~$0.0004
- **Typical usage**: Called 5–10 times per run (for new domains)
- **Budget**: Negligible; cached after first call

---

## Caching Strategy

**Critical**: This skill should be cached. Once a domain is scored, reuse that score unless 30 days old.

```
Memory table: source_scores (domain TEXT PRIMARY KEY, credibility_score REAL, last_updated DATETIME)

On call:
1. Check memory for domain
2. If cached and < 30 days old: return cached score
3. If not cached or > 30 days: call skill, update memory
4. Return score
```

This reduces API calls dramatically (1 call per new domain per month, not per article).

---

## Changelog

### v1.0 (Initial)
- Scoring rubric (0.9–1.0, 0.7–0.8, etc.)
- 5 evaluation criteria (authorship, fact-checking, bias, track record, frequency)
- JSON output with signals (list of reasons)
- Temperature 0.1 for stability
- Designed for monthly re-evaluation (not per-article)

---

## Performance Notes

- **Accuracy**: Not formally tested; subjective domain (credibility is somewhat opinion-based)
- **Consistency**: Temperature 0.1 produces identical/near-identical scores
- **Known blindspots**:
  - New domains (< 1 year old): harder to assess, confidence lower
  - Niche topics: may not have expertise (e.g., neuroscience LLM applications)
- **Improvement opportunities**:
  - v1.1: Add Alexa rank as signal (optional)
  - v2.0: Learn from human feedback (domains user frequently removes vs. keeps)

---

## Testing Checklist for Implementation

- [ ] Parse JSON output (error handling)
- [ ] Validate credibility_score in [0.0, 1.0]
- [ ] Implement caching in source_memory table
- [ ] Cache expiry: 30 days
- [ ] Fallback: if score fails, use 0.5 (unknown credibility)
- [ ] Timeout: skip if call > 20 seconds
- [ ] Monitor: track how often cached vs. fresh calls
- [ ] Retry logic: 2 attempts (lower than ranker/summarizer since less critical)

