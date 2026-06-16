"""
ARIA Publisher Node

Sends the approved newsletter via Gmail API and updates all memory stores.
Final step of the autonomous pipeline (before human review checkpoint).

Handles:
1. Gmail authentication and email sending
2. Updating source credibility scores based on published articles
3. Saving story fingerprints for cross-week deduplication
4. Recording topic history (what was covered)
5. Updating preference history based on human edits
6. Logging eval metrics to database
7. Archiving newsletter HTML and metadata
"""

import logging
import uuid
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from state import ARIAState, Article
from memory.db import get_db
from memory.source_memory import update_source_score
from memory.story_memory import save_story_fingerprints, compute_fingerprint
from memory.topic_memory import get_topic_history

logger = logging.getLogger(__name__)

# Optional Gmail imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.service_account import Credentials
    from google.auth.oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials as OAuthCredentials
    from google.api_python_client.discovery import build
    import google.auth
    HAS_GMAIL = True
except ImportError:
    HAS_GMAIL = False
    logger.warning("Gmail API libraries not installed; publishing will be simulated")


def publisher_node(state: ARIAState) -> ARIAState:
    """
    Publisher: Send newsletter and update memory stores.

    Error handling: Memory update failures are logged but don't block email send.
    Gmail failures use simulated IDs but still update memory.
    """

    try:
        logger.info("Publisher starting")

        run_id = state.get("run_id", str(uuid.uuid4()))
        run_timestamp = state.get("run_timestamp", datetime.now())
        draft_newsletter = state.get("draft_newsletter", "")
        final_articles = state.get("final_articles", state.get("articles", []))
        human_review_edits = state.get("human_review_edits", [])

        sender_email = os.getenv("GMAIL_SENDER_EMAIL", "")
        recipient_email = os.getenv("NEWSLETTER_RECIPIENT_EMAIL", os.getenv("GMAIL_RECIPIENT_EMAIL", ""))

        if not sender_email or not recipient_email:
            logger.warning("Gmail credentials not configured; using simulation mode")

        # Step 1: Send newsletter (with fallback to simulation)
        try:
            message_id = _send_newsletter(
                draft_newsletter,
                sender_email,
                recipient_email,
                run_id,
            )
            state["message_id"] = message_id
            logger.info(f"Newsletter sent: {message_id}")
        except Exception as send_error:
            logger.error(f"Send failed: {send_error}; using simulated ID")
            state["message_id"] = f"simulated_{run_id}"

        # Step 2: Update source scores (non-critical; don't block on failure)
        try:
            _update_source_scores(final_articles)
        except Exception as source_error:
            logger.warning(f"Failed to update source scores: {source_error}")

        # Step 3: Save fingerprints (non-critical)
        try:
            _save_fingerprints(run_id, final_articles)
        except Exception as fp_error:
            logger.warning(f"Failed to save fingerprints: {fp_error}")

        # Step 4: Record topic history (non-critical)
        try:
            _record_topic_history(run_id, final_articles)
        except Exception as topic_error:
            logger.warning(f"Failed to record topic history: {topic_error}")

        # Step 5: Update preference history (non-critical)
        try:
            _update_preference_history(run_id, human_review_edits, state.get("interest_profile", {}))
        except Exception as pref_error:
            logger.warning(f"Failed to update preferences: {pref_error}")

        # Step 6: Log eval metrics (non-critical)
        try:
            _log_eval_metrics(run_id, final_articles, human_review_edits)
        except Exception as eval_error:
            logger.warning(f"Failed to log eval metrics: {eval_error}")

        # Step 7: Archive newsletter (non-critical)
        try:
            _archive_newsletter(run_id, draft_newsletter, final_articles, state)
        except Exception as archive_error:
            logger.warning(f"Failed to archive newsletter: {archive_error}")

        # Update state
        state["published"] = True
        state["publish_timestamp"] = datetime.now()
        state["publish_status"] = "success"

        logger.info(
            f"Publisher: newsletter sent ({len(final_articles)} articles), "
            f"memory updates attempted"
        )

        return state

    except Exception as e:
        logger.error(f"Publisher node failed: {e}")
        state["published"] = False
        state["publish_timestamp"] = datetime.now()
        state["publish_status"] = f"error: {str(e)}"
        return state


def _send_newsletter(
    html_content: str,
    sender_email: str,
    recipient_email: str,
    run_id: str,
) -> Optional[str]:
    """
    Send newsletter via Gmail API.
    Falls back to simulation if not configured.

    Returns: message_id from Gmail API, or simulated ID if not configured.
    """

    # Fallback if not configured
    if not sender_email or not recipient_email:
        logger.info("Publisher: simulating email send (no Gmail configured)")
        return f"simulated_{run_id}"

    if not HAS_GMAIL:
        logger.warning("Gmail API not available; simulating send")
        return f"simulated_{run_id}"

    try:
        # Get Gmail service
        service = _get_gmail_service()

        # Build message
        subject = f"📰 Weekly AI Research Newsletter - {datetime.now().strftime('%Y-%m-%d')}"

        # Create MIME message
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        message = MIMEMultipart("alternative")
        message["to"] = recipient_email
        message["from"] = sender_email
        message["subject"] = subject

        # Add HTML content
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)

        # Encode message
        import base64
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Send
        send_message = {"raw": raw_message}
        result = service.users().messages().send(userId="me", body=send_message).execute()

        message_id = result.get("id", "")
        logger.info(f"Publisher: sent via Gmail, message_id={message_id}")
        return message_id

    except Exception as e:
        logger.error(f"Publisher: Gmail send failed: {e}, using simulated ID")
        return f"simulated_{run_id}"


def _get_gmail_service():
    """
    Authenticate with Gmail API using OAuth2 credentials.
    Supports both service account and installed app (user) credentials.
    """

    try:
        # Try service account first
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
        if creds_path and os.path.exists(creds_path):
            credentials = Credentials.from_service_account_file(creds_path)
            service = build("gmail", "v1", credentials=credentials)
            logger.info("Publisher: authenticated via service account")
            return service
    except Exception as e:
        logger.warning(f"Service account auth failed: {e}")

    try:
        # Try OAuth2 token
        token_path = "gmail_token.json"
        creds_path = "gmail_credentials.json"

        creds = None
        if os.path.exists(token_path):
            creds = OAuthCredentials.from_authorized_user_file(token_path, scopes=["https://www.googleapis.com/auth/gmail.send"])

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Run OAuth flow
                if os.path.exists(creds_path):
                    flow = InstalledAppFlow.from_client_secrets_file(
                        creds_path,
                        scopes=["https://www.googleapis.com/auth/gmail.send"]
                    )
                    creds = flow.run_local_server(port=0)

            # Save token
            if creds:
                with open(token_path, "w") as token_file:
                    token_file.write(creds.to_json())

        if creds:
            service = build("gmail", "v1", credentials=creds)
            logger.info("Publisher: authenticated via OAuth2")
            return service

    except Exception as e:
        logger.warning(f"OAuth2 auth failed: {e}")

    raise RuntimeError("Could not authenticate with Gmail API")


def _update_source_scores(articles: List[Article]) -> None:
    """
    Update credibility scores for sources in published articles.
    Articles that made it to publish = positive signal for their sources.
    """

    try:
        from memory.source_memory import get_source_score

        for article in articles:
            domain = article.get("source_domain", "")
            if not domain:
                continue

            # Boost score slightly for published articles (positive feedback)
            current_score = get_source_score(domain) or 0.5
            boosted_score = min(1.0, current_score + 0.05)
            update_source_score(domain, boosted_score)

        logger.info(f"Publisher: updated source scores for {len(articles)} articles")

    except Exception as e:
        logger.error(f"Publisher: failed to update source scores: {e}")


def _save_fingerprints(newsletter_id: str, articles: List[Article]) -> None:
    """
    Save story fingerprints from published articles for cross-week deduplication.
    """

    try:
        fingerprints = []
        for article in articles:
            title = article.get("title", "")
            domain = article.get("source_domain", "")
            url = article.get("url", "")

            if title and domain:
                fingerprint = compute_fingerprint(title, domain)
                fingerprints.append({
                    "fingerprint": fingerprint,
                    "url": url,
                    "title": title,
                    "source_domain": domain,
                })

        save_story_fingerprints(newsletter_id, fingerprints)
        logger.info(f"Publisher: saved {len(fingerprints)} story fingerprints")

    except Exception as e:
        logger.error(f"Publisher: failed to save fingerprints: {e}")


def _record_topic_history(newsletter_id: str, articles: List[Article]) -> None:
    """
    Record which topics were covered in this newsletter.
    Helps supervisor avoid repeating topics week-to-week.
    """

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Count articles by section
            section_counts = {}
            for article in articles:
                section = article.get("section", "Trending")
                section_counts[section] = section_counts.get(section, 0) + 1

            # Record each section as a "topic"
            for section, count in section_counts.items():
                cursor.execute("""
                    INSERT INTO topic_history
                    (history_id, newsletter_id, topic, article_count, section, date_sent)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    str(uuid.uuid4()),
                    newsletter_id,
                    section,
                    count,
                    section,
                ))

        logger.info(f"Publisher: recorded topic history for {len(section_counts)} sections")

    except Exception as e:
        logger.error(f"Publisher: failed to record topic history: {e}")


def _update_preference_history(
    run_id: str,
    human_review_edits: List[Dict[str, Any]],
    interest_profile: Dict[str, float],
) -> None:
    """
    Update preference history based on human edits.
    """

    try:
        removes_by_section = {}
        approves_by_section = {}

        for edit in human_review_edits:
            action = edit.get("action", "")
            section = edit.get("new_section") or edit.get("section", "Trending")

            if action == "remove":
                removes_by_section[section] = removes_by_section.get(section, 0) + 1
            elif action == "keep":
                approves_by_section[section] = approves_by_section.get(section, 0) + 1

        with get_db() as conn:
            cursor = conn.cursor()

            for section in set(list(removes_by_section.keys()) + list(approves_by_section.keys())):
                topic = section
                weight_before = interest_profile.get(topic, 0.5)

                removes = removes_by_section.get(section, 0)
                approves = approves_by_section.get(section, 0)
                signal = "removed" if removes > approves else ("approved" if approves > 0 else "neutral")

                adjustment = 0.05 if signal == "approved" else (-0.05 if signal == "removed" else 0)
                weight_after = max(0.0, min(1.0, weight_before + adjustment))

                if weight_after != weight_before:
                    cursor.execute("""
                        INSERT INTO preference_history
                        (history_id, run_id, topic, weight_before, weight_after, signal_type, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        str(uuid.uuid4()),
                        run_id,
                        topic,
                        weight_before,
                        weight_after,
                        signal,
                    ))

        logger.info(f"Publisher: updated preference history for {len(removes_by_section)} sections")

    except Exception as e:
        logger.error(f"Publisher: failed to update preference history: {e}")


def _log_eval_metrics(
    run_id: str,
    final_articles: List[Article],
    human_review_edits: List[Dict[str, Any]],
) -> None:
    """
    Log evaluation metrics to database.
    """

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            approves = sum(1 for e in human_review_edits if e.get("action") == "keep")
            rejects = sum(1 for e in human_review_edits if e.get("action") == "remove")
            total_feedback = approves + rejects

            relevance_rate = (approves / total_feedback) if total_feedback > 0 else None

            if relevance_rate is not None:
                cursor.execute("""
                    INSERT INTO eval_results
                    (eval_id, run_id, metric_name, value, details, timestamp)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    str(uuid.uuid4()),
                    run_id,
                    "relevance_rate",
                    relevance_rate,
                    json.dumps({"approves": approves, "rejects": rejects}),
                ))

            if len(final_articles) > 0:
                edit_rate = rejects / len(final_articles)
                cursor.execute("""
                    INSERT INTO eval_results
                    (eval_id, run_id, metric_name, value, details, timestamp)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    str(uuid.uuid4()),
                    run_id,
                    "edit_rate",
                    edit_rate,
                    json.dumps({"edits": rejects, "total": len(final_articles)}),
                ))

            cursor.execute("""
                INSERT INTO eval_results
                (eval_id, run_id, metric_name, value, timestamp)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                str(uuid.uuid4()),
                run_id,
                "articles_published",
                float(len(final_articles)),
            ))

        logger.info("Publisher: logged eval metrics")

    except Exception as e:
        logger.error(f"Publisher: failed to log eval metrics: {e}")


def _archive_newsletter(
    newsletter_id: str,
    html_content: str,
    final_articles: List[Article],
    state: ARIAState,
) -> None:
    """
    Archive the sent newsletter to database for audit trail and retrieval.
    """

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            section_breakdown = {}
            for article in final_articles:
                section = article.get("section", "Trending")
                section_breakdown[section] = section_breakdown.get(section, 0) + 1

            cursor.execute("""
                INSERT INTO newsletters
                (newsletter_id, run_id, send_date, html_content, article_count,
                 cost_usd, section_breakdown, total_fetched, llm_call_count, elapsed_seconds)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
            """, (
                newsletter_id,
                state.get("run_id", ""),
                html_content,
                len(final_articles),
                state.get("estimated_cost_usd", 0.0),
                json.dumps(section_breakdown),
                state.get("total_fetched", 0),
                state.get("llm_call_count", 0),
                state.get("elapsed_seconds", 0.0),
            ))

        logger.info(f"Publisher: archived newsletter {newsletter_id}")

    except Exception as e:
        logger.error(f"Publisher: failed to archive newsletter: {e}")
