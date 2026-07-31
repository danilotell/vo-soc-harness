"""
Async HTTP clients for Vision One and VirusTotal.

Cross-cutting concerns live here so the tools stay thin:
  * a single shared ``httpx.AsyncClient`` (connection pooling / keep-alive),
  * retries with exponential backoff + jitter for transient failures, shared by
    BOTH upstreams via ``_send_with_retries``,
  * upstream errors translated into ``ToolError`` with safe, LLM-friendly
    messages (full details are logged, never returned to the client),
  * bounded pagination so a runaway ``nextLink`` cannot exhaust memory.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any
from urllib.parse import quote

import httpx
from fastmcp.exceptions import ToolError

logger = logging.getLogger("vo_mcp.http")

# Status codes worth retrying: rate limiting + transient server errors.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _backoff_delay(attempt: int, retry_after: str | None, *, base: float, maximum: float) -> float:
    """Seconds to wait before a retry: honour Retry-After, else exp backoff + jitter."""
    if retry_after:
        try:
            return min(float(retry_after), maximum)
        except ValueError:
            pass
    delay = base * (2**attempt)
    return min(delay, maximum) + random.uniform(0, base)


async def _send_with_retries(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json: Any | None = None,
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
    service: str,
) -> httpx.Response:
    """Send a request with retries on transient failures.

    Returns the (possibly error-status) response; status-specific translation is
    left to the caller, which knows the upstream's error semantics.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await http.request(method, url, params=params, json=json, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "%s %s %s transport error (attempt %d/%d): %s",
                service,
                method,
                url,
                attempt + 1,
                max_retries + 1,
                exc,
            )
            if attempt < max_retries:
                await asyncio.sleep(
                    _backoff_delay(attempt, None, base=backoff_base, maximum=backoff_max)
                )
                continue
            raise ToolError(f"Could not reach {service}. Try again later.") from exc

        if response.status_code in _RETRYABLE_STATUS and attempt < max_retries:
            delay = _backoff_delay(
                attempt, response.headers.get("Retry-After"), base=backoff_base, maximum=backoff_max
            )
            logger.warning(
                "%s %s %s returned %d; retrying in %.2fs (attempt %d/%d)",
                service,
                method,
                url,
                response.status_code,
                delay,
                attempt + 1,
                max_retries + 1,
            )
            await asyncio.sleep(delay)
            continue

        return response

    # Defensive: loop always returns or raises above.
    raise ToolError(f"Could not reach {service}. Try again later.") from last_exc


class VisionOneClient:
    """Thin authenticated wrapper around the Vision One v3.0 API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        http: httpx.AsyncClient,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        max_pages: int = 50,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._max_pages = max_pages

    # -- internal helpers --------------------------------------------------

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Perform a request with retries; raise a safe ToolError on failure."""
        headers = self._headers(extra_headers)
        if json is not None:
            headers.setdefault("Content-Type", "application/json;charset=utf-8")

        response = await _send_with_retries(
            self._http,
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            max_retries=self._max_retries,
            backoff_base=self._backoff_base,
            backoff_max=self._backoff_max,
            service="Vision One",
        )
        _raise_for_vo_status(response, method, url)
        return response

    # -- public verbs ------------------------------------------------------

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self._request(
            "GET", self._base_url + path, params=params or {}, extra_headers=extra_headers
        )
        return response.json() if response.content else None

    async def post(self, path: str, body: Any) -> Any:
        response = await self._request("POST", self._base_url + path, json=body)
        return response.json() if response.content else None

    async def patch(self, path: str, body: Any) -> Any:
        response = await self._request("PATCH", self._base_url + path, json=body)
        return response.json() if response.content else None

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        max_items: int | None = None,
    ) -> list[Any]:
        """Collect ``items`` across pages, bounded by ``max_pages``.

        ``max_items`` stops paging early once enough items are gathered, so a
        small caller-supplied limit does not fetch every page.
        """
        items: list[Any] = []
        next_url: str | None = None

        for _page in range(self._max_pages):
            if next_url is None:
                data = await self.get(path, params=params, extra_headers=extra_headers)
            else:
                response = await self._request("GET", next_url)
                data = response.json() if response.content else {}

            if not data:
                break
            items.extend(data.get("items", []))
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            next_url = data.get("nextLink")
            if not next_url:
                return items

        logger.warning(
            "Pagination for %s hit the max_pages cap (%d); results may be truncated.",
            path,
            self._max_pages,
        )
        return items[:max_items] if max_items is not None else items


def _raise_for_vo_status(response: httpx.Response, method: str, url: str) -> None:
    """Translate an error response into a safe ToolError (logs full detail)."""
    if not response.is_error:
        return

    status = response.status_code
    logger.error(
        "Vision One %s %s failed: %d %s",
        method,
        url,
        status,
        response.text[:500],
    )

    if status in (401, 403):
        raise ToolError("Vision One authentication failed. Check the API key/permissions.")
    if status == 404:
        raise ToolError("The requested Vision One resource was not found.")
    if status == 400:
        raise ToolError("Vision One rejected the request (invalid parameters).")
    if status == 429:
        raise ToolError("Vision One rate limit exceeded. Try again later.")
    if 500 <= status < 600:
        raise ToolError("Vision One is currently unavailable. Try again later.")
    raise ToolError(f"Vision One request failed (HTTP {status}).")


async def fetch_virustotal(
    http: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    ioc_path: str,
    ioc: str,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    backoff_max: float = 8.0,
) -> str:
    """Query VirusTotal for an IOC reputation; return the raw JSON text.

    ``ioc`` is URL-encoded so it cannot break out of its path segment (a value
    like ``../../other`` must not reach a different VirusTotal resource).
    """
    url = f"{base_url}/{ioc_path}/{quote(ioc, safe='')}"
    response = await _send_with_retries(
        http,
        "GET",
        url,
        headers={"accept": "application/json", "x-apikey": api_key},
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        service="VirusTotal",
    )

    if response.is_error:
        logger.error(
            "VirusTotal %s failed: %d %s", ioc_path, response.status_code, response.text[:500]
        )
        if response.status_code in (401, 403):
            raise ToolError("VirusTotal authentication failed. Check VT_API_KEY.")
        if response.status_code == 404:
            raise ToolError("VirusTotal has no record for this indicator.")
        if response.status_code == 429:
            raise ToolError("VirusTotal rate limit exceeded. Try again later.")
        raise ToolError(f"VirusTotal request failed (HTTP {response.status_code}).")

    return response.text
