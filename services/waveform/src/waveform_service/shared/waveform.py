"""Waveform generation: decode the audio, then reduce it to

- peaks: the loudest sample in each equal-length slice of the song, as a
  fraction of full scale (0..1). The browser draws one bar per peak, e.g. as
  the seek bar.
- bands: how loud each frequency band is, frame by frame. The browser
  animates these in time with playback, like the bars in a lyrics video.
"""

import math
import subprocess
from dataclasses import dataclass

import numpy as np

from waveform_service.shared.errors import PermanentError, TransientError

FULL_SCALE = 32768.0  # 16-bit signed PCM

LOWEST_BAND_HZ = 50.0
# Most music has less energy in the treble; tilting the levels up per octave
# (down below 1 kHz) keeps the treble bars moving instead of near the floor.
TILT_DB_PER_OCTAVE = 3.0
# A level of 0 is this far below the song's loudest moments.
DYNAMIC_RANGE_DB = 48.0
# Quieter than this (dB below full scale) counts as silence, whatever the song.
NOISE_FLOOR_DB = -90.0
# Frames transformed at once, which bounds memory on long songs.
CHUNK_FRAMES = 512


@dataclass(frozen=True, slots=True)
class Bands:
    """Frequency-band levels over time, for a visualiser.

    `levels` holds one byte per band per frame, frame after frame, lowest band
    first: 0 is silent and 255 the song's loudest. Frame i is centred on
    i / frame_rate seconds into the song.
    """

    frame_rate: float
    edges_hz: list[float]  # band_count + 1 band edges, low to high
    levels: bytes

    @property
    def band_count(self) -> int:
        return len(self.edges_hz) - 1

    @property
    def frame_count(self) -> int:
        return len(self.levels) // self.band_count


def decode(path: str, *, sample_rate: int, timeout_s: float) -> np.ndarray:
    """Decodes any format ffmpeg understands to mono 16-bit PCM at `sample_rate`.

    The bands go up to half the sample rate, so 22.05 kHz keeps everything up
    to 11 kHz; 10 minutes of audio is then about 26 MB in memory.
    """
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
        "-i", path,
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1",
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TransientError(
            "DECODE_TIMEOUT", f"decoding took longer than {timeout_s:g} s"
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()[-300:]
        raise PermanentError(
            "AUDIO_UNDECODABLE",
            f"ffmpeg could not decode the audio: {detail or f'exit code {result.returncode}'}",
        )
    return np.frombuffer(result.stdout, dtype="<i2")


def compute_peaks(samples: np.ndarray, points: int) -> list[float]:
    """`points` peaks (fewer if there are fewer samples), rounded to 3 decimals."""
    _require_samples(samples)
    # int32 first: abs(-32768) does not fit in int16
    return _max_per_slice(np.abs(samples.astype(np.int32)), points, scale=FULL_SCALE)


def compute_bands(
    samples: np.ndarray, sample_rate: int, *, frame_rate: float, band_count: int
) -> Bands:
    """Levels of `band_count` log-spaced frequency bands, `frame_rate` times a second.

    Each frame is the Hann-windowed power spectrum of about two frames' worth
    of audio centred on the frame's time. A band's power is the spectrum's
    integral over the band, with the spectrum interpolated linearly between
    FFT bins: bass bands narrower than one bin then still move on their own
    instead of copying their neighbours. Band power in dB is tilted by
    TILT_DB_PER_OCTAVE, then scaled so the song's loudest moments are 255
    and DYNAMIC_RANGE_DB below them is 0.
    """
    _require_samples(samples)
    hop = max(1, round(sample_rate / frame_rate))
    window = 1 << max(1, math.ceil(math.log2(2 * hop)))
    nyquist = sample_rate / 2
    edges = np.geomspace(min(LOWEST_BAND_HZ, nyquist / 4), nyquist, band_count + 1)

    # Where each band edge falls between two FFT bins.
    bins = window // 2 + 1
    position = edges / (sample_rate / window)
    below = np.minimum(position.astype(int), bins - 2)
    past = position - below

    # Frame i is centred on sample i * hop: pad half a window of silence at the start.
    frame_count = math.ceil(samples.size / hop)
    padded = np.zeros(frame_count * hop + window, dtype=np.int16)
    padded[window // 2 : window // 2 + samples.size] = samples
    frames = np.lib.stride_tricks.sliding_window_view(padded, window)[::hop][:frame_count]
    taper = np.hanning(window + 1)[:-1].astype(np.float32)  # periodic Hann
    # Power of the strongest bin for a full-scale sine: that is 0 dB.
    full_scale_power = (taper.sum() / 2 * FULL_SCALE) ** 2

    power = np.empty((frame_count, band_count))
    for first in range(0, frame_count, CHUNK_FRAMES):
        chunk = frames[first : first + CHUNK_FRAMES] * taper
        spectrum = np.abs(np.fft.rfft(chunk, axis=1)) ** 2
        # Integral of the spectrum from 0 Hz up to each bin, then up to each edge.
        up_to_bin = np.zeros((len(chunk), bins))
        np.cumsum((spectrum[:, :-1] + spectrum[:, 1:]) / 2, axis=1, out=up_to_bin[:, 1:])
        low, high = spectrum[:, below], spectrum[:, below + 1]
        up_to_edge = up_to_bin[:, below] + low * past + (high - low) * past**2 / 2
        power[first : first + len(chunk)] = np.diff(up_to_edge, axis=1)

    centres = np.sqrt(edges[:-1] * edges[1:])
    decibels = 10 * np.log10(np.maximum(power, 0) / full_scale_power + 1e-20)
    decibels += TILT_DB_PER_OCTAVE * np.log2(centres / 1000)
    loudest = float(np.percentile(decibels, 99.5))
    floor = max(loudest - DYNAMIC_RANGE_DB, NOISE_FLOOR_DB)
    if loudest > floor:
        scaled = np.clip((decibels - floor) / (loudest - floor), 0, 1)
    else:
        scaled = np.zeros_like(decibels)  # silence
    return Bands(
        frame_rate=sample_rate / hop,
        edges_hz=[round(float(edge), 1) for edge in edges],
        levels=np.round(scaled * 255).astype(np.uint8).tobytes(),
    )


def downsample(peaks: list[float], points: int) -> list[float]:
    """Fewer peaks for a narrower display; each is the maximum of the peaks it covers."""
    if points >= len(peaks):
        return peaks
    return _max_per_slice(np.asarray(peaks, dtype=np.float64), points)


def duration_ms(samples: np.ndarray, sample_rate: int) -> int:
    return round(samples.size * 1000 / sample_rate)


def _require_samples(samples: np.ndarray) -> None:
    if samples.size == 0:
        raise PermanentError("AUDIO_EMPTY", "the audio contains no samples")


def _max_per_slice(values: np.ndarray, points: int, scale: float = 1.0) -> list[float]:
    count = min(points, values.size)
    starts = np.arange(count) * values.size // count
    peaks = np.maximum.reduceat(values, starts) / scale
    return np.round(np.minimum(peaks, 1.0), 3).tolist()
