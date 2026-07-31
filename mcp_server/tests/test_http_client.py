"""Offline tests for the HTTP layer: IOC URL-encoding + retry behaviour.

A fake httpx-like client lets us drive the retry loop deterministically with no
network. ``asyncio.sleep`` is patched to a no-op so backoff adds no wall time.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

import http_client
from http_client import VisionOneClient, fetch_virustotal


class _Resp:
    def __init__(self, status_code: int = 200, text: str = '{"ok":true}', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400


class _FakeClient:
    """Returns queued responses (or raises queued exceptions) per request."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def request(self, method, url, *, params=None, json=None, headers=None):
        self.calls.append((method, url))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(*_args, **_kwargs):
        return None

    monkeypatch.setattr(http_client.asyncio, "sleep", _instant)


async def test_ioc_is_url_encoded_into_its_path_segment():
    client = _FakeClient([_Resp()])
    await fetch_virustotal(
        client, base_url="https://vt/api/v3", api_key="k", ioc_path="files", ioc="../../etc/passwd"
    )
    _method, url = client.calls[0]
    assert url == "https://vt/api/v3/files/..%2F..%2Fetc%2Fpasswd"


async def test_retries_transient_5xx_then_succeeds():
    client = _FakeClient([_Resp(status_code=500), _Resp(status_code=200, text='{"ok":1}')])
    out = await fetch_virustotal(
        client,
        base_url="https://vt",
        api_key="k",
        ioc_path="files",
        ioc="abc",
        backoff_base=0,
        backoff_max=0,
    )
    assert out == '{"ok":1}'
    assert len(client.calls) == 2


async def test_rate_limit_raises_after_exhausting_retries():
    client = _FakeClient([_Resp(status_code=429), _Resp(status_code=429)])
    with pytest.raises(ToolError):
        await fetch_virustotal(
            client,
            base_url="https://vt",
            api_key="k",
            ioc_path="files",
            ioc="abc",
            max_retries=1,
            backoff_base=0,
            backoff_max=0,
        )
    assert len(client.calls) == 2


class _JsonResp(_Resp):
    """Adds the .content / .json() surface VisionOneClient expects."""

    def __init__(self, payload):
        import json as _json

        super().__init__(status_code=200, text=_json.dumps(payload))
        self._payload = payload
        self.content = self.text.encode()

    def json(self):
        return self._payload


async def test_paginate_stops_early_at_max_items():
    # Two pages of 2 items; max_items=3 must return exactly 3 and not over-fetch.
    page1 = _JsonResp({"items": [1, 2], "nextLink": "https://vo/next"})
    page2 = _JsonResp({"items": [3, 4]})
    client = _FakeClient([page1, page2])
    vo = VisionOneClient(base_url="https://vo", api_key="k", http=client)
    items = await vo.paginate("/things", max_items=3)
    assert items == [1, 2, 3]
    assert len(client.calls) == 2
