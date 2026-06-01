import time

from asuna.config import settings


class TokenBucket:
    def __init__(self, rate: float, capacity: float) -> None:
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max tokens
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self) -> bool:
        self._refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[TokenBucket, TokenBucket]] = {}

    def _get_buckets(self, user_id: str) -> tuple[TokenBucket, TokenBucket]:
        if user_id not in self._buckets:
            per_min = TokenBucket(
                rate=settings.RATE_LIMIT_PER_MINUTE / 60.0,
                capacity=settings.RATE_LIMIT_PER_MINUTE,
            )
            per_hour = TokenBucket(
                rate=settings.RATE_LIMIT_PER_HOUR / 3600.0,
                capacity=settings.RATE_LIMIT_PER_HOUR,
            )
            self._buckets[user_id] = (per_min, per_hour)
        return self._buckets[user_id]

    def check_and_acquire(self, user_id: str) -> bool:
        per_min, per_hour = self._get_buckets(user_id)
        if not per_min.acquire():
            return False
        if not per_hour.acquire():
            # Refund the per-minute token
            per_min.tokens = min(per_min.capacity, per_min.tokens + 1.0)
            return False
        return True

    def cleanup(self) -> None:
        """Remove stale entries periodically (optional)."""
        if len(self._buckets) > 10_000:
            self._buckets.clear()
