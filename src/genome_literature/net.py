"""Shared HTTP client with per-host throttling and retry/backoff."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from . import __version__, config

logger = logging.getLogger(__name__)

USER_AGENT = f"3DGenomeHub/{__version__} (+{config.REPO_URL})"
RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    """Thin wrapper around ``httpx.Client`` that is polite to public APIs."""

    def __init__(self, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        headers = {"User-Agent": USER_AGENT}
        if config.CROSSREF_MAILTO:
            headers["User-Agent"] += f" mailto:{config.CROSSREF_MAILTO}"
        self._client = httpx.Client(
            timeout=httpx.Timeout(config.HTTP_TIMEOUT, connect=15.0),
            headers=headers,
            follow_redirects=True,
            transport=transport,
        )
        self._sleep = sleep
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def _throttle(self, host: str) -> None:
        interval = config.HOST_MIN_INTERVAL.get(host, 0.25)
        with self._lock:
            wait = self._last_call.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_call[host] = time.monotonic()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlparse(url).netloc
        attempts = config.HTTP_MAX_RETRIES + 1
        for attempt in range(1, attempts + 1):
            self._throttle(host)
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt == attempts:
                    raise
                delay = min(2 ** attempt, 30)
                logger.warning("%s %s failed (%s); retry %d/%d in %ss", method, host, exc, attempt, attempts - 1, delay)
                self._sleep(delay)
                continue
            if resp.status_code in RETRY_STATUS and attempt < attempts:
                delay = _retry_after(resp) or min(2 ** attempt * (3 if resp.status_code == 429 else 1), 60)
                logger.warning("%s %s -> HTTP %d; retry %d/%d in %ss", method, host, resp.status_code, attempt, attempts - 1, delay)
                self._sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError("unreachable")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(float(value), 120.0)
    except ValueError:
        return None


_default: HttpClient | None = None


def get_client() -> HttpClient:
    global _default
    if _default is None:
        _default = HttpClient()
    return _default
