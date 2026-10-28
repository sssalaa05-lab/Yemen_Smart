"""Tests for nexus_news service — fetcher, calendar, sentiment."""
from __future__ import annotations

from pathlib import Path

import pytest


NEWS_SVC = Path(__file__).resolve().parents[2] / "services" / "nexus_news"


class TestNewsServiceFiles:
    REQUIRED = [
        "__init__.py", "main.py", "news_fetcher.py",
        "calendar_parser.py", "social_sentiment.py",
    ]

    @pytest.mark.parametrize("filename", REQUIRED)
    def test_file_exists(self, filename: str):
        assert (NEWS_SVC / filename).exists(), f"Missing news file: {filename}"


class TestNewsFetcherImport:
    def test_importable(self):
        import importlib
        mod = importlib.import_module("services.nexus_news.news_fetcher")
        assert mod is not None


class TestCalendarParserImport:
    def test_importable(self):
        import importlib
        mod = importlib.import_module("services.nexus_news.calendar_parser")
        assert mod is not None


class TestNewsModelValidation:
    def test_news_item_creation(self, sample_news_item):
        assert sample_news_item.headline == "Fed holds rates steady"
        assert sample_news_item.impact == "high"

    def test_news_item_default_impact(self):
        from shared.models import NewsItem
        item = NewsItem(headline="Minor data release")
        assert item.impact == "low"
        assert item.sentiment == "neutral"
        assert item.available_at is None

    def test_news_revision_identity_is_stable_and_separate_from_availability(self):
        from datetime import datetime, timezone
        from services.nexus_news.news_fetcher import _news_revision_id
        from shared.models import NewsItem

        published = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)
        observed = datetime(2026, 10, 28, 10, 1, tzinfo=timezone.utc)
        revision = _news_revision_id("provider", "Headline", published)
        item = NewsItem(
            headline="Headline", source="provider", timestamp=published,
            available_at=observed, revision_id=revision,
        )
        assert item.timestamp == published
        assert item.available_at == observed
        assert _news_revision_id("provider", "Headline", published) == revision
        assert _news_revision_id("provider", "Corrected headline", published) != revision

    def test_calendar_event_has_separate_observed_time_and_vintage_fields(self):
        from datetime import datetime, timezone
        from shared.models import CalendarEvent

        event = CalendarEvent(
            event_name="CPI", currency="USD",
            timestamp=datetime(2026, 10, 28, 12, tzinfo=timezone.utc),
            available_at=datetime(2026, 10, 28, 11, tzinfo=timezone.utc),
            event_id="event-1", revision_id="revision-1",
        )
        assert event.available_at < event.timestamp
        assert event.event_id == "event-1"
        assert event.revision_id == "revision-1"

    def test_calendar_revisions_are_content_addressed_and_first_observed(self):
        from datetime import datetime, timezone
        from services.nexus_news.calendar_parser import _stamp_calendar_revisions
        from shared.models import CalendarEvent

        scheduled = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        first = datetime(2026, 10, 28, 10, tzinfo=timezone.utc)
        repoll = datetime(2026, 10, 28, 10, 5, tzinfo=timezone.utc)
        event = CalendarEvent(event_name="CPI", currency="USD", timestamp=scheduled, forecast="3.0")
        _stamp_calendar_revisions([event], first)
        rev_id, event_id = event.revision_id, event.event_id
        same = CalendarEvent(event_name="CPI", currency="USD", timestamp=scheduled, forecast="3.0")
        _stamp_calendar_revisions([same], repoll, {rev_id: first})
        assert same.revision_id == rev_id
        assert same.event_id == event_id
        assert same.available_at == first

        corrected = CalendarEvent(event_name="CPI", currency="USD", timestamp=scheduled, forecast="3.1")
        _stamp_calendar_revisions([corrected], repoll, {rev_id: first})
        assert corrected.revision_id != rev_id
        assert corrected.available_at == repoll

    def test_news_repoll_preserves_first_observed_time_for_same_revision(self):
        from datetime import datetime, timezone
        from services.nexus_news.main import _merge_news
        from services.nexus_news.news_fetcher import _news_revision_id
        from shared.models import NewsItem

        published = datetime(2026, 10, 28, 9, tzinfo=timezone.utc)
        first = datetime(2026, 10, 28, 9, 1, tzinfo=timezone.utc)
        repoll = datetime(2026, 10, 28, 9, 5, tzinfo=timezone.utc)
        revision = _news_revision_id("provider", "Headline", published)
        old = NewsItem(headline="Headline", source="provider", timestamp=published,
                       available_at=first, revision_id=revision)
        incoming = NewsItem(headline="Headline", source="provider", timestamp=published,
                            available_at=repoll, revision_id=revision)
        merged = _merge_news([old], [incoming], 10)
        assert len(merged) == 1
        assert merged[0].available_at == first
