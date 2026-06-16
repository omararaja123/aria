"""
Topic History Memory Module

Reads what topics have been covered in recent newsletters.
Used by Supervisor to avoid repeating topics week-to-week.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional
from memory.db import get_db


def get_topic_history(weeks_back: int = 4) -> Dict[str, int]:
    """
    Get topics covered in the last N weeks, aggregated by count.
    Returns dict like: {"Large Language Models": 5, "Computer Vision": 3}
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cutoff_date = datetime.now() - timedelta(days=7 * weeks_back)
            cursor.execute("""
                SELECT topic, SUM(article_count) as total_count
                FROM topic_history
                WHERE date_sent > ?
                GROUP BY topic
                ORDER BY total_count DESC
            """, (cutoff_date,))
            rows = cursor.fetchall()
            return {topic: count for topic, count in rows}
    except Exception as e:
        print(f"Warning: Failed to read topic_history: {e}")
        return {}


def get_last_newsletter_date() -> Optional[datetime]:
    """Get the date of the most recent sent newsletter."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT send_date
                FROM newsletters
                ORDER BY send_date DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            return datetime.fromisoformat(row[0]) if row else None
    except Exception as e:
        print(f"Warning: Failed to read last_newsletter_date: {e}")
        return None
