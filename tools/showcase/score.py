"""Synthesize the showcase's original, sample-free instrumental score.

This is an offline delivery asset. It is not a Minecraft audio integration.
All oscillators, envelopes and noise below are generated locally; no music or
third-party samples are downloaded or embedded.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave

import numpy as np


def frequency(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def _smooth(value: np.ndarray) -> np.ndarray:
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def compose(duration: float = 41.0, sample_rate: int = 48000) -> np.ndarray:
    """Return deterministic stereo float32 samples, with headroom and no clips."""
    if not math.isfinite(duration) or not 1 <= duration <= 300:
        raise ValueError("Score duration must be in [1, 300] seconds")
    if not 8000 <= sample_rate <= 192000:
        raise ValueError("Unsupported sample rate")
    count = round(duration * sample_rate)
    mix = np.zeros((count, 2), dtype=np.float32)
    random = np.random.default_rng(20261110)

    def add(start, signal, gain=1.0, pan=0.0):
        offset = round(start * sample_rate)
        if offset >= count:
            return
        skip = max(0, -offset)
        offset = max(0, offset)
        length = min(len(signal) - skip, count - offset)
        if length <= 0:
            return
        pan = np.clip(pan, -1.0, 1.0)
        left = math.sqrt((1.0 - pan) / 2.0)
        right = math.sqrt((1.0 + pan) / 2.0)
        values = signal[skip:skip + length] * gain
        mix[offset:offset + length, 0] += values * left
        mix[offset:offset + length, 1] += values * right

    def clock(seconds):
        return np.arange(round(seconds * sample_rate), dtype=np.float32) / sample_rate

    # Soft D-minor/add9 progression, changing with the five visual chapters.
    chords = [
        (0.0, 6.7, (50, 57, 60, 64, 69), 0.11),
        (5.0, 5.8, (46, 53, 57, 60, 65), 0.12),
        (9.0, 5.7, (48, 55, 59, 62, 67), 0.12),
        (13.0, 7.5, (50, 57, 60, 64, 69), 0.12),
        (19.0, 6.7, (53, 60, 64, 67, 72), 0.13),
        (24.0, 6.8, (46, 53, 57, 60, 65), 0.15),
        (29.0, 5.8, (48, 55, 59, 62, 67), 0.15),
        (33.0, 8.0, (50, 57, 62, 64, 69), 0.14),
    ]
    for chord_index, (start, length, notes, level) in enumerate(chords):
        t = clock(length)
        envelope = _smooth(t / 1.4) * _smooth((length - t) / 2.4)
        for index, note in enumerate(notes):
            f = frequency(note)
            # Gentle detune and low partial levels keep the pad warm and quiet.
            voice = (np.sin(2 * np.pi * f * t + index * 0.7)
                     + 0.28 * np.sin(2 * np.pi * f * 1.002 * t + 0.8)
                     + 0.11 * np.sin(2 * np.pi * f * 2 * t))
            voice *= envelope * (0.94 + 0.06 * np.sin(t * 1.1 + index))
            add(start, voice, level / len(notes), (index - 2) * 0.28)

    def bell(start, note, gain=0.12, pan=0.0, length=3.2):
        t = clock(length)
        f = frequency(note)
        attack = _smooth(t / 0.012)
        voice = (np.sin(2 * np.pi * f * t) * np.exp(-t * 1.3)
                 + 0.34 * np.sin(2 * np.pi * f * 2.001 * t) * np.exp(-t * 2.1)
                 + 0.10 * np.sin(2 * np.pi * f * 3.997 * t) * np.exp(-t * 4.0))
        voice *= attack * _smooth((length - t) / 0.3)
        add(start, voice, gain, pan)

    # A sparse opening motif gradually develops into an eighth-note arpeggio.
    for start, note, pan in [(0.5, 74, -0.3), (1.7, 81, 0.3), (3.0, 77, -0.1),
                             (5.1, 74, 0.2), (6.35, 77, -0.35), (7.6, 81, 0.35),
                             (9.15, 79, -0.3), (10.4, 74, 0.3), (11.65, 76, 0.0)]:
        bell(start, note, 0.13, pan)
    step = 0.3125  # 96 BPM, eighth-note movement.
    motif = [74, 81, 77, 84, 81, 77, 76, 72]
    for index, start in enumerate(np.arange(13.0, 32.7, step)):
        # Deliberate rests make room for the visual transformations.
        if index % 8 in (3, 7) and start < 24:
            continue
        note = motif[index % len(motif)]
        if 19 <= start < 24:
            note += 3
        elif 24 <= start < 29:
            note -= 4
        elif start >= 29:
            note -= 2
        gain = 0.075 if start < 24 else 0.10
        bell(float(start), note, gain, math.sin(index * 1.7) * 0.55, 2.3)
    for start, note, gain in [(33.05, 74, 0.17), (33.075, 81, 0.10),
                              (34.3, 77, 0.11), (35.55, 76, 0.10),
                              (36.8, 74, 0.13), (38.05, 86, 0.065)]:
        bell(start, note, gain, (note - 79) * 0.055, 4.0)

    # Restrained low pulses support the geometric climax without drowning text.
    for index, start in enumerate(np.arange(13.0, 33.0, 0.625)):
        t = clock(0.6)
        phase = 2 * np.pi * (43.0 * t + 26.0 * (1.0 - np.exp(-18.0 * t)) / 18.0)
        pulse = np.sin(phase) * np.exp(-7.0 * t) * _smooth(t / 0.008)
        pulse *= _smooth((0.6 - t) / 0.1)
        add(float(start), pulse, 0.07 if start < 24 else 0.10)
        if start >= 24 and index % 2 == 1:
            t = clock(0.13)
            noise = random.standard_normal(len(t)).astype(np.float32)
            noise = np.concatenate((noise[:1], np.diff(noise)))
            noise *= np.exp(-t * 36) * _smooth(t / 0.004) * _smooth((0.13 - t) / 0.03)
            add(float(start), noise, 0.007, -0.2)

    # Subtle swells anticipate chapter changes; all are generated filtered noise.
    for transition in (5.0, 13.0, 24.0, 33.0):
        length = 1.7
        t = clock(length)
        noise = random.standard_normal(len(t)).astype(np.float32)
        kernel = np.ones(33, dtype=np.float32) / 33
        low = np.convolve(noise, kernel, mode="same")
        envelope = _smooth(t / 1.3) * _smooth((length - t) / 0.12)
        add(transition - 1.5, low * envelope, 0.07, 0.0)

    # A few quiet crossed taps create depth without a giant convolution asset.
    dry = mix.copy()
    for delay, gain in ((0.19, 0.18), (0.31, 0.13), (0.47, 0.085), (0.73, 0.045)):
        offset = round(delay * sample_rate)
        if offset < count:
            mix[offset:] += dry[:-offset, ::-1] * gain
    timeline = np.arange(count, dtype=np.float32) / sample_rate
    mix *= (_smooth(timeline / 0.7) * _smooth((duration - timeline) / 2.8))[:, None]
    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        # Moderate soft saturation and comfortable presentation headroom.
        # The 41-second master measures about -15.6 LUFS / -4 dBTP.
        mix = np.tanh(mix * (0.9 / peak)).astype(np.float32)
        mix *= np.float32(10 ** (-4.0 / 20.0) / np.max(np.abs(mix)))
    return mix


def write_score(path: Path, duration: float = 41.0, sample_rate: int = 48000) -> dict:
    samples = compose(duration, sample_rate)
    pcm = np.rint(samples * 32767).astype("<i2")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm.tobytes())
    return {
        "path": str(path.resolve()), "sample_rate": sample_rate, "channels": 2,
        "duration": len(samples) / sample_rate,
        "peak_dbfs": 20 * math.log10(max(float(np.max(np.abs(samples))), 1e-12)),
        "rms_dbfs": 20 * math.log10(max(float(np.sqrt(np.mean(samples ** 2))), 1e-12)),
        "original_synthesis": True, "external_samples": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=41.0)
    parser.add_argument("--sample-rate", type=int, default=48000)
    args = parser.parse_args()
    print(json.dumps(write_score(args.output, args.duration, args.sample_rate), indent=2))


if __name__ == "__main__":
    main()
