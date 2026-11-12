"""In-process reference state. This is not a public API or persistent cache."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import math
import re
import time
from typing import Callable

from .adapters import SOURCE_REFS, SampleError, project


def utc_time(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        raise ValueError("UTC Z timestamp required")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CachePolicy:
    # These are local display thresholds, not a claim about provider update rates.
    fresh_for_seconds: int = 300
    retain_for_seconds: int = 0
    permission_ref: str | None = None

    def __post_init__(self):
        if any(type(n) is not int or not 0 <= n <= 31 * 86400 for n in
               (self.fresh_for_seconds, self.retain_for_seconds)):
            raise ValueError("integer cache thresholds must be within 0..31 days")
        if self.retain_for_seconds and not (isinstance(self.permission_ref, str)
                                            and self.permission_ref.strip()):
            raise ValueError("cache retention requires separate permission evidence")


@dataclass(frozen=True)
class SampleResponse:
    raw: bytes
    received_at: str
    http_status: int = 200


class ReferenceReader:
    """One source, direction and explicit mode per instance; no mock fallback.

    The caller must have permission to read its local sample. A permission_ref
    records that assertion, not an independent legal/operational verification.
    Cache permission is separate and disabled by default. No raw bytes are held.
    Instances are single-owner/synchronous; no background jobs or shared server.
    """

    def __init__(self, source: str, *, kind: str, sample_permission_ref: str,
                 policy: CachePolicy | None = None, direction: tuple[str, str] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if source not in SOURCE_REFS or kind not in ("reference", "simulated"):
            raise ValueError("unsupported source or explicit sample kind")
        if not isinstance(sample_permission_ref, str) or not sample_permission_ref.strip():
            raise ValueError("sample read permission evidence required")
        if source == "road" and (not isinstance(direction, tuple) or len(direction) != 2
                                 or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{3}", v)
                                        for v in direction)):
            raise ValueError("road source requires an explicit directed unit pair")
        if source != "road" and direction is not None:
            raise ValueError("direction applies only to road samples")
        self.source, self.kind, self.direction = source, kind, direction
        self.policy = policy or CachePolicy()
        self.sample_permission_ref = sample_permission_ref
        self.clock = clock
        self._last_attempt = None
        self._last_success = None
        self._cache = None
        self._last_clock = None

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must be timezone aware")
        now = now.astimezone(timezone.utc)
        if self._last_clock is not None and now < self._last_clock:
            raise ValueError("clock moved backwards")
        self._last_clock = now
        if self._cache is not None and now >= utc_time(self._cache["received_at"]) + timedelta(
                seconds=self.policy.retain_for_seconds):
            self._cache = None
        return now

    def _freshness(self, received_at: str, now: datetime) -> str:
        return "fresh" if now < utc_time(received_at) + timedelta(
            seconds=self.policy.fresh_for_seconds) else "stale"

    def _view(self, now: datetime, current: dict | None = None) -> dict:
        cached = deepcopy(self._cache)
        for item in (current, cached):
            if item is not None:
                item["freshness"] = self._freshness(item["received_at"], now)
        return deepcopy({"model_version": "reference-read-preview-1",
                         "source": self.source, "source_ref": SOURCE_REFS[self.source],
                         "kind": self.kind, "checked_at": utc_text(now),
                         "sample_permission_ref": self.sample_permission_ref,
                         "cache_policy": asdict(self.policy),
                         "last_attempt": self._last_attempt, "last_success": self._last_success,
                         "current": current, "cached": cached,
                         "engine_conversion": "blocked", "approval_eligible": False,
                         "automatic_mock_fallback": False})

    def view(self) -> dict:
        return self._view(self._now())

    def _failure(self, code: str, now: datetime, attempts: int) -> dict:
        self._last_attempt = {"at": utc_text(now), "status": "failed",
                              "error_code": code, "attempts": attempts}
        return self._view(now)

    def ingest(self, response: SampleResponse, *, attempts: int = 1) -> dict:
        now = self._now()
        if not isinstance(response, SampleResponse):
            return self._failure("invalid_response", now, attempts)
        if type(response.http_status) is not int or not 100 <= response.http_status <= 599:
            return self._failure("invalid_http_status", now, attempts)
        if response.http_status != 200:
            return self._failure("http_error", now, attempts)
        try:
            received = utc_time(response.received_at)
        except (ValueError, TypeError):
            return self._failure("invalid_received_at", now, attempts)
        if received > now:
            return self._failure("future_received_at", now, attempts)
        if self._last_success is not None and received <= utc_time(self._last_success["received_at"]):
            return self._failure("out_of_order_sample", now, attempts)
        try:
            projection = project(self.source, response.raw, response.received_at,
                                 self.kind, self.direction)
        except SampleError as error:
            return self._failure(str(error), now, attempts)
        current = {**asdict(projection), "received_at": response.received_at,
                   "receipt_provenance": "caller_supplied_not_provider_observation_time"}
        # Successful parsing is distinct from complete coverage or engine readiness.
        self._last_success = {"received_at": response.received_at, "status": projection.status,
                              "row_count": projection.row_count, "item_count": len(projection.items)}
        self._last_attempt = {"at": utc_text(now), "status": projection.status,
                              "error_code": None, "attempts": attempts}
        if projection.status != "partial":
            # A known empty response replaces previous data; partial data cannot
            # erase a previously coherent sample. Failure never updates its age.
            self._cache = None
            if self.policy.retain_for_seconds and now < received + timedelta(
                    seconds=self.policy.retain_for_seconds):
                self._cache = deepcopy(current)
        return self._view(now, current)

    def refresh(self, loader: Callable[[], SampleResponse], *, max_attempts: int = 1,
                backoff_seconds: float = 0.25,
                sleeper: Callable[[float], None] = time.sleep) -> dict:
        """Injected transport only; caller must enforce its own request timeout.

        No provider transport is supplied or enabled. Future authorized transports
        may retry connection/timeout, 429 and selected 5xx at most three times.
        HTTP/provider auth errors, invalid/empty/partial payloads are not retried.
        """
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be 1..3")
        if (type(backoff_seconds) not in (int, float) or not math.isfinite(backoff_seconds)
                or not 0 <= backoff_seconds <= 1):
            raise ValueError("backoff_seconds must be 0..1")
        for attempt in range(1, max_attempts + 1):
            self._now()  # Reject clock problems before invoking a transport.
            try:
                response = loader()
            except (ConnectionError, TimeoutError):
                result = self._failure("transport_error", self._now(), attempt)
                retry = True
            except Exception:
                # Never expose a loader's URL, credentials or response body.
                return self._failure("loader_error", self._now(), attempt)
            else:
                if not isinstance(response, SampleResponse):
                    return self._failure("invalid_response", self._now(), attempt)
                result = self.ingest(response, attempts=attempt)
                retry = response.http_status in (429, 500, 502, 503, 504)
            if not retry or attempt == max_attempts:
                return result
            sleeper(min(backoff_seconds * 2 ** (attempt - 1), 1))
        raise AssertionError("unreachable")
