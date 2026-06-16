"""
ARIA SQLite Database Layer

Manages persistent memory stores for the newsletter agent.
All memory survives across weekly runs via SQLite.

8 tables:
1. source_scores — Domain credibility tracking
2. story_fingerprints — Cross-week deduplication
3. user_feedback — Human actions during review
4. topic_history — Topics covered per newsletter
5. preference_history — Interest profile drift over time
6. eval_results — Performance metrics per run
7. newsletters — Archive of sent newsletters
8. summary_cache — Cached article summaries by URL
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional
from contextlib import contextmanager

from config import DATABASE_PATH, SUMMARY_CACHE_DAYS, SOURCE_SCORE_CACHE_DAYS


def get_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database. Creates it if it doesn't exist."""
    conn = sqlite3.connect(DATABASE_PATH)
    # Enable foreign keys and JSON support
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA json1")
    return conn


@contextmanager
def get_db():
    """Context manager for database connections. Ensures proper cleanup."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_db() -> None:
    """Initialize the database schema. Idempotent (safe to call multiple times)."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # ===== TABLE 1: source_scores =====
        # Tracks credibility of news sources by domain
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS source_scores (
                domain TEXT PRIMARY KEY,
                credibility_score REAL DEFAULT 0.5,
                last_feedback_date DATETIME,
                feedback_count INTEGER DEFAULT 0,
                created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ===== TABLE 2: story_fingerprints =====
        # Tracks stories that have been published, used for cross-week deduplication
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS story_fingerprints (
                fingerprint TEXT PRIMARY KEY,
                newsletter_id TEXT,
                url TEXT,
                title TEXT,
                source_domain TEXT,
                archived_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ===== TABLE 3: user_feedback =====
        # Human actions during review (thumbs up/down, removals, reorders)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                feedback_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                source_domain TEXT,
                action TEXT NOT NULL,
                feedback TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewer_notes TEXT
            )
        """)

        # ===== TABLE 4: topic_history =====
        # What topics were covered in each sent newsletter
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS topic_history (
                history_id TEXT PRIMARY KEY,
                newsletter_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                article_count INTEGER,
                section TEXT,
                date_sent DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ===== TABLE 5: preference_history =====
        # Track changes to the interest profile over time
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preference_history (
                history_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                weight_before REAL,
                weight_after REAL,
                signal_type TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ===== TABLE 6: eval_results =====
        # Performance metrics captured per run
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS eval_results (
                eval_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ===== TABLE 7: newsletters =====
        # Archive of sent newsletters with full HTML and metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS newsletters (
                newsletter_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                send_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                html_content TEXT NOT NULL,
                article_count INTEGER,
                cost_usd REAL,
                section_breakdown TEXT,
                total_fetched INTEGER,
                llm_call_count INTEGER,
                elapsed_seconds REAL
            )
        """)

        # ===== TABLE 8: summary_cache =====
        # Cached article summaries keyed by URL, to avoid re-summarizing articles
        # that reappear in later weeks (e.g., RSS republishes)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS summary_cache (
                url TEXT PRIMARY KEY,
                summary_text TEXT NOT NULL,
                why_matters TEXT NOT NULL,
                created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_date DATETIME
            )
        """)

        # ===== INDICES =====
        # Speed up common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fingerprint_date ON story_fingerprints(archived_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_run ON user_feedback(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_topic_history_date ON topic_history(date_sent)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_preference_history_run ON preference_history(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_newsletters_date ON newsletters(send_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_summary_cache_expires ON summary_cache(expires_date)")

        conn.commit()
    finally:
        conn.close()


def cleanup_expired_data() -> None:
    """Remove stale cached data (summaries older than threshold, etc.)."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Remove expired summaries
        cursor.execute(
            "DELETE FROM summary_cache WHERE expires_date IS NOT NULL AND expires_date < CURRENT_TIMESTAMP"
        )

        # Remove old fingerprints (older than 28 days)
        cutoff_date = datetime.now() - timedelta(days=28)
        cursor.execute(
            "DELETE FROM story_fingerprints WHERE archived_date < ?",
            (cutoff_date,)
        )


if __name__ == "__main__":
    # Initialize database when run as a script
    print(f"Initializing database at {DATABASE_PATH}...")
    init_db()
    print("✓ Database initialized successfully")

    # Test connection
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"✓ Created {len(tables)} tables:")
        for table in tables:
            print(f"  - {table[0]}")
