from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import services.nexus_data.main as data_main


def _request(token: str = "") -> Request:
    headers = [(b"x-nexus-service-token", token.encode("utf-8"))] if token else []
    return Request({"type": "http", "headers": headers, "method": "POST", "path": "/"})


def test_internal_archive_endpoint_fails_closed_without_long_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_main, "INTERNAL_SERVICE_TOKEN", "short")
    with pytest.raises(HTTPException) as exc:
        data_main._internal_service_ok(_request("short"))
    assert exc.value.status_code == 503


def test_internal_archive_endpoint_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_main, "INTERNAL_SERVICE_TOKEN", "a" * 40)
    with pytest.raises(HTTPException) as exc:
        data_main._internal_service_ok(_request("b" * 40))
    assert exc.value.status_code == 401


def test_source_revision_endpoint_allows_only_internal_services(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "c" * 40
    monkeypatch.setattr(data_main, "INTERNAL_SERVICE_TOKEN", token)
    calls: list[tuple[list[dict], str]] = []

    async def persist(records: list[dict], *, caller_service: str) -> int:
        calls.append((records, caller_service))
        return len(records)

    monkeypatch.setattr(data_main, "data_store", SimpleNamespace(persist_source_revisions=persist))
    body = {"caller_service": "nexus-news", "records": [{"dataset": "news"}]}
    result = asyncio.run(data_main.ingest_source_revisions(_request(token), body))
    assert result == {"accepted": 1, "received": 1}
    assert calls == [(body["records"], "nexus-news")]

    with pytest.raises(HTTPException) as exc:
        asyncio.run(data_main.ingest_source_revisions(
            _request(token), {"caller_service": "nexus-ml", "records": [{"dataset": "news"}]},
        ))
    assert exc.value.status_code == 403
