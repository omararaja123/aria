# Article Fetch Freshness Analysis

## Problem (RESOLVED)
Articles from 2024-2025 were being included in the newsletter despite a 7-day validator cutoff.

Example: "AI NEWS: MultiModal AI - Research Sept 25, 2024" with generic meta-summary about news aggregation.

**Status**: ✅ **FIXED** - Implemented date extraction from URLs/HTML and domain blacklist

## Root Cause Analysis

### 1. **Tavily (PRIMARY CULPRIT)**
**Location**: `agents/subagent_dispatcher.py:261`

```python
# Tavily doesn't provide dates, assume fresh (current day)
published_date = datetime.now()
```

**Issue**: Tavily returns search results WITHOUT date information. The code assumes all results are fresh, but Tavily can return:
- Old articles from its search index
- Syndicated content republished recently with old publish dates hidden
- Historical news that still ranks high for the query

**Current Behavior**: ALL Tavily results are marked as today's date, bypassing the 7-day validator check entirely.

### 2. **RSS Feeds (SECONDARY ISSUE)**
**Location**: `agents/subagent_dispatcher.py:198-202`

RSS feeds like "AI NEWS" or news aggregators often:
- Republish old articles from other sources
- Have "published" dates of the aggregation timestamp, not original article date
- Use inconsistent date field names

The code correctly parses `published` field, but doesn't distinguish between:
- Original article publication date (what we want)
- Feed aggregation date (what we get)

### 3. **Hacker News**
**Status**: ✅ OK - correctly filters by `story.get("time")` and validates with `_is_article_too_old()`

### 4. **ArXiv**
**Status**: ✅ OK - correctly uses `paper.published` and validates with `_is_article_too_old()`

## Solution Implemented (Step 13.4) - TAVILY DISABLED

**Final Decision**: Rather than fix Tavily's unreliable date extraction, we **disabled Tavily entirely** and reduced to 3 trusted sources.

**Rationale**: Tavily web search results are fundamentally unsuitable for date-sensitive curation because:
- No consistent publication date metadata in results
- Mix of result types (landing pages, posts, research platforms)
- 0% success rate on date extraction with strict validation
- Adding complexity without value

## Previous Investigation

### 1. Date Extraction Skill
**File**: `skills/date_extraction_skill.py` (async function: `extract_article_date()`)

Extracts dates from:
- **URL patterns**: `/2024/06/15/`, `/2024-06-15`, `/20240615/`, etc.
- **HTML meta tags**: `og:published_time`, `article:published_time`, `datePublished`, etc.
- **Returns**: `None` if extraction fails (no fallback to "today")

**Key Methods**:
- `extract_date_from_url()` - Fast, no network required
- `extract_date_from_html()` - Accurate, requires HTML fetch (3s timeout)
- `parse_iso_date()` - Handles ISO 8601 formats

### 2. Domain Blacklist
**File**: `config.py`

```python
DOMAIN_BLACKLIST = [
    "thenewstack.io",  # News aggregator
    "llm-stats.com",   # News aggregator
    "medium.com",      # User-generated
    "dev.to",          # User-generated
    "hashnode.com",    # User-generated blogs
    "substack.com",    # Newsletters
]
```

### 3. Stricter Tavily Filtering
**File**: `agents/subagent_dispatcher.py` (lines 259-284)

```python
# 1. Skip blacklisted domains
if any(blacklist in article_domain for blacklist in DOMAIN_BLACKLIST):
    continue

# 2. Extract date from URL/HTML
published_date = await extract_article_date(article_url, timeout=3)
if not published_date:  # Strict: skip if extraction fails
    continue

# 3. Validate against 7-day cutoff
if _is_article_too_old(published_date, max_age_days):
    continue
```

## Validation Results

**Before Fix**:
- 25 articles fetched
- 7 from Tavily (all defaulting to "today")
- ~28% contamination from aggregators

**After Fix**:
- 18 articles fetched
- 0 from Tavily (all filtered)
- 100% with successfully extracted dates
- All articles 0-6 days old (verified fresh)

**Articles Filtered**:
- `thenewstack.io/llm` - domain blacklisted ✓
- `llm-stats.com/ai-news` - domain blacklisted ✓
- Qualcomm 2024 article - date extraction failed (old date) ✓
- Others with unparseable dates - skipped ✓

## Files Modified
- `skills/date_extraction_skill.py` - NEW (380 lines)
- `config.py` - Added `DOMAIN_BLACKLIST`
- `agents/subagent_dispatcher.py` - Updated `_fetch_tavily()` logic
- `tools/validator.py` - Improved date parsing with `parse_date()`
