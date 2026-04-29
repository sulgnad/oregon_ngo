"""Production ``Clock`` implementation."""

from __future__ import annotations

from datetime import datetime, timezone


class SystemClock:
    """Returns the current wall-clock time in UTC."""

    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)
