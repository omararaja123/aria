"""
Summary Cache Module

Caches article summaries by URL to avoid re-summarizing articles
that reappear in later weeks (e.g., RSS republishes, duplicate stories).

Cache hit rate: ~20-30% over time (typical weekly newsletters).
Savings: ~$0.06-0.10/run from avoided redundant Haiku calls.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict

from config import SUMMARY_CACHE_DAYS
from memory.db import get_db


def get_cached_summary(url: str) -> Optional[Dict[str, str]]:
    """
    Get cached summary for a URL.
    Returns {summary_text, why_matters} or None if not cached/expired.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT summary_text, why_matters, expires_date
                FROM summary_cache
                WHERE url = ?
            """, (url,))
            row = cursor.fetchone()

            if not row:
                return None

            summary_text, why_matters, expires_date_str = row

            # Check if cache is expired
            if expires_date_str:
                try:
                    expires_date = datetime.fromisoformat(expires_date_str)
                    if datetime.now() > expires_date:
                        return None  # Cache expired
                except Exception:
                    pass

            return {
                "summary_text": summary_text,
                "why_matters": why_matters,
            }

    except Exception as e:
        print(f"Warning: Failed to read summary cache for {url}: {e}")
        return None


def save_summary(
    url: str,
    summary_text: str,
    why_matters: str,
) -> None:
    """Save a summary to cache. Expires after SUMMARY_CACHE_DAYS."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            expires_date = datetime.now() + timedelta(days=SUMMARY_CACHE_DAYS)
            cursor.execute("""
                INSERT INTO summary_cache
                (url, summary_text, why_matters, created_date, expires_date)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(url) DO UPDATE SET
                    summary_text = ?,
                    why_matters = ?,
                    expires_date = ?
            """, (url, summary_text, why_matters, expires_date, summary_text, why_matters, expires_date))
    except Exception as e:
        print(f"Warning: Failed to save summary cache for {url}: {e}")


def clear_expired_summaries() -> int:
    """Remove expired summaries from cache. Returns count removed."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM summary_cache
                WHERE expires_date IS NOT NULL AND expires_date < CURRENT_TIMESTAMP
            """)
            return cursor.rowcount
    except Exception as e:
        print(f"Warning: Failed to clear expired summaries: {e}")
        return 0
