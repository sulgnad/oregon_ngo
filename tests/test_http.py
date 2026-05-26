"""Unit tests for the HTTP adapter's per-host rate limiter.

These tests don't hit the network; they exercise the throttling logic by
injecting a fake ``sleep`` callable.
"""

from __future__ import annotations

from oregon_ngo_scraper.http import _HostRateLimiter


def test_rate_limiter_does_not_sleep_when_disabled() -> None:
    slept: list[float] = []
    limiter = _HostRateLimiter(0.0, sleep=slept.append)
    limiter.wait("example.org")
    limiter.wait("example.org")
    assert slept == []


def test_rate_limiter_sleeps_to_respect_min_interval() -> None:
    slept: list[float] = []
    limiter = _HostRateLimiter(1.0, sleep=slept.append)
    limiter.wait("example.org")  # first call: no sleep
    limiter.wait("example.org")  # second call should sleep close to 1s
    assert len(slept) == 1
    assert 0.0 < slept[0] <= 1.0


def test_rate_limiter_independent_per_host() -> None:
    slept: list[float] = []
    limiter = _HostRateLimiter(1.0, sleep=slept.append)
    limiter.wait("a.org")
    limiter.wait("b.org")
    assert slept == []
