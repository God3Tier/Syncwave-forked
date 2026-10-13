import json
import logging
import re
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import uuid4

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

_CORRELATION_ID = ContextVar("correlation_id", default="")
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def correlation_id(value: str | None = None) -> str:
    if value and _SAFE_CORRELATION_ID.fullmatch(value):
        return value
    return uuid4().hex


def bind_correlation_id(value: str | None = None) -> tuple[str, Token[str]]:
    selected = correlation_id(value)
    return selected, _CORRELATION_ID.set(selected)


def reset_correlation_id(token: Token[str]) -> None:
    _CORRELATION_ID.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": "sync",
            "event": record.getMessage(),
        }
        current_correlation_id = _CORRELATION_ID.get()
        if current_correlation_id:
            document["correlation_id"] = current_correlation_id
        for key in (
            "transport",
            "jam_id",
            "participant_id",
            "connection_id",
            "generation",
            "request_id",
            "message_type",
            "outcome",
            "duration_ms",
            "error_code",
            "drift_ms",
            "method",
        ):
            value = getattr(record, key, None)
            if value is not None:
                document[key] = value
        return json.dumps(document, separators=(",", ":"), default=str)


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("sync_service")
    logger.setLevel(level.upper())
    if not any(getattr(handler, "sync_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.sync_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = configure_logging("INFO")


def log_event(event: str, **context: object) -> None:
    logger.info(event, extra=context)


@dataclass(slots=True)
class Metrics:
    registry: CollectorRegistry
    websocket_connections: Gauge
    ready_participants: Gauge
    clock_offset_ms: Histogram
    round_trip_delay_ms: Histogram
    prepare_duration_ms: Histogram
    start_error_ms: Histogram
    drift_ms: Histogram
    corrections_total: Counter
    dependency_duration_ms: Histogram
    protocol_errors_total: Counter

    @classmethod
    def create(cls) -> "Metrics":
        registry = CollectorRegistry()
        return cls(
            registry=registry,
            websocket_connections=Gauge(
                "sync_websocket_connections",
                "Currently connected Sync WebSocket clients.",
                registry=registry,
            ),
            ready_participants=Gauge(
                "sync_ready_participants",
                "Participants ready for the current generation.",
                registry=registry,
            ),
            clock_offset_ms=Histogram(
                "sync_clock_offset_ms",
                "Reported browser-to-server clock offset in milliseconds.",
                buckets=(-1000, -500, -250, -100, -50, -10, 0, 10, 50, 100, 250, 500, 1000),
                registry=registry,
            ),
            round_trip_delay_ms=Histogram(
                "sync_round_trip_delay_ms",
                "Browser clock sample round-trip delay in milliseconds.",
                registry=registry,
            ),
            prepare_duration_ms=Histogram(
                "sync_prepare_duration_ms",
                "Time from prepare creation until playback scheduling.",
                registry=registry,
            ),
            start_error_ms=Histogram(
                "sync_start_error_ms",
                "Absolute browser playback start error in milliseconds.",
                registry=registry,
            ),
            drift_ms=Histogram(
                "sync_drift_ms",
                "Absolute playback drift in milliseconds.",
                registry=registry,
            ),
            corrections_total=Counter(
                "sync_corrections_total",
                "Sync corrections issued.",
                ("method", "reason"),
                registry=registry,
            ),
            dependency_duration_ms=Histogram(
                "sync_dependency_duration_ms",
                "Dependency operation latency.",
                ("service", "method", "status"),
                registry=registry,
            ),
            protocol_errors_total=Counter(
                "sync_protocol_errors_total",
                "Rejected protocol messages.",
                ("code",),
                registry=registry,
            ),
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


metrics = Metrics.create()


class OperationTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1_000, 3)
