"""Login abuse control (ADR-010 §4): fixed windows in Redis, failing closed.

If Redis cannot be reached, logins are refused with 503 rather than allowed
without limits. Emails are keyed by SHA-256 hash, never stored in Redis.
"""

import hashlib
from dataclasses import dataclass

import redis.exceptions
from redis import Redis

from app.core.clock import Clock
from app.core.errors import DependencyUnavailable, RateLimited

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_EMAIL = 5
MAX_ATTEMPTS_PER_IP = 30
KEY_PREFIX = "auth:login"


@dataclass(frozen=True)
class LoginRateLimiter:
    redis: Redis
    clock: Clock

    def _window(self) -> tuple[int, int]:
        now = int(self.clock.now().timestamp())
        index = now // WINDOW_SECONDS
        return index, (index + 1) * WINDOW_SECONDS - now

    @staticmethod
    def _email_key(email: str, window: int) -> str:
        digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
        return f"{KEY_PREFIX}:email:{digest}:{window}"

    @staticmethod
    def _ip_key(ip: str, window: int) -> str:
        return f"{KEY_PREFIX}:ip:{hashlib.sha256(ip.encode('utf-8')).hexdigest()}:{window}"

    def check_and_count(self, email: str, ip: str) -> None:
        """Count this attempt against the IP; refuse if the IP or email is over budget."""
        window, remaining = self._window()
        try:
            pipe = self.redis.pipeline()
            pipe.incr(self._ip_key(ip, window))
            pipe.expire(self._ip_key(ip, window), WINDOW_SECONDS)
            pipe.get(self._email_key(email, window))
            ip_attempts, _, email_failures = pipe.execute()
        except redis.exceptions.RedisError:
            raise DependencyUnavailable() from None
        if int(ip_attempts) > MAX_ATTEMPTS_PER_IP or int(email_failures or 0) >= MAX_FAILURES_PER_EMAIL:
            raise RateLimited(headers={"Retry-After": str(remaining)})

    def record_failure(self, email: str) -> None:
        window, _ = self._window()
        key = self._email_key(email, window)
        try:
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS)
            pipe.execute()
        except redis.exceptions.RedisError:
            raise DependencyUnavailable() from None

    def reset(self, email: str) -> None:
        window, _ = self._window()
        try:
            self.redis.delete(self._email_key(email, window))
        except redis.exceptions.RedisError:
            raise DependencyUnavailable() from None
