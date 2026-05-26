"""Production ``HttpClient`` implementation backed by ``requests``.

Wraps a ``requests.Session`` with:
- a polite User-Agent
- retry/backoff on transient errors via ``urllib3.util.Retry``
- a simple per-host token-bucket rate limiter (default 1 req/sec)
"""

from __future__ import annotations

import threading
import time
from typing import Callable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .protocols import HttpResponse


DEFAULT_USER_AGENT = (
    "OregonNGOResearch/0.1 (academic; contact: opal@oregonstate.edu)"
)


class _HostRateLimiter:
    """Naive per-host rate limiter: enforces ``min_interval`` between calls.

    ``time.monotonic()`` is documented as returning a clock with an *undefined*
    reference point; on macOS + Python 3.9 it returns time since process
    start, which can be a small fractional value. We therefore explicitly
    track which hosts have been seen rather than relying on a 0.0 default,
    so the first call to ``wait()`` per host is always a no-op.
    """

    def __init__(self, min_interval: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self._min_interval = min_interval
        self._sleep = sleep
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            prev = self._last_call.get(host)
            if prev is not None:
                elapsed = now - prev
                if elapsed < self._min_interval:
                    self._sleep(self._min_interval - elapsed)
            self._last_call[host] = time.monotonic()


class RequestsHttpClient:
    """Concrete ``HttpClient`` backed by a ``requests.Session``.

    Defaults are tuned for a polite-but-resilient web scrape:
    short connect/read timeouts, retry only on 5xx/429, and never retry
    connection errors (so an unresolvable host fails fast instead of
    blocking the whole pipeline for minutes).
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_limit_per_host: float = 1.0,
        retries: int = 1,
        backoff_factor: float = 0.3,
        default_timeout: float | tuple[float, float] = (5.0, 10.0),
        session: requests.Session | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._default_timeout = default_timeout
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

        retry_cfg = Retry(
            total=retries,
            connect=0,  # do NOT retry connection / DNS failures
            read=retries,
            status=retries,
            backoff_factor=backoff_factor,
            status_forcelist=(500, 502, 503, 504, 429),
            allowed_methods=("GET", "HEAD"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_cfg)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        min_interval = 1.0 / rate_limit_per_host if rate_limit_per_host > 0 else 0.0
        self._limiter = _HostRateLimiter(min_interval)

    def get(
        self,
        url: str,
        *,
        timeout: float | tuple[float, float] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        host = urlparse(url).netloc
        self._limiter.wait(host)
        merged = dict(headers or {})
        effective_timeout = timeout if timeout is not None else self._default_timeout
        resp = self._session.get(url, timeout=effective_timeout, headers=merged)
        return HttpResponse(status_code=resp.status_code, text=resp.text, url=resp.url)

    def close(self) -> None:
        self._session.close()
