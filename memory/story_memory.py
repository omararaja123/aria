"""
Story Memory Module

Tracks story fingerprints across weeks for cross-week deduplication.
Prevents the same story from appearing in multiple newsletters.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Set

from memory.db import get_db


def compute_fingerprint(title: str, source_domain: str) -> str:
    """
    Compute a cryptographic fingerprint of a story.
    Combines title (normalized) + source_domain to uniquely identify the story.
    """
    # Normalize title: lowercase, strip whitespace
    normalized = f"{title.lower().strip()}:{source_domain.lower().strip()}"
    # SHA256 hash
    return hashlib.sha256(normalized.encode()).hexdigest()


def is_story_seen(fingerprint: str, weeks_back: int = 4) -> bool:
    """
    Check if a story (by fingerprint) was published in a recent newsletter.
    Returns True if story was in newsletter within weeks_back weeks.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=7 * weeks_back)
            cursor.execute("""
                SELECT COUNT(*) FROM story_fingerprints
                WHERE fingerprint = ? AND archived_date > ?
            """, (fingerprint, cutoff_date))
            count = cursor.fetchone()[0]
            return count > 0
    except Exception as e:
        print(f"Warning: Failed to check story fingerprint: {e}")
        return False


def get_recent_fingerprints(weeks_back: int = 4) -> Set[str]:
    """
    Get all fingerprints from newsletters sent in the last weeks_back weeks.
    Used to exclude recently-published stories.
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=7 * weeks_back)
            cursor.execute("""
                SELECT DISTINCT fingerprint FROM story_fingerprints
                WHERE archived_date > ?
            """, (cutoff_date,))
            rows = cursor.fetchall()
            return {row[0] for row in rows}
    except Exception as e:
        print(f"Warning: Failed to read recent fingerprints: {e}")
        return set()


def save_story_fingerprints(newsletter_id: str, fingerprints: List[Dict]) -> None:
    """
    Save fingerprints from a published newsletter to memory.
    Called by Publisher after sending.
    
    fingerprints: list of {fingerprint, url, title, source_domain}
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            for fp_dict in fingerprints:
                cursor.execute("""
                    INSERT INTO story_fingerprints
                    (fingerprint, newsletter_id, url, title, source_domain, archived_date)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    fp_dict.get("fingerprint"),
                    newsletter_id,
                    fp_dict.get("url"),
                    fp_dict.get("title"),
                    fp_dict.get("source_domain"),
                ))
    except Exception as e:
        print(f"Warning: Failed to save story fingerprints: {e}")


def get_story_metadata(fingerprint: str) -> Dict:
    """
    Get metadata about a story (e.g., when it was published, in which newsletter).
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT newsletter_id, url, title, archived_date
                FROM story_fingerprints
                WHERE fingerprint = ?
                ORDER BY archived_date DESC
                LIMIT 1
            """, (fingerprint,))
            row = cursor.fetchone()
            if row:
                newsletter_id, url, title, archived_date = row
                return {
                    "newsletter_id": newsletter_id,
                    "url": url,
                    "title": title,
                    "archived_date": archived_date,
                }
    except Exception as e:
        print(f"Warning: Failed to get story metadata: {e}")
    
    return {}
