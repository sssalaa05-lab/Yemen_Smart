from __future__ import annotations

import asyncio

import httpx
import pytest

import shared.source_revision_client as revision_client


def test_submit_source_revisions_sends_authenticated_iso_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "s" * 40
    monkeypatch.setenv("NEXUS_INTERNAL_SERVICE_TOKEN", token)
    monkeypatch.setenv("NEXUS_DATA_URL", "http://data.test")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/data/ingest/source-revisions"
        assert request.headers["x-nexus-service-token"] == token
        seen.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"accepted": len(seen[-1]["records"])})

    monkeypatch.setattr(
        revision_client,
        "new_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs),
    )
    records = [{"dataset": "news", "available_at": "2026-10-28T12:00:00+00:00"}]
    accepted = asyncio.run(revision_client.submit_source_revisions(records, caller_service="nexus-news"))

    assert accepted == 1
    assert seen == [{"caller_service": "nexus-news", "records": records}]


def test_submit_source_revisions_refuses_short_secret_and_unknown_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_INTERNAL_SERVICE_TOKEN", "short")
    with pytest.raises(RuntimeError):
        asyncio.run(revision_client.submit_source_revisions([{}], caller_service="nexus-news"))

    monkeypatch.setenv("NEXUS_INTERNAL_SERVICE_TOKEN", "s" * 40)
    with pytest.raises(ValueError):
        asyncio.run(revision_client.submit_source_revisions([{}], caller_service="unknown-service"))
