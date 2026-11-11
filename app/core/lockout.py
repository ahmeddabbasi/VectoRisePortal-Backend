"""Slow repeated login attempts without saying whether an account exists."""

import threading
import time

from fastapi import HTTPException


class LoginGuard:
    def __init__(self, email_limit: int = 8, ip_limit: int = 40, window_seconds: int = 900):
        self.email_limit = email_limit
        self.ip_limit = ip_limit
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [stamp for stamp in self._events.get(key, []) if now - stamp < self.window_seconds]
        if recent:
            self._events[key] = recent
        else:
            self._events.pop(key, None)
        return recent

    def check(self, ip: str, email: str) -> None:
        now = time.monotonic()
        with self._lock:
            email_hits = self._prune(f"email:{email}", now)
            ip_hits = self._prune(f"ip:{ip}", now)
        if len(email_hits) >= self.email_limit or len(ip_hits) >= self.ip_limit:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(self.window_seconds)},
            )

    def fail(self, ip: str, email: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in (f"email:{email}", f"ip:{ip}"):
                hits = self._prune(key, now)
                hits.append(now)
                self._events[key] = hits

    def succeed(self, email: str) -> None:
        with self._lock:
            self._events.pop(f"email:{email}", None)


login_guard = LoginGuard()
