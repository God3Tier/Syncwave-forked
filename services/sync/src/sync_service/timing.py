from dataclasses import dataclass
from enum import StrEnum


class CorrectionMethod(StrEnum):
    RATE = "RATE"
    SEEK = "SEEK"


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
    """Suppress correction chatter until drift settles or meaningfully escalates."""

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

        if (
            self.last_issued_at_ms is not None
            and now_ms - self.last_issued_at_ms < cooldown_ms
        ):
            return False

        if not self.active:
            if absolute_drift <= ignore_threshold_ms + hysteresis_ms:
                return False
        elif not (
            self.last_method is CorrectionMethod.RATE
            and correction.method is CorrectionMethod.SEEK
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
    return Correction(
        method=CorrectionMethod.RATE,
        drift_ms=drift_ms,
        target_position_ms=expected_position_at_apply_ms,
        playback_rate=playback_rate,
        apply_at_server_time_ms=apply_at_server_time_ms,
        duration_ms=3_000,
    )
