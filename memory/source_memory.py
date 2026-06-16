"""
Source Memory Module

Tracks credibility scores for news sources (domains).
Used by Validator to score articles and by Publisher to update scores.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config import KNOWN_CREDIBLE_SOURCES, SOURCE_SCORE_CACHE_DAYS
from memory.db import get_db


def get_source_score(domain: str) -> Optional[float]:
    """
    Get cached credibility score for a domain.
    Returns float (0–1) or None if domain never seen or cache expired.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT credibility_score, updated_date
                FROM source_scores
                WHERE domain = ?
            """, (domain,))
            row = cursor.fetchone()

            if not row:
                return None

            score, updated_date_str = row

            # Check if cache is stale
            try:
                updated_date = datetime.fromisoformat(updated_date_str)
                cache_age_days = (datetime.now() - updated_date).days
                if cache_age_days > SOURCE_SCORE_CACHE_DAYS:
                    return None  # Cache expired, re-score
            except Exception:
                pass

            return score

    except Exception as e:
        print(f"Warning: Failed to read source_score for {domain}: {e}")
        return None


def update_source_score(domain: str, credibility_score: float) -> None:
    """Update or insert credibility score for a domain."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO source_scores
                (domain, credibility_score, updated_date, feedback_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(domain) DO UPDATE SET
                    credibility_score = ?,
                    updated_date = CURRENT_TIMESTAMP,
                    feedback_count = feedback_count + 1
            """, (domain, credibility_score, datetime.now(), credibility_score))
    except Exception as e:
        print(f"Warning: Failed to update source_score for {domain}: {e}")


def get_blacklisted_sources() -> List[str]:
    """Get list of blacklisted source domains."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT domain FROM source_scores
                WHERE credibility_score = 0.0
            """)
            rows = cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        print(f"Warning: Failed to read blacklisted_sources: {e}")
        return []


def blacklist_source(domain: str) -> None:
    """Mark a source as blacklisted (credibility score = 0.0)."""
    update_source_score(domain, 0.0)


def get_all_source_scores() -> Dict[str, float]:
    """Get all cached source scores."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT domain, credibility_score
                FROM source_scores
                WHERE credibility_score > 0.0
            """)
            rows = cursor.fetchall()
            return {domain: score for domain, score in rows}
    except Exception as e:
        print(f"Warning: Failed to read all source_scores: {e}")
        return {}
