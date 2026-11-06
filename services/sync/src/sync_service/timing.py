from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from statistics import median


class CorrectionMethod(StrEnum):
    RATE = "RATE"
    SEEK = "SEEK"


@dataclass(frozen=True, slots=True)
class ClockSample:
    sampled_at_ms: int
    offset_ms: float
    round_trip_delay_ms: float


def clock_sample(
    *,
    client_sent_ms: int,
    server_received_ms: int,
    server_sent_ms: int,
    client_received_ms: int,
) -> ClockSample:
    """Calculate the standard four-timestamp NTP offset and network delay."""
    return ClockSample(
        sampled_at_ms=client_received_ms,
        offset_ms=((server_received_ms - client_sent_ms) + (server_sent_ms - client_received_ms))
        / 2,
        round_trip_delay_ms=max(
            0,
            (client_received_ms - client_sent_ms) - (server_sent_ms - server_received_ms),
        ),
    )


def select_clock_estimate(
    samples: list[ClockSample],
    *,
    now_ms: int,
    max_age_ms: int,
    best_sample_count: int = 5,
) -> tuple[float, float] | None:
    """Select low-delay recent samples and reject offset outliers using MAD."""
    recent = [sample for sample in samples if now_ms - sample.sampled_at_ms <= max_age_ms]
    if not recent:
        return None
    candidates = sorted(recent, key=lambda sample: sample.round_trip_delay_ms)[:best_sample_count]
    center = median(sample.offset_ms for sample in candidates)
    mad = median(abs(sample.offset_ms - center) for sample in candidates)
    tolerance = max(10.0, 3 * mad)
    accepted = [sample for sample in candidates if abs(sample.offset_ms - center) <= tolerance]
    return (
        float(median(sample.offset_ms for sample in accepted)),
        float(median(sample.round_trip_delay_ms for sample in accepted)),
    )


@dataclass(frozen=True, slots=True)
class Correction:
    method: CorrectionMethod
    drift_ms: int
    target_position_ms: int
    playback_rate: float
    apply_at_server_time_ms: int
    duration_ms: int | None = None


@dataclass(slots=True)
class CorrectionGate:
    """Suppress correction chatter while allowing persistent seek drift to recover."""

    active: bool = False
    last_method: CorrectionMethod | None = None
    last_issued_at_ms: int | None = None

    def reset(self) -> None:
        self.active = False
        self.last_method = None
        self.last_issued_at_ms = None

    def should_issue(
        self,
        correction: Correction | None,
        *,
        drift_ms: int,
        now_ms: int,
        ignore_threshold_ms: int,
        hysteresis_ms: int,
        cooldown_ms: int,
    ) -> bool:
        absolute_drift = abs(drift_ms)
        if absolute_drift <= ignore_threshold_ms:
            self.active = False
            self.last_method = None
            return False

        if correction is None:
            return False

        if self.last_issued_at_ms is not None and now_ms - self.last_issued_at_ms < cooldown_ms:
            return False

        if not self.active:
            if absolute_drift <= ignore_threshold_ms + hysteresis_ms:
                return False
        elif not (
            (
                self.last_method is CorrectionMethod.RATE
                and correction.method is CorrectionMethod.SEEK
            )
            or (
                self.last_method is CorrectionMethod.SEEK
                and correction.method is CorrectionMethod.SEEK
            )
        ):
            return False

        self.active = True
        self.last_method = correction.method
        self.last_issued_at_ms = now_ms
        return True


def expected_position_ms(
    *,
    anchor_server_time_ms: int,
    anchor_position_ms: int,
    playback_rate: float,
    measured_server_time_ms: int,
) -> int:
    elapsed_ms = max(0, measured_server_time_ms - anchor_server_time_ms)
    return anchor_position_ms + round(elapsed_ms * playback_rate)


def choose_correction(
    *,
    drift_ms: int,
    expected_position_at_apply_ms: int,
    apply_at_server_time_ms: int,
    ignore_threshold_ms: int,
    seek_threshold_ms: int,
    rate_correction_percent: float,
) -> Correction | None:
    absolute_drift = abs(drift_ms)
    if absolute_drift <= ignore_threshold_ms:
        return None

    if absolute_drift > seek_threshold_ms:
        return Correction(
            method=CorrectionMethod.SEEK,
            drift_ms=drift_ms,
            target_position_ms=expected_position_at_apply_ms,
            playback_rate=1.0,
            apply_at_server_time_ms=apply_at_server_time_ms,
        )

    # A client ahead of the timeline slows down; a client behind speeds up.
    playback_rate = 1.0 - rate_correction_percent if drift_ms > 0 else 1.0 + rate_correction_percent
    duration_ms = min(
        10_000,
        max(1_000, ceil((absolute_drift - ignore_threshold_ms) / rate_correction_percent)),
    )
    return Correction(
        method=CorrectionMethod.RATE,
        drift_ms=drift_ms,
        target_position_ms=expected_position_at_apply_ms,
        playback_rate=playback_rate,
        apply_at_server_time_ms=apply_at_server_time_ms,
        duration_ms=duration_ms,
    )
