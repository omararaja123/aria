# Drafting Skill

**Version**: 1.0  
**Purpose**: Generate intro paragraph for the newsletter (enticing, personal, timely).  
**Model**: Claude Sonnet 4.6  
**Temperature**: 0.7 (creative; intro should feel fresh, not robotic)  
**Max tokens**: 300

---

## System Prompt

```
You are a newsletter editor writing compelling introductions for a weekly AI digest.

Given:
- This week's topics and story counts
- The highlight story (most relevant article)
- The reader's interests and last week's coverage

Write a 2–3 sentence intro paragraph that:
1. Feels personal and warm (as if from a trusted curator)
2. Hints at the week's standout story
3. Mentions 1–2 key topics covered this week
4. Never exceeds 100 words

Tone: Authoritative but conversational. Excited but not hyperbolic.

Example: "This week's AI landscape is shifting fast—from new models to major breakthroughs. But the story that grabbed me was X. We've also covered Y and Z. Dive in below."

Output as JSON:
{
  "intro_text": "...",
  "word_count": 42
}
```

---

## Example Input

```json
{
  "highlight_story": {
    "title": "GPT-4o mini: Smaller, faster, cheaper",
    "relevance_score": 0.95
  },
  "topics_this_week": {
    "Trending": 4,
    "Research": 3,
    "Tools": 2,
    "Industry": 2,
    "Analysis": 4
  },
  "last_week_coverage": ["LLMs", "Vision", "Agents"],
  "interest_profile": ["LLMs (0.95)", "Agents (0.75)", "Multimodal (0.80)"]
}
```

---

## Example Output

```json
{
  "intro_text": "OpenAI just released GPT-4o mini—smaller, faster, and surprisingly capable. It's the headline this week, but there's plenty more: fresh research on vision models, new agent frameworks, and industry announcements reshaping the AI stack. Let's dig in.",
  "word_count": 44
}
```

---

## Key Parameters

- **Temperature**: 0.7 (creative variety; each intro should feel slightly different)
- **Top-p**: 0.95
- **Max tokens**: 300 (enforced: don't ramble)
- **Stop sequences**: None

---

## Estimated Costs

- **Tokens per call**: ~250 input + 80 output = 330 total
- **Cost per run**: ~$0.0005
- **Budget**: Negligible; one call per newsletter

---

## Changelog

### v1.0 (Initial)
- 2–3 sentence intro (100 word max)
- References highlight story + 1–2 key topics
- Personal, conversational tone
- Temperature 0.7 for freshness
- Mentions what's NOT being repeated from last week

---

## Performance Notes

- **Subjectivity**: Intros are qualitative; hard to evaluate objectively
- **User feedback**: Intros with specific story titles score higher than generic ones
- **Consistency**: Temperature 0.7 produces varied-but-coherent intros (no repetition across weeks)
- **Failure modes**:
  - Missing context (no highlight story provided): produces generic intro
  - Too many topics: intro becomes a list, loses narrative
- **Improvement opportunities**:
  - v1.1: Add emoji (optional, reader preference)
  - v1.2: Learn tone from user edits (formal vs. casual)
  - v2.0: Include reading time estimate ("15 min read this week")

---

## Testing Checklist for Implementation

- [ ] Parse JSON output (error handling)
- [ ] Validate intro_text is not empty
- [ ] Enforce max 100 words (count and truncate if needed)
- [ ] Timeout: skip if call > 30 seconds (fallback to generic intro)
- [ ] Fallback intro if call fails: "This week in AI: [topics]. Read on."
- [ ] Cost tracking: add to estimated_cost_usd
- [ ] Retry logic: 1 attempt (low priority; doesn't break sending)

---

## Integration Notes

This skill is called by the Drafter node (not the Ranker/Summarizer pipeline). It's the final creative touch before human review.

The full newsletter structure (Jinja2 template) looks like:
```html
<h1>AI This Week</h1>
<p>{intro_text}</p>
<h2>This Week's Highlight</h2>
{highlight_story_block}
<h2>Trending</h2>
{trending_articles}
...
```

The intro_text generated here fills the opening paragraph.

