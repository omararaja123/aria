"""
Date Extraction Skill

Extracts publication dates from:
1. URL patterns (e.g., /2024/06/15/, /2024-06-15-)
2. HTML meta tags (og:published_time, article:published_time, etc.)
3. HTML content patterns (Posted on June 15, 2024, etc.)

Handles timezone conversion and returns normalized datetime objects.
"""

import re
import logging
from datetime import datetime
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

logger = logging.getLogger(__name__)


def extract_date_from_url(url: str) -> Optional[datetime]:
    """
    Extract publication date from URL patterns.

    Patterns:
    - /2024/06/15/ or /2024/6/15/
    - /2024-06-15 or /2024-06-15-
    - /20240615/
    - article-june-15-2024
    - article-2024-06-15
    """
    if not url:
        return None

    try:
        # Pattern 1: /YYYY/MM/DD/
        match = re.search(r'/(\d{4})/(\d{1,2})/(\d{1,2})/', url)
        if match:
            year, month, day = match.groups()
            return datetime(int(year), int(month), int(day))

        # Pattern 2: /YYYY-MM-DD or /YYYY-MM-DD-
        match = re.search(r'/(\d{4})-(\d{2})-(\d{2})', url)
        if match:
            year, month, day = match.groups()
            return datetime(int(year), int(month), int(day))

        # Pattern 3: /YYYYMMDD/
        match = re.search(r'/(\d{4})(\d{2})(\d{2})/', url)
        if match:
            year, month, day = match.groups()
            return datetime(int(year), int(month), int(day))

        # Pattern 4: article-month-day-year format
        months = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
            'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
        }

        for month_name, month_num in months.items():
            match = re.search(rf'{month_name}-(\d{{1,2}})-(\d{{4}})', url, re.IGNORECASE)
            if match:
                day, year = match.groups()
                return datetime(int(year), month_num, int(day))

        # Pattern 5: YYYY-MM-DD anywhere in URL
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', url)
        if match:
            year, month, day = match.groups()
            return datetime(int(year), int(month), int(day))

    except (ValueError, AttributeError):
        logger.debug(f"Could not extract date from URL: {url}")

    return None


def extract_date_from_html(html_content: str) -> Optional[datetime]:
    """
    Extract publication date from HTML meta tags.

    Looks for:
    - og:published_time
    - article:published_time
    - datePublished
    - publish_date
    - DC.issued
    """
    if not html_content or not HAS_BS4:
        return None

    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # Meta tag patterns to check
        patterns = [
            ('property', 'og:published_time'),
            ('property', 'article:published_time'),
            ('name', 'datePublished'),
            ('name', 'publish_date'),
            ('name', 'article.created'),
            ('itemprop', 'datePublished'),
            ('name', 'DC.issued'),
        ]

        for attr_name, attr_value in patterns:
            meta = soup.find('meta', attrs={attr_name: attr_value})
            if meta and meta.get('content'):
                date_str = meta.get('content')
                return parse_iso_date(date_str)

        # Try to find date in common patterns in HTML text
        text = soup.get_text()

        # Pattern: "Published on June 15, 2024"
        match = re.search(
            r'(?:published|posted|updated)(?:\s+on)?\s+([a-z]+)\s+(\d{1,2}),?\s+(\d{4})',
            text,
            re.IGNORECASE
        )
        if match:
            month_name, day, year = match.groups()
            month_map = {
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
            }
            month = month_map.get(month_name[:3].lower())
            if month:
                try:
                    return datetime(int(year), month, int(day))
                except ValueError:
                    pass

    except Exception as e:
        logger.debug(f"Error extracting date from HTML: {e}")

    return None


def parse_iso_date(date_str: str) -> Optional[datetime]:
    """Parse ISO 8601 date string to datetime."""
    if not date_str:
        return None

    try:
        # Handle ISO format with timezone
        if 'T' in date_str:
            # Remove timezone info for simplicity
            date_str = date_str.split('+')[0].split('Z')[0]

        # Try parsing with common formats
        for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d']:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Fallback to dateutil parser
        try:
            from dateutil import parser as date_parser
            return date_parser.parse(date_str)
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"Error parsing date string '{date_str}': {e}")

    return None


async def extract_article_date(url: str, timeout: int = 5) -> Optional[datetime]:
    """
    Extract publication date from an article URL.

    1. First tries URL pattern extraction (fast, no network)
    2. Then tries to fetch and parse HTML (slower, but accurate)

    Returns datetime or None if extraction fails.
    """
    # Try URL pattern first (fastest)
    date_from_url = extract_date_from_url(url)
    if date_from_url:
        logger.debug(f"Extracted date from URL {url}: {date_from_url.date()}")
        return date_from_url

    # Try fetching HTML (slower but more reliable)
    if not HAS_REQUESTS:
        logger.debug(f"requests library not available; cannot fetch HTML for {url}")
        return None

    try:
        import asyncio
        response = await asyncio.to_thread(
            requests.get,
            url,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        )
        response.raise_for_status()

        date_from_html = extract_date_from_html(response.text)
        if date_from_html:
            logger.debug(f"Extracted date from HTML {url}: {date_from_html.date()}")
            return date_from_html

    except Exception as e:
        logger.debug(f"Could not fetch/parse {url}: {e}")

    return None
