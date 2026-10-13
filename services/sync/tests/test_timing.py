from sync_service.timing import (
    CorrectionGate,
    CorrectionMethod,
    choose_correction,
    expected_position_ms,
)


def test_expected_position_uses_timeline_anchor() -> None:
    assert (
        expected_position_ms(
            anchor_server_time_ms=10_000,
            anchor_position_ms=2_000,
            playback_rate=1.0,
            measured_server_time_ms=13_500,
        )
        == 5_500
    )


def test_small_drift_is_ignored() -> None:
    assert (
        choose_correction(
            drift_ms=80,
            expected_position_at_apply_ms=5_000,
            apply_at_server_time_ms=15_000,
            ignore_threshold_ms=80,
            seek_threshold_ms=250,
            rate_correction_percent=0.02,
        )
        is None
    )


def test_medium_drift_uses_rate_correction() -> None:
    correction = choose_correction(
        drift_ms=-150,
        expected_position_at_apply_ms=5_000,
        apply_at_server_time_ms=15_000,
        ignore_threshold_ms=80,
        seek_threshold_ms=250,
        rate_correction_percent=0.02,
    )
    assert correction is not None
    assert correction.method is CorrectionMethod.RATE
    assert correction.playback_rate == 1.02


def test_large_drift_uses_scheduled_seek() -> None:
    correction = choose_correction(
        drift_ms=400,
        expected_position_at_apply_ms=5_000,
        apply_at_server_time_ms=15_000,
        ignore_threshold_ms=80,
        seek_threshold_ms=250,
        rate_correction_percent=0.02,
    )
    assert correction is not None
    assert correction.method is CorrectionMethod.SEEK
    assert correction.target_position_ms == 5_000


def test_correction_gate_uses_hysteresis_before_first_correction() -> None:
    gate = CorrectionGate()
    correction = choose_correction(
        drift_ms=90,
        expected_position_at_apply_ms=5_000,
        apply_at_server_time_ms=15_000,
        ignore_threshold_ms=80,
        seek_threshold_ms=250,
        rate_correction_percent=0.02,
    )

    assert correction is not None
    assert not gate.should_issue(
        correction,
        drift_ms=90,
        now_ms=10_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )


def test_correction_gate_suppresses_repeats_but_allows_rate_to_seek_escalation() -> None:
    gate = CorrectionGate()
    rate = choose_correction(
        drift_ms=150,
        expected_position_at_apply_ms=5_000,
        apply_at_server_time_ms=15_000,
        ignore_threshold_ms=80,
        seek_threshold_ms=250,
        rate_correction_percent=0.02,
    )
    seek = choose_correction(
        drift_ms=400,
        expected_position_at_apply_ms=8_000,
        apply_at_server_time_ms=18_000,
        ignore_threshold_ms=80,
        seek_threshold_ms=250,
        rate_correction_percent=0.02,
    )

    assert rate is not None
    assert seek is not None
    assert gate.should_issue(
        rate,
        drift_ms=150,
        now_ms=10_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )
    assert not gate.should_issue(
        seek,
        drift_ms=400,
        now_ms=11_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )
    assert gate.should_issue(
        seek,
        drift_ms=400,
        now_ms=13_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )
    assert not gate.should_issue(
        seek,
        drift_ms=400,
        now_ms=17_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )


def test_correction_gate_rearms_after_drift_returns_to_tolerance() -> None:
    gate = CorrectionGate()
    correction = choose_correction(
        drift_ms=-150,
        expected_position_at_apply_ms=5_000,
        apply_at_server_time_ms=15_000,
        ignore_threshold_ms=80,
        seek_threshold_ms=250,
        rate_correction_percent=0.02,
    )
    assert correction is not None
    assert gate.should_issue(
        correction,
        drift_ms=-150,
        now_ms=10_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )
    assert not gate.should_issue(
        None,
        drift_ms=40,
        now_ms=11_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )
    assert gate.should_issue(
        correction,
        drift_ms=-150,
        now_ms=13_000,
        ignore_threshold_ms=80,
        hysteresis_ms=20,
        cooldown_ms=3_000,
    )
