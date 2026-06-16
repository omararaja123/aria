"""
ARIA Research Intelligence Dashboard

Premium Streamlit app for reviewing, filtering, and managing AI research articles.
Automatically loads latest research state from database.
Designed with Apple-level clarity, polish, and usability.

Flow:
1. Auto-load latest articles from database on startup
2. Display rich article dashboard with filters and search
3. Show article cards with summaries, sources, and relevance scores
4. Allow human feedback and decision-making
5. Resume LangGraph with user decisions
"""

import streamlit as st
from datetime import datetime
import uuid
import json
import sqlite3
from typing import List, Dict, Any, Optional
import os

try:
    from evals.eval_runner import get_recent_eval_runs
    EVALS_AVAILABLE = True
except ImportError:
    EVALS_AVAILABLE = False

# ============================================================================
# PAGE CONFIG & STYLING (Apple-inspired)
# ============================================================================

st.set_page_config(
    page_title="ARIA — AI Research Intelligence",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Modern, minimal styling
st.markdown("""
<style>
    /* Reset and base styles */
    * { margin: 0; padding: 0; box-sizing: border-box; }

    /* Typography hierarchy */
    h1 { font-size: 32px; font-weight: 600; letter-spacing: -0.5px; margin-bottom: 8px; }
    h2 { font-size: 24px; font-weight: 600; margin-top: 24px; margin-bottom: 16px; }
    h3 { font-size: 18px; font-weight: 600; margin-top: 16px; margin-bottom: 12px; }

    /* Card styling */
    .article-card {
        background: linear-gradient(135deg, #ffffff 0%, #fafafa 100%);
        border: 1px solid #e5e5e5;
        border-radius: 12px;
        padding: 20px;
        margin: 12px 0;
        transition: all 0.3s ease;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
    }
    .article-card:hover {
        border-color: #667eea;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
    }

    /* Highlight article */
    .highlight-article {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border: none;
        color: white;
        border-radius: 12px;
        padding: 24px;
        margin: 20px 0;
    }
    .highlight-article h3 { color: white; }
    .highlight-article p { color: rgba(255, 255, 255, 0.9); }

    /* Badge styles */
    .badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 16px;
        font-size: 12px;
        font-weight: 500;
        margin-right: 8px;
        margin-bottom: 8px;
    }
    .badge-source { background: #f0f0f0; color: #333; }
    .badge-trending { background: #ffeaa7; color: #d63031; }
    .badge-research { background: #74b9ff; color: #0984e3; }
    .badge-tools { background: #81ecec; color: #00b894; }
    .badge-industry { background: #fab1a0; color: #e17055; }
    .badge-analysis { background: #dfe6e9; color: #2d3436; }

    /* Metric card */
    .metric-card {
        background: white;
        border: 1px solid #e5e5e5;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
        margin: 8px 0;
    }

    /* Empty state */
    .empty-state {
        text-align: center;
        padding: 60px 20px;
        color: #666;
    }
    .empty-state-icon { font-size: 64px; margin-bottom: 16px; }

    /* Action buttons */
    .action-row {
        display: flex;
        gap: 12px;
        margin-top: 12px;
        flex-wrap: wrap;
    }

    /* Divider */
    .divider {
        margin: 24px 0;
        border: none;
        border-top: 1px solid #e5e5e5;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# DATA LOADING (Automatic on startup)
# ============================================================================

def load_latest_newsletter() -> Optional[List[Dict[str, Any]]]:
    """
    Load articles from the saved state file (.aria_state.json) created by main.py.
    This is written when the pipeline pauses at human_review.
    Automatically detects when the file has been updated and reloads.
    """
    state_file = ".aria_state.json"
    if not os.path.exists(state_file):
        return None

    try:
        # Check file modification time to detect updates
        file_mtime = os.path.getmtime(state_file)

        # Store last mtime in session state
        if "state_file_mtime" not in st.session_state:
            st.session_state.state_file_mtime = None

        # If file has been modified, reload
        if st.session_state.state_file_mtime != file_mtime:
            st.session_state.state_file_mtime = file_mtime
            # Clear session state for new article review
            st.session_state.reviewed_article_ids = set()
            st.session_state.current_article_index = 0
            st.session_state.human_review_edits = []

        with open(state_file, "r") as f:
            state_data = json.load(f)

        articles = state_data.get("articles", [])
        # Filter to ensure all articles are dicts
        return [a for a in articles if isinstance(a, dict)] if articles else None

    except Exception:
        # If loading fails, return None and fall back to demo
        return None


@st.cache_data
def load_articles_from_state() -> Optional[List[Dict[str, Any]]]:
    """
    Load articles from the most recent LangGraph state or database.
    In a production system, this would load from a persisted state store.
    For now, we return None and rely on the user running the pipeline.
    """
    # In production, you would load from:
    # - LangGraph checkpoint store
    # - State database
    # - Redis cache
    # etc.
    return None


@st.cache_data
def get_demo_articles() -> List[Dict[str, Any]]:
    """Return high-quality demo articles for onboarding."""
    return [
        {
            "id": str(uuid.uuid4()),
            "title": "Claude 3.5 Sonnet: Breaking New Records in Reasoning",
            "source_domain": "anthropic.com",
            "published_date": "2024-06-15",
            "section": "Trending",
            "relevance_score": 0.98,
            "summary_text": "Anthropic released Claude 3.5 with major improvements in mathematical reasoning and code generation. The model achieves new benchmarks on competitive programming and logical reasoning tasks. Available via API and Claude.ai.",
            "why_matters": "Represents significant progress in LLM reasoning capabilities, directly impacting enterprise AI applications.",
            "url": "https://anthropic.com/news/claude-3-5-sonnet",
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Vision Transformers Achieve SOTA on ImageNet",
            "source_domain": "arxiv.org",
            "published_date": "2024-06-14",
            "section": "Research",
            "relevance_score": 0.87,
            "summary_text": "New research on vision transformers shows how to achieve state-of-the-art ImageNet accuracy with 30% fewer parameters. Uses a novel attention mechanism and training strategy.",
            "why_matters": "Efficiency improvements enable deployment on edge devices and reduce computational costs.",
            "url": "https://arxiv.org/abs/2024.xxxxx",
        },
        {
            "id": str(uuid.uuid4()),
            "title": "LangChain 0.2 Release: Major API Overhaul",
            "source_domain": "github.com",
            "published_date": "2024-06-13",
            "section": "Tools & Resources",
            "relevance_score": 0.76,
            "summary_text": "LangChain releases v0.2 with simplified API, better type hints, and improved async support. Migration guide provided.",
            "why_matters": "Cleaner APIs improve development velocity and code maintainability for LLM applications.",
            "url": "https://github.com/langchain-ai/langchain/releases/tag/v0.2.0",
        },
        {
            "id": str(uuid.uuid4()),
            "title": "OpenAI Announces GPT-5 Roadmap",
            "source_domain": "openai.com",
            "published_date": "2024-06-12",
            "section": "Industry News",
            "relevance_score": 0.85,
            "summary_text": "OpenAI published its roadmap for GPT-5 development, focusing on reasoning, multimodality, and real-time interaction.",
            "why_matters": "Signals the direction of model development; impacts enterprise AI strategy.",
            "url": "https://openai.com/blog/gpt-5-roadmap",
        },
        {
            "id": str(uuid.uuid4()),
            "title": "Why Scaling Laws May Be Breaking Down",
            "source_domain": "thegradient.pub",
            "published_date": "2024-06-11",
            "section": "Analysis & Opinion",
            "relevance_score": 0.72,
            "summary_text": "Opinion piece argues that traditional scaling laws may not hold for the next generation of AI.",
            "why_matters": "Challenges conventional wisdom; would reshape how companies plan model development.",
            "url": "https://thegradient.pub/scaling-laws-breaking-down",
        },
    ]


# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

if "articles_data" not in st.session_state:
    st.session_state.articles_data = None

if "search_query" not in st.session_state:
    st.session_state.search_query = ""

if "selected_sections" not in st.session_state:
    st.session_state.selected_sections = ["Trending", "Research", "Tools & Resources", "Industry News", "Analysis & Opinion"]

if "human_review_edits" not in st.session_state:
    st.session_state.human_review_edits = []

if "decision" not in st.session_state:
    st.session_state.decision = None
if "reject_feedback" not in st.session_state:
    st.session_state.reject_feedback = ""
if "show_reject_form" not in st.session_state:
    st.session_state.show_reject_form = False
if "decision_feedback" not in st.session_state:
    st.session_state.decision_feedback = ""
if "show_feedback_form" not in st.session_state:
    st.session_state.show_feedback_form = False
if "reviewed_article_ids" not in st.session_state:
    st.session_state.reviewed_article_ids = set()
if "current_article_index" not in st.session_state:
    st.session_state.current_article_index = 0
if "decision_submitted" not in st.session_state:
    st.session_state.decision_submitted = False
if "decision_submitted_type" not in st.session_state:
    st.session_state.decision_submitted_type = None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_section_badge_class(section: str) -> str:
    """Return CSS class for section badge."""
    mapping = {
        "Trending": "badge-trending",
        "Research": "badge-research",
        "Tools & Resources": "badge-tools",
        "Industry News": "badge-industry",
        "Analysis & Opinion": "badge-analysis",
    }
    return mapping.get(section, "badge-research")


def filter_articles(articles: List[Dict], query: str, sections: List[str]) -> List[Dict]:
    """Filter articles by search query and selected sections."""
    filtered = articles

    if query:
        query_lower = query.lower()
        filtered = [
            a for a in filtered
            if query_lower in a.get("title", "").lower()
            or query_lower in a.get("summary_text", "").lower()
            or query_lower in a.get("source_domain", "").lower()
        ]

    if sections:
        filtered = [a for a in filtered if a.get("section") in sections]

    return filtered


def get_source_contribution(articles: List[Dict]) -> Dict[str, int]:
    """Count articles by source (fetch_source field). Returns dict of {source: count}."""
    contribution = {}
    for article in articles:
        source = article.get("fetch_source", "unknown")
        contribution[source] = contribution.get(source, 0) + 1
    return contribution


def render_article_card(article: Dict[str, Any], show_actions: bool = True):
    """Render a single article card with Apple-level polish."""
    st.markdown('<div class="article-card">', unsafe_allow_html=True)

    # Title
    st.markdown(f"### {article.get('title', 'Untitled')}")

    # Metadata row
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1])

    with col1:
        source = article.get("source_domain", "Unknown")
        st.markdown(f'<span class="badge badge-source">📌 {source}</span>', unsafe_allow_html=True)

    with col2:
        section = article.get("section", "Uncategorized")
        section_class = get_section_badge_class(section)
        st.markdown(f'<span class="badge {section_class}">📂 {section}</span>', unsafe_allow_html=True)

    with col3:
        relevance = article.get("relevance_score", 0.5)
        color = "🟢" if relevance > 0.8 else "🟡" if relevance > 0.6 else "🔴"
        st.markdown(f'{color} {relevance:.0%}')

    with col4:
        date = article.get("published_date", "—")
        st.caption(f"📅 {date}")

    st.markdown("---")

    # Summary
    st.markdown(f"**Summary:**")
    st.markdown(article.get("summary_text", "No summary available"))

    # Why it matters
    if article.get("why_matters"):
        st.markdown(f"*💡 {article.get('why_matters')}*")

    # Feedback box (for individual article comments)
    article_id = article.get("id", "unknown")
    feedback_key = f"feedback_{article_id}"

    if feedback_key not in st.session_state:
        st.session_state[feedback_key] = ""

    if show_actions:
        st.markdown("**💬 Your feedback on this article** *(optional)*")
        feedback = st.text_area(
            "Feedback",
            value=st.session_state[feedback_key],
            max_chars=300,
            placeholder="e.g., Great insights, but missing recent developments... or Too basic for newsletter...",
            label_visibility="collapsed",
            height=80,
            key=f"feedback_input_{article_id}"
        )
        st.session_state[feedback_key] = feedback
        if feedback:
            st.caption(f"**{len(feedback)} / 300** characters")

    # Action buttons
    if show_actions:
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("👍 Approve", key=f"approve_{article.get('id')}", use_container_width=True):
                st.session_state.human_review_edits.append({
                    "article_id": article.get("id"),
                    "action": "approve",
                    "feedback": st.session_state.get(feedback_key, "").strip(),
                    "timestamp": datetime.now().isoformat(),
                })
                st.session_state.reviewed_article_ids.add(article.get("id"))
                st.success("✓ Approved! Next article →")
                st.rerun()

        with col2:
            if st.button("👎 Reject", key=f"reject_{article.get('id')}", use_container_width=True):
                st.session_state.human_review_edits.append({
                    "article_id": article.get("id"),
                    "action": "reject",
                    "feedback": st.session_state.get(feedback_key, "").strip(),
                    "timestamp": datetime.now().isoformat(),
                })
                st.session_state.reviewed_article_ids.add(article.get("id"))
                st.warning("✗ Rejected! Next article →")
                st.rerun()

        with col3:
            if st.button("🔗 Open", key=f"open_{article.get('id')}", use_container_width=True):
                st.link_button("Open Article", article.get('url'))

    st.markdown("</div>", unsafe_allow_html=True)


def render_empty_state():
    """Render empty state with helpful guidance."""
    st.markdown("""
    <div class="empty-state">
        <div class="empty-state-icon">🔍</div>
        <h2>No Articles Loaded</h2>
        <p style="font-size: 16px; color: #666; margin-bottom: 24px;">
            Start by running the ARIA research pipeline to fetch and analyze articles.
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.info("""
    **How to get started:**

    1. Open a terminal in the ARIA directory
    2. Run: `python3 main.py`
    3. Wait for the pipeline to complete (~90 seconds)
    4. Return here to review your articles
    """)


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # Show completion screen if decision was submitted
    if st.session_state.decision_submitted:
        st.markdown("# 🎉 Decision Submitted")

        decision_type = st.session_state.decision_submitted_type
        if decision_type == "approve":
            st.success("✅ Newsletter approved!")
            st.markdown("---")
            st.markdown("### 📧 Publishing Your Newsletter")
            st.markdown("Your articles are being sent now. This window will close automatically.")
            st.info("The pipeline is finalizing your newsletter and updating memory tables.")
            st.balloons()
        elif decision_type == "re_rank":
            st.info("🔄 Re-ranking Articles")
            st.markdown("---")
            st.markdown("### ⏳ Processing Your Feedback")
            st.markdown("New rankings are being generated based on your feedback.")
            st.markdown("The updated articles will appear in a moment...")
        else:  # reject
            st.warning("↻ Restarting Pipeline")
            st.markdown("---")
            st.markdown("### ⏳ Fetching Fresh Articles")
            st.markdown("Fresh research is being fetched from all sources.")
            st.markdown("A new review interface will appear shortly...")

        # Don't show anything else - just the completion screen
        return

    # Auto-refresh when state file is updated (for re-rank loops)
    state_file = ".aria_state.json"
    if "state_file_mtime" not in st.session_state:
        st.session_state.state_file_mtime = None

    if os.path.exists(state_file):
        current_mtime = os.path.getmtime(state_file)
        if st.session_state.state_file_mtime != current_mtime and st.session_state.state_file_mtime is not None:
            # File has been updated - refresh to show new articles
            st.session_state.reviewed_article_ids = set()
            st.session_state.current_article_index = 0
            st.session_state.human_review_edits = []
            # Clear decision submitted flag for next round
            st.session_state.decision_submitted = False
            st.session_state.decision_submitted_type = None

    # Header
    st.markdown("# 🧠 ARIA — AI Research Intelligence")
    st.markdown("*Intelligent curation and review of research articles*")
    st.markdown("---")

    # Sidebar for filters and controls
    with st.sidebar:
        st.markdown("## 🔧 Controls")

        # Refresh data
        if st.button("🔄 Reload Articles", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        st.markdown("## 🎯 Filters")

        # Search
        search_query = st.text_input("🔍 Search articles", placeholder="e.g., Claude, Vision, LLM...")

        # Section filter
        all_sections = ["Trending", "Research", "Tools & Resources", "Industry News", "Analysis & Opinion"]
        selected_sections = st.multiselect(
            "📂 Sections",
            all_sections,
            default=all_sections,
            label_visibility="collapsed"
        )

        # Relevance filter
        min_relevance = st.slider("⭐ Minimum Relevance", 0.0, 1.0, 0.0, 0.1)

        st.markdown("---")
        st.markdown("## 📊 Stats")

        if st.session_state.articles_data:
            articles = st.session_state.articles_data
            st.metric("Total Articles", len(articles))
            st.metric("Sources", len(set(a.get("source_domain") for a in articles)))
            relevance_avg = sum(a.get("relevance_score", 0.5) for a in articles) / len(articles) if articles else 0
            st.metric("Avg Relevance", f"{relevance_avg:.0%}")

        st.markdown("---")
        st.markdown("## 💾 Actions")

        if st.button("📥 Export Articles", use_container_width=True):
            st.info("Export functionality coming soon")

        if st.button("📧 Email Summary", use_container_width=True):
            st.info("Email functionality coming soon")

    # Main content
    # Try to load real data, fall back to demo
    articles = load_latest_newsletter()

    if not articles:
        articles = load_articles_from_state()

    if articles is None:
        # Show empty state with onboarding
        render_empty_state()

        st.markdown("---")
        st.markdown("## 📚 Demo Articles")
        st.markdown("*Want to see how the dashboard works? Here are sample articles:*")

        demo_articles = get_demo_articles()
        st.session_state.articles_data = demo_articles

        for article in demo_articles[:3]:
            render_article_card(article, show_actions=False)

        st.info("👆 Run the pipeline above to load real articles and enable full review features.")

    else:
        # We have articles - show full dashboard
        st.session_state.articles_data = articles

        # Info about articles shown
        st.info("📊 **Showing final selected articles** — These are the top-ranked articles after deduplication, ranking by relevance, and summarization. This is what will go in your newsletter.")

        # Dashboard metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Articles Selected", len(articles))

        with col2:
            sources = len(set(a.get("source_domain") for a in articles))
            st.metric("Unique Sources", sources)

        with col3:
            relevance_avg = sum(a.get("relevance_score", 0.5) for a in articles) / len(articles)
            st.metric("Avg Relevance", f"{relevance_avg:.0%}")

        with col4:
            st.metric("Last Updated", datetime.now().strftime("%I:%M %p"))

        # Per-source contribution breakdown
        with st.expander("📊 Articles by Source", expanded=False):
            source_contribution = get_source_contribution(articles)
            if source_contribution:
                # Display as a bar chart
                source_names = list(source_contribution.keys())
                source_counts = list(source_contribution.values())

                # Create a nicer display
                st.bar_chart(dict(sorted(source_contribution.items(), key=lambda x: x[1], reverse=True)))

                # Also show as text
                st.markdown("**Source Breakdown:**")
                for source, count in sorted(source_contribution.items(), key=lambda x: x[1], reverse=True):
                    pct = (count / len(articles)) * 100
                    st.caption(f"• {source.replace('_', ' ').title()}: {count} articles ({pct:.0f}%)")
            else:
                st.caption("No source data available")

        st.markdown("---")

        # Filter and search
        filtered = filter_articles(
            articles,
            search_query,
            selected_sections if selected_sections else all_sections
        )

        # Filter out already-reviewed articles
        unreviewed = [a for a in filtered if a.get("id") not in st.session_state.reviewed_article_ids]
        total_articles = len(filtered)
        reviewed_count = len([a for a in filtered if a.get("id") in st.session_state.reviewed_article_ids])

        # Progress indicator
        progress_pct = (reviewed_count / total_articles * 100) if total_articles > 0 else 0
        st.progress(reviewed_count / total_articles if total_articles > 0 else 1.0)
        st.markdown(f"**Progress: {reviewed_count} / {total_articles} articles reviewed**")

        if search_query or selected_sections != all_sections:
            st.markdown(f"*({len(unreviewed)} remaining to review)*")

        st.markdown("---")

        # Display articles
        if not unreviewed:
            if reviewed_count == total_articles:
                st.success("🎉 **All articles reviewed!**")
                st.markdown("Your feedback has been collected. Now decide what to do with the newsletter below.")
            else:
                st.info("No articles match your filters. Try adjusting your search or selections.")
        else:
            # Find and display highlight
            highlight = next((a for a in unreviewed if a.get("is_highlight")), unreviewed[0] if unreviewed else None)

            if highlight:
                st.markdown("### ⭐ Highlighted Article")
                st.markdown(f"*({len(unreviewed)} unreviewed articles)*")
                render_article_card(highlight, show_actions=True)
                st.markdown("---")

                # Show next few articles for context
                remaining_after_highlight = [a for a in unreviewed if a.get("id") != highlight.get("id")]
                if remaining_after_highlight:
                    st.markdown(f"### 📄 Next Articles to Review")
                    for article in remaining_after_highlight[:2]:  # Show next 2 articles
                        with st.expander(f"💭 {article.get('title', 'Untitled')[:60]}... (Preview)"):
                            st.markdown(f"**Source:** {article.get('source_domain')}")
                            st.markdown(f"**Relevance:** {article.get('relevance_score', 0.5):.0%}")
                            st.caption(article.get("summary_text", "No summary"))
            else:
                # No highlight, group by section
                sections_to_show = [s for s in all_sections if s in selected_sections]

                for section in sections_to_show:
                    section_articles = [a for a in unreviewed if a.get("section") == section]

                    if not section_articles:
                        continue

                    st.markdown(f"### 📂 {section} ({len(section_articles)})")

                    for article in section_articles[:1]:  # Show one article at a time per section
                        render_article_card(article, show_actions=True)

                    if len(section_articles) > 1:
                        with st.expander(f"📄 {len(section_articles) - 1} more in {section}"):
                            for article in section_articles[1:]:
                                st.markdown(f"- **{article.get('title', 'Untitled')[:60]}...** ({article.get('relevance_score', 0.5):.0%})")

        st.markdown("---")

        # Decision buttons (show anytime, but highlight when all reviewed)
        decision_header = "## 🎯 Your Decision" if reviewed_count < total_articles else "## ✨ Ready to Publish?"
        st.markdown(decision_header)

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("✅ Approve All", use_container_width=True, type="primary"):
                st.session_state.show_feedback_form = True
                st.session_state.decision = "approve"

        with col2:
            if st.button("🔄 Re-rank", use_container_width=True):
                st.session_state.show_feedback_form = True
                st.session_state.decision = "re_rank"

        with col3:
            if st.button("❌ Reject", use_container_width=True, type="secondary"):
                st.session_state.show_feedback_form = True
                st.session_state.decision = "reject"

        # Feedback form for all decisions
        if st.session_state.show_feedback_form:
            decision_type = st.session_state.decision
            if decision_type == "approve":
                st.markdown("### Approve Newsletter")
                st.markdown("*(Optional: Tell the model what you liked about this selection)*")
                prompt = "What did you like about these articles?"
            elif decision_type == "re_rank":
                st.markdown("### Re-rank Articles")
                st.markdown("*(Optional: Explain what you'd like changed)*")
                prompt = "What would you like improved in the ranking?"
            else:  # reject
                st.markdown("### Reject & Restart")
                st.markdown("*(Optional: Explain why, so the model can learn)*")
                prompt = "Why are you rejecting? What should be different?"

            feedback = st.text_area(
                "Your feedback",
                value=st.session_state.decision_feedback,
                max_chars=500,
                placeholder=prompt,
                label_visibility="collapsed",
                height=120,
                key="decision_feedback_input"
            )
            st.session_state.decision_feedback = feedback

            char_count = len(feedback)
            st.caption(f"**{char_count} / 500** characters")

            col_submit, col_cancel = st.columns(2)

            with col_submit:
                button_labels = {
                    "approve": "✓ Approve & Send",
                    "re_rank": "🔄 Re-rank with Feedback",
                    "reject": "✓ Submit & Reject"
                }
                button_label = button_labels.get(decision_type, "Submit")

                if st.button(button_label, use_container_width=True, type="primary", key="submit_decision"):
                    # Write decision to file for main.py to detect
                    decision_data = {
                        "review_approved": decision_type == "approve",
                        "review_rejected": decision_type == "reject",
                        "review_re_rank": decision_type == "re_rank",
                        "human_review_edits": st.session_state.get("human_review_edits", []),
                        "interest_profile_edits": st.session_state.get("interest_profile_edits", {}),
                        "decision_feedback": feedback.strip(),
                    }
                    with open(".aria_review_decision.json", "w") as f:
                        json.dump(decision_data, f)
                    st.session_state.show_feedback_form = False
                    st.session_state.decision_submitted = True
                    st.session_state.decision_submitted_type = decision_type
                    st.rerun()

            with col_cancel:
                if st.button("✕ Cancel", use_container_width=True, key="cancel_decision"):
                    st.session_state.show_feedback_form = False
                    st.session_state.decision = None

        # Show edits if any
        if st.session_state.human_review_edits:
            with st.expander("📋 Your Edits"):
                st.json(st.session_state.human_review_edits)


if __name__ == "__main__":
    main()
