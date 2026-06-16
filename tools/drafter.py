"""
ARIA Drafter Node

Assembles a full HTML newsletter from summarized articles.
Uses Claude Sonnet 4.6 to generate an engaging intro paragraph,
then renders the full newsletter with Jinja2 templating.

Features:
- Email-safe HTML with inline CSS
- Featured highlight article at the top
- 5 newsletter sections with articles grouped by relevance
- Max 4 articles per section
- Responsive design for mobile and desktop
"""

import logging
from datetime import datetime
from typing import Any, Dict, List

from jinja2 import Template

from state import ARIAState, Article
from config import (
    NEWSLETTER_SECTIONS,
    ENABLE_LLM_DRAFTING,
)
from skills.drafting_skill import drafting_skill

logger = logging.getLogger(__name__)


def is_summary_valid(summary: str) -> bool:
    """
    Check if a summary is valid (not an error message, incomplete, or meta-description).
    Rejects summaries that indicate content extraction failed or are just platform descriptions.
    """
    if not summary or not isinstance(summary, str):
        return False

    summary_lower = summary.lower().strip()

    # Error patterns that indicate failed extraction
    error_patterns = [
        "unable to provide summary",
        "unable to extract",
        "no content",
        "content is incomplete",
        "navigation and cookie",
        "article body is missing",
        "insufficient content",
        "cannot be summarized",
        "could not be processed",
        "access denied",
        "paywall",
    ]

    for pattern in error_patterns:
        if pattern in summary_lower:
            return False

    # Meta-description patterns (describes the platform/source, not the article)
    meta_patterns = [
        "news aggregation platform",
        "tracks daily updates",
        "covers open source",
        "curated coverage",
        "provides curated",
        "platform provides",
        "aggregation platform",
        "platform tracks",
        "service provides",
        "website provides",
        "this is a",
        "this platform",
        "this service",
        "this website",
    ]

    # Check if summary is meta-description (talks about the platform, not content)
    meta_count = sum(1 for pattern in meta_patterns if pattern in summary_lower)
    if meta_count >= 2 or (len(summary) < 100 and meta_count >= 1):
        # Meta-description detected - likely describes source rather than article
        return False

    # Summary should have minimum length
    if len(summary) < 30:
        return False

    return True


def drafter_node(state: ARIAState) -> ARIAState:
    """
    Drafter: Assemble full HTML newsletter.

    Error handling: Drafting skill failures use static template.
    HTML rendering always succeeds (Jinja2 is safe).
    """

    try:
        logger.info("Drafter starting")

        articles = state.get("articles", [])
        interest_profile = state.get("interest_profile", {})
        run_timestamp = state.get("run_timestamp", datetime.now())
        llm_call_count = state.get("llm_call_count", 0)
        estimated_cost_usd = state.get("estimated_cost_usd", 0.0)
        fetch_errors = state.get("fetch_errors", [])

        # Filter to final articles (valid + not removed + good summaries)
        final_articles = []
        rejected_poor_summaries = []
        for a in articles:
            if a.get("validation_status") == "valid" and not a.get("ranking_removed", False):
                # Check summary quality
                summary = a.get("summary_text", "")
                if is_summary_valid(summary):
                    final_articles.append(a)
                else:
                    rejected_poor_summaries.append({
                        "title": a.get("title", "Unknown"),
                        "reason": "Poor or incomplete summary",
                        "summary_preview": summary[:100] if summary else "No summary"
                    })

        if rejected_poor_summaries:
            logger.info(f"Drafter: rejected {len(rejected_poor_summaries)} articles with poor summaries")
            for rejected in rejected_poor_summaries:
                logger.debug(f"  - {rejected['title']}: {rejected['summary_preview']}")

        logger.info(f"Drafter: assembling {len(final_articles)} articles")

        if not final_articles:
            logger.warning("Drafter: no final articles; creating empty newsletter")

        # Identify highlight article
        highlight_article = None
        if final_articles:
            highlight_article = max(
                final_articles,
                key=lambda a: a.get("relevance_score", 0.0),
                default=None,
            )

        # Group articles by section
        articles_by_section = {section: [] for section in NEWSLETTER_SECTIONS}
        for article in final_articles:
            try:
                section = article.get("section", "Trending")
                if section not in articles_by_section:
                    articles_by_section[section] = []
                # Limit to 4 per section
                if len(articles_by_section[section]) < 4:
                    articles_by_section[section].append(article)
            except Exception as section_error:
                logger.warning(f"Error grouping article: {section_error}; skipping")

        # Generate intro paragraph
        topic_summary = {section: len(articles_by_section[section]) for section in NEWSLETTER_SECTIONS}

        intro_text = "This week's newsletter features the latest breakthroughs in AI research."
        intro_cost = 0.0

        if ENABLE_LLM_DRAFTING:
            try:
                logger.info("Drafting intro with Claude Sonnet")
                draft_result = drafting_skill(topic_summary, highlight_article, interest_profile)
                if draft_result.get("success"):
                    intro_text = draft_result.get("intro_text", intro_text)
                    intro_cost = draft_result.get("estimated_cost_usd", 0.0)
                    llm_call_count += 1
                    estimated_cost_usd += intro_cost
                else:
                    logger.warning(f"Drafting skill failed: {draft_result.get('error')}; using default intro")
            except Exception as draft_error:
                logger.warning(f"Drafting error: {draft_error}; using default intro")
                fetch_errors.append({
                    "node": "drafter",
                    "error": str(draft_error),
                })

        # Render HTML template
        try:
            html_content = _render_newsletter_html(
                intro_text=intro_text,
                highlight_article=highlight_article,
                articles_by_section=articles_by_section,
                run_timestamp=run_timestamp,
            )
        except Exception as html_error:
            logger.error(f"HTML rendering error: {html_error}; using minimal HTML")
            html_content = f"""<html><body>
<h1>AI Newsletter</h1>
<p>{intro_text}</p>
<p>{len(final_articles)} articles included.</p>
</body></html>"""

        # Build metadata
        newsletter_metadata = {
            "title": "Weekly AI Research Newsletter",
            "date": run_timestamp.strftime("%Y-%m-%d"),
            "highlight_story_id": highlight_article.get("id") if highlight_article else None,
            "highlight_story_title": highlight_article.get("title") if highlight_article else "N/A",
            "section_breakdown": topic_summary,
            "article_count": len(final_articles),
            "estimated_cost_total": estimated_cost_usd,
        }

        logger.info(
            f"Drafter: newsletter assembled ({len(final_articles)} articles, "
            f"{len(html_content)} chars HTML, ${estimated_cost_usd:.3f})"
        )

        # Update state
        state["draft_newsletter"] = html_content
        state["newsletter_metadata"] = newsletter_metadata
        state["llm_call_count"] = llm_call_count
        state["estimated_cost_usd"] = estimated_cost_usd
        state["fetch_errors"] = fetch_errors

        return state

    except Exception as e:
        logger.error(f"Drafter node failed: {e}")
        state.setdefault("fetch_errors", []).append({
            "node": "drafter",
            "error": str(e),
        })
        # Create minimal fallback newsletter
        state["draft_newsletter"] = "<html><body><h1>Newsletter Generation Failed</h1></body></html>"
        return state


def _render_newsletter_html(
    intro_text: str,
    highlight_article: Dict[str, Any],
    articles_by_section: Dict[str, List[Article]],
    run_timestamp: datetime,
) -> str:
    """
    Render the newsletter HTML using Jinja2 template.
    Inline CSS for email client compatibility.
    """

    template_str = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title }}</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 8px; text-align: center; margin-bottom: 30px; }
        h1 { margin: 0; font-size: 28px; font-weight: bold; }
        .date { font-size: 14px; opacity: 0.9; margin-top: 5px; }
        .intro { font-size: 16px; line-height: 1.7; margin-bottom: 30px; padding: 20px; background: #f8f9fa; border-left: 4px solid #667eea; }
        .highlight { background: #fff9e6; border: 2px solid #ffd700; border-radius: 8px; padding: 20px; margin-bottom: 30px; }
        .highlight h2 { margin: 0 0 10px 0; color: #667eea; font-size: 18px; }
        .highlight .source { color: #666; font-size: 13px; }
        .highlight .summary { font-size: 15px; margin: 15px 0; line-height: 1.6; }
        .highlight .why-matters { font-style: italic; color: #555; margin-top: 10px; padding-top: 10px; border-top: 1px solid #ddd; }
        .highlight a { color: #667eea; text-decoration: none; font-weight: bold; }
        .section { margin-bottom: 30px; }
        .section h3 { margin: 0 0 15px 0; color: #667eea; font-size: 18px; border-bottom: 2px solid #667eea; padding-bottom: 10px; }
        .article { margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 4px; }
        .article h4 { margin: 0 0 8px 0; font-size: 16px; color: #333; }
        .article .source { font-size: 12px; color: #999; }
        .article .summary { font-size: 14px; margin: 10px 0; line-height: 1.5; }
        .article .why-matters { font-style: italic; color: #666; font-size: 13px; margin-top: 8px; }
        .article a { color: #667eea; text-decoration: none; }
        footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #999; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{{ title }}</h1>
            <div class="date">{{ date }}</div>
        </header>

        <div class="intro">{{ intro_text }}</div>

        {% if highlight_article %}
        <div class="highlight">
            <h2>⭐ This Week's Highlight</h2>
            <h4>{{ highlight_article.title }}</h4>
            <div class="source">from {{ highlight_article.source_domain }}</div>
            <div class="summary">{{ highlight_article.summary_text }}</div>
            <div class="why-matters">{{ highlight_article.why_matters }}</div>
            <p><a href="{{ highlight_article.url }}" target="_blank">Read full article →</a></p>
        </div>
        {% endif %}

        {% for section_name in section_order %}
            {% set articles = articles_by_section[section_name] %}
            {% if articles %}
            <div class="section">
                <h3>{{ section_name }}</h3>
                {% for article in articles %}
                <div class="article">
                    <h4>{{ article.title }}</h4>
                    <div class="source">{{ article.source_domain }}</div>
                    <div class="summary">{{ article.summary_text }}</div>
                    <div class="why-matters">{{ article.why_matters }}</div>
                    <p><a href="{{ article.url }}" target="_blank">Read full article →</a></p>
                </div>
                {% endfor %}
            </div>
            {% endif %}
        {% endfor %}

        <footer>
            <p>Weekly AI Research Newsletter • Curated for you</p>
            <p><a href="#" style="color: #667eea; text-decoration: none;">Archive</a> | <a href="#" style="color: #667eea; text-decoration: none;">Unsubscribe</a></p>
        </footer>
    </div>
</body>
</html>"""

    template = Template(template_str)

    html = template.render(
        title="Weekly AI Research Newsletter",
        date=run_timestamp.strftime("%B %d, %Y"),
        intro_text=intro_text,
        highlight_article=highlight_article,
        articles_by_section=articles_by_section,
        section_order=NEWSLETTER_SECTIONS,
    )

    return html
