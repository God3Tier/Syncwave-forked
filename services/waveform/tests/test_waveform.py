import math
import shutil
import wave
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from waveform_service.shared.errors import PermanentError
from waveform_service.shared.waveform import (
    Bands,
    compute_bands,
    compute_peaks,
    decode,
    downsample,
    duration_ms,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def test_one_peak_per_slice_normalised_to_full_scale() -> None:
    samples = np.array([0, 16384, -32768, 8192, 0, 0, 100, -100], dtype=np.int16)
    assert compute_peaks(samples, 4) == [0.5, 1.0, 0.0, 0.003]


def test_uneven_slices_still_cover_every_sample() -> None:
    samples = np.zeros(10, dtype=np.int16)
    samples[-1] = 32767
    peaks = compute_peaks(samples, 3)
    assert peaks == [0.0, 0.0, 1.0]


def test_fewer_samples_than_points_gives_one_peak_per_sample() -> None:
    assert compute_peaks(np.array([16384, -8192], dtype=np.int16), 1000) == [0.5, 0.25]


def test_silence_is_flat() -> None:
    assert compute_peaks(np.zeros(8000, dtype=np.int16), 100) == [0.0] * 100


def test_empty_audio_is_a_permanent_failure() -> None:
    empty = np.array([], dtype=np.int16)
    with pytest.raises(PermanentError) as caught:
        compute_peaks(empty, 100)
    assert caught.value.code == "AUDIO_EMPTY"
    with pytest.raises(PermanentError) as caught:
        compute_bands(empty, RATE, frame_rate=25, band_count=50)
    assert caught.value.code == "AUDIO_EMPTY"


def test_downsample_keeps_the_loudest_peak_of_each_group() -> None:
    peaks = [0.1, 0.9, 0.2, 0.3, 0.8, 0.0]
    assert downsample(peaks, 3) == [0.9, 0.3, 0.8]
    assert downsample(peaks, 2) == [0.9, 0.8]
    assert downsample(peaks, 1) == [0.9]
    assert downsample(peaks, 6) == peaks
    assert downsample(peaks, 100) == peaks


def test_duration() -> None:
    assert duration_ms(np.zeros(16000, dtype=np.int16), 8000) == 2000
    assert duration_ms(np.zeros(12, dtype=np.int16), 8000) == 2


RATE = 22050


def tone(hz: float, seconds: float, amplitude: float = 0.5) -> np.ndarray:
    time = np.arange(round(seconds * RATE)) / RATE
    return (np.sin(2 * np.pi * hz * time) * amplitude * 32767).astype(np.int16)


def bands_of(samples: np.ndarray) -> Bands:
    return compute_bands(samples, RATE, frame_rate=25, band_count=50)


def grid(bands: Bands) -> np.ndarray:
    """The levels as one row per frame and one column per band."""
    return np.frombuffer(bands.levels, dtype=np.uint8).reshape(bands.frame_count, -1)


def band_containing(bands: Bands, hz: float) -> int:
    return next(i for i, (low, high) in enumerate(pairwise(bands.edges_hz)) if low <= hz < high)


def test_bands_have_one_frame_per_40_ms_and_log_spaced_edges() -> None:
    bands = bands_of(tone(1000, 1.0))

    assert bands.frame_rate == 25.0
    assert (bands.frame_count, bands.band_count) == (25, 50)
    assert len(bands.levels) == 25 * 50
    assert (bands.edges_hz[0], bands.edges_hz[-1]) == (50.0, 11025.0)
    ratios = [high / low for low, high in pairwise(bands.edges_hz)]
    assert max(ratios) - min(ratios) < 0.01  # every band spans the same fraction of an octave


@pytest.mark.parametrize("band", [18, 31, 45])  # about 370 Hz, 1.5 kHz and 6.8 kHz
def test_a_tone_lights_up_its_own_band(band: int) -> None:
    edges = bands_of(tone(1000, 0.1)).edges_hz
    centres = [math.sqrt(low * high) for low, high in pairwise(edges)]

    middle = grid(bands_of(tone(centres[band], 1.0)))[5:20]

    assert (middle.argmax(axis=1) == band).all()
    assert middle[:, band].min() >= 250
    # Bands more than an octave away from the tone stay quiet.
    far = [b for b, hz in enumerate(centres) if not centres[band] / 2 <= hz <= centres[band] * 2]
    assert middle[:, far].max() < 20


@pytest.mark.parametrize("hz", [60.0, 75.0, 90.0])
def test_bass_tones_peak_at_their_own_frequency(hz: float) -> None:
    # Bass bands are narrower than one FFT bin (10.8 Hz), so a tone spreads
    # over a few of them; the loudest is still its own band or a neighbour.
    bands = bands_of(tone(hz, 1.0))

    loudest = grid(bands)[5:20].argmax(axis=1)

    assert (abs(loudest - band_containing(bands, hz)) <= 1).all()


def test_band_levels_follow_the_music_over_time() -> None:
    samples = np.concatenate([np.zeros(RATE // 2, dtype=np.int16), tone(1000, 0.5)])
    bands = bands_of(samples)
    levels = grid(bands)

    # Frames up to 400 ms see audio up to 446 ms at most (half a window ahead).
    assert levels[:11].max() == 0
    assert levels[14:, band_containing(bands, 1000)].min() >= 200


def test_silence_has_no_band_levels() -> None:
    assert bands_of(np.zeros(RATE, dtype=np.int16)).levels == bytes(25 * 50)


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(samples.astype("<i2").tobytes())


@needs_ffmpeg
def test_decodes_to_mono_pcm_at_the_requested_rate(tmp_path: Path) -> None:
    rate = 44100
    seconds = np.arange(rate) / rate
    tone = (np.sin(2 * np.pi * 440 * seconds) * 16384).astype(np.int16)
    write_wav(tmp_path / "tone.wav", np.concatenate([tone, np.zeros(rate, np.int16)]), rate)

    samples = decode(str(tmp_path / "tone.wav"), sample_rate=8000, timeout_s=30)

    assert abs(samples.size - 16000) <= 16  # 2 s at 8 kHz
    loud, quiet = compute_peaks(samples, 2)
    assert 0.45 <= loud <= 0.55
    assert quiet < 0.1


@needs_ffmpeg
def test_undecodable_audio_is_a_permanent_failure(tmp_path: Path) -> None:
    path = tmp_path / "not-audio.mp3"
    path.write_bytes(b"this is not audio")

    with pytest.raises(PermanentError) as caught:
        decode(str(path), sample_rate=8000, timeout_s=30)

    assert caught.value.code == "AUDIO_UNDECODABLE"
