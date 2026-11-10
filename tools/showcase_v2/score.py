"""Original two-minute electronic/cinematic score; no imported music or samples.

Eight sections develop the harmony, pulse, register and instrumentation to
follow the visual film. This is not a loop of the earlier 41-second score.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave

import numpy as np


SECTIONS = (
    (0.0, 12.0, "awakening", 0.0),
    (12.0, 28.0, "geometry", 0.55),
    (28.0, 48.0, "algebra", 0.74),
    (48.0, 66.0, "orbits", 0.45),
    (66.0, 84.0, "calculus", 0.64),
    (84.0, 102.0, "harmonics", 0.86),
    (102.0, 114.0, "metamorphosis", 1.0),
    (114.0, 120.0, "resolution", 0.0),
)
BEAT = 0.5  # 120 BPM; all chapter boundaries fall on the grid.


def frequency(note):
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


def smooth(value):
    value = np.clip(value, 0.0, 1.0)
    return value * value * (3.0 - 2.0 * value)


def compose(duration=120.0, sample_rate=48000):
    if not math.isfinite(duration) or not 1 <= duration <= 300:
        raise ValueError("Duration must be finite and in [1, 300] seconds")
    if not isinstance(sample_rate, int) or not 8000 <= sample_rate <= 192000:
        raise ValueError("Sample rate must be an integer in [8000, 192000]")
    count = round(duration * sample_rate)
    mix = np.zeros((count, 2), dtype=np.float32)
    rng = np.random.default_rng(202611102)

    def clock(seconds):
        # Double precision phase avoids high-note stair-stepping on long pads.
        return np.arange(round(seconds * sample_rate), dtype=np.float64) / sample_rate

    def add(start, signal, gain=1.0, pan=0.0):
        offset = round(start * sample_rate)
        skip = max(0, -offset)
        offset = max(0, offset)
        length = min(len(signal) - skip, count - offset)
        if length <= 0:
            return
        pan = min(1.0, max(-1.0, float(pan)))
        values = np.asarray(signal[skip:skip + length] * gain, dtype=np.float32)
        mix[offset:offset + length, 0] += values * math.sqrt((1 - pan) * 0.5)
        mix[offset:offset + length, 1] += values * math.sqrt((1 + pan) * 0.5)

    # D minor -> Bb major -> F -> C; inversions and suspended chords evolve
    # between chapters instead of repeating one four-bar rendered audio block.
    harmony = [
        (0, 6, (50, 57, 64, 69)), (6, 12, (46, 53, 60, 65)),
        (12, 16, (50, 57, 60, 64)), (16, 20, (46, 53, 57, 60)),
        (20, 24, (53, 60, 64, 67)), (24, 28, (48, 55, 59, 62)),
        (28, 32, (50, 57, 62, 65)), (32, 36, (46, 57, 60, 65)),
        (36, 40, (53, 60, 64, 69)), (40, 44, (48, 55, 62, 67)),
        (44, 48, (45, 52, 59, 64)),
        (48, 54, (50, 57, 64, 69)), (54, 60, (53, 60, 67, 72)),
        (60, 66, (48, 55, 62, 67)),
        (66, 70, (46, 53, 60, 65)), (70, 74, (48, 55, 62, 67)),
        (74, 78, (50, 57, 64, 69)), (78, 82, (53, 60, 67, 72)),
        (82, 84, (45, 52, 59, 64)),
        (84, 88, (50, 57, 60, 65)), (88, 92, (46, 53, 60, 65)),
        (92, 96, (53, 60, 64, 69)), (96, 100, (48, 55, 62, 67)),
        (100, 102, (45, 52, 61, 64)),
        (102, 106, (50, 57, 62, 65)), (106, 110, (46, 53, 60, 65)),
        (110, 112, (48, 55, 62, 67)), (112, 114, (45, 52, 61, 64)),
        (114, 120, (50, 57, 62, 64, 69)),
    ]

    def chord_at(start):
        for left, right, notes in harmony:
            if left <= start < right:
                return notes
        return harmony[-1][2]

    def intensity_at(start):
        for left, right, _, intensity in SECTIONS:
            if left <= start < right:
                return intensity
        return 0.0

    # Warm pad and restrained harmonic shimmer, with a little movement.
    for chord_index, (start, end, notes) in enumerate(harmony):
        if start >= duration:
            break
        length = end - start + 1.3
        t = clock(length)
        envelope = smooth(t / 0.8) * smooth((length - t) / 1.8)
        strength = 0.09 + 0.025 * intensity_at(start)
        for voice_index, note in enumerate(notes):
            f = frequency(note)
            phase = 2 * np.pi * f * t
            voice = (np.sin(phase + voice_index * 0.8)
                     + 0.35 * np.sin(phase * 1.0017 + 0.4)
                     + 0.13 * np.sin(phase * 2 + 0.3)
                     + 0.045 * np.sin(phase * 3))
            shimmer = 0.94 + 0.06 * np.sin(t * 0.8 + chord_index)
            add(start, voice * envelope * shimmer, strength / len(notes),
                (voice_index - (len(notes) - 1) * 0.5) * 0.3)

    def pluck(start, note, gain=0.12, pan=0.0, duration_note=1.6, soft=False):
        if start >= duration:
            return
        t = clock(duration_note)
        f = frequency(note)
        phase = 2 * np.pi * f * t
        # Low partial count avoids the shrill high-frequency bell of many demos.
        voice = (np.sin(phase) * np.exp(-t * 2.2)
                 + (0.16 if soft else 0.25) * np.sin(phase * 2.001) * np.exp(-t * 4.2)
                 + 0.035 * np.sin(phase * 3.997) * np.exp(-t * 8.0))
        voice *= smooth(t / 0.009) * smooth((duration_note - t) / 0.18)
        add(start, voice, gain, pan)

    # The opening phrase has deliberate space; different contour at the ending.
    for index, (start, note) in enumerate(((0.8, 74), (2.2, 77), (3.8, 81), (5.4, 79),
                                         (6.8, 77), (8.0, 72), (9.25, 74), (10.5, 76))):
        pluck(start, note, 0.12, math.sin(index * 1.5) * 0.35, 3.2, True)

    # Evolving arpeggio: geometry is broken eighths; algebra is syncopated;
    # orbit section opens up, then calculus/harmonics add interlocking figures.
    for section_index, (start, end, _, intensity) in enumerate(SECTIONS[1:-1], 1):
        if start >= duration:
            break
        step = 0.25 if section_index in (1, 2, 4, 5) else 0.5
        if section_index == 6:
            step = 0.25
        for index, when in enumerate(np.arange(start, min(end, duration), step)):
            if section_index == 1 and index % 8 in (3, 7):
                continue
            if section_index == 2 and index % 16 in (6, 7, 14):
                continue
            if section_index == 3 and index % 4 == 3:
                continue
            notes = chord_at(float(when))
            pattern = (0, 2, 1, 3, 2, 0, 3, 1)
            note = notes[pattern[(index + section_index) % 8] % len(notes)] + 12
            if section_index == 5 and index % 8 >= 4:
                note += 12
            note = min(note, 84)
            accent = 1.16 if index % 4 == 0 else 0.82
            pluck(float(when), note, (0.055 + intensity * 0.045) * accent,
                  math.sin(index * 1.13 + section_index) * 0.48,
                  1.7 if section_index != 3 else 2.5, section_index == 3)
        # A slower counter-melody enters only after the calculus reveal.
        if section_index >= 4:
            for index, when in enumerate(np.arange(start + 0.375, min(end, duration), 2.0)):
                notes = chord_at(float(when))
                pluck(float(when), notes[(index + 2) % len(notes)] + 12,
                      0.055 + intensity * 0.025, (-1) ** index * 0.4, 2.4, True)

    # Tonal bass: separate notes and rests follow each harmony rather than a drone.
    for section_index, (start, end, _, intensity) in enumerate(SECTIONS[1:-1], 1):
        step = 1.0 if section_index == 3 else 0.5
        for index, when in enumerate(np.arange(start, min(end, duration), step)):
            if section_index == 1 and index % 4 == 3:
                continue
            t = clock(step * 0.92)
            note = chord_at(float(when))[0] - 12
            if section_index >= 5 and index % 8 == 6:
                note += 7
            phase = 2 * np.pi * frequency(note) * t
            bass = np.sin(phase) + 0.22 * np.sin(2 * phase) + 0.06 * np.sin(3 * phase)
            envelope = smooth(t / 0.013) * np.exp(-t * 2.0) * smooth((step * 0.92 - t) / 0.07)
            add(float(when), bass * envelope, 0.11 + 0.055 * intensity)

    def kick(when, strength):
        t = clock(0.47)
        phase = 2 * np.pi * (43 * t + 67 * (1 - np.exp(-35 * t)) / 35)
        body = np.sin(phase) * np.exp(-t * 9) * smooth(t / 0.003)
        transient = rng.standard_normal(len(t)) * np.exp(-t * 150) * 0.035
        add(when, (body + transient) * smooth((0.47 - t) / 0.06), strength)

    def snare(when, strength, pan=0.0):
        t = clock(0.21)
        noise = rng.standard_normal(len(t))
        # Smooth the top end; this is a soft clap-like accent, not a piercing hiss.
        noise = np.convolve(noise, np.ones(9) / 9, mode="same")
        body = 0.18 * np.sin(2 * np.pi * 175 * t) * np.exp(-t * 30)
        voice = (noise * np.exp(-t * 23) + body) * smooth(t / 0.002)
        add(when, voice * smooth((0.21 - t) / 0.05), strength, pan)

    def hat(when, strength, pan):
        t = clock(0.08)
        noise = rng.standard_normal(len(t))
        filtered = np.convolve(noise, np.ones(5) / 5, mode="same")
        voice = np.diff(filtered, prepend=filtered[0]) * np.exp(-t * 60)
        add(when, voice * smooth(t / 0.002) * smooth((0.08 - t) / 0.02), strength, pan)

    for section_index, (start, end, _, intensity) in enumerate(SECTIONS[1:-1], 1):
        for index, when in enumerate(np.arange(start, min(end, duration), BEAT)):
            if section_index == 3:
                if index % 4 == 0:
                    kick(float(when), 0.17)
                continue
            kick(float(when), 0.18 + intensity * 0.1)
            if index % 2 == 1:
                snare(float(when), 0.10 + intensity * 0.055, 0.08)
            if section_index >= 2:
                hat(float(when) + 0.25, 0.035 + intensity * 0.015, (-1) ** index * 0.3)
            if section_index >= 5 and index % 4 == 3:
                hat(float(when) + 0.375, 0.03, -0.4)
        # Brief end-of-chapter rolls create momentum without constant density.
        if section_index in (1, 2, 4, 5, 6):
            for index in range(4):
                snare(end - 0.5 + index * 0.125, 0.06 + index * 0.012, (index - 1.5) * 0.2)

    # Filtered swells and low impacts make chapter changes audible.
    for transition in (12, 28, 48, 66, 84, 102, 114):
        if transition - 2.1 >= duration:
            continue
        t = clock(2.3)
        noise = rng.standard_normal(len(t))
        filtered = np.convolve(noise, np.ones(29) / 29, mode="same")
        envelope = smooth(t / 2.05) * smooth((2.3 - t) / 0.16)
        sweep = np.sin(2 * np.pi * (95 * t + 80 * t ** 2)) * 0.11
        add(transition - 2.1, (filtered + sweep) * envelope, 0.11)
        t = clock(2.5)
        impact = (np.sin(2 * np.pi * 36 * t) + 0.24 * np.sin(2 * np.pi * 72 * t))
        impact *= np.exp(-t * 2.7) * smooth(t / 0.006) * smooth((2.5 - t) / 0.3)
        add(transition, impact, 0.17 if transition != 48 else 0.10)

    # Resolve to the opening theme at a lower register, with a high soft ninth.
    for index, (start, note, gain) in enumerate(((114.0, 74, 0.15), (114.02, 81, 0.08),
                                                (115.0, 77, 0.11), (116.0, 76, 0.10),
                                                (117.0, 74, 0.13), (118.0, 86, 0.045))):
        pluck(start, note, gain, math.sin(index * 1.4) * 0.25, 3.5, True)

    # Quiet cross-channel early reflections, no large FFT/convolution dependency.
    dry = mix.copy()
    for delay, gain in ((0.1875, 0.105), (0.3125, 0.075), (0.4375, 0.045), (0.6875, 0.025)):
        offset = round(delay * sample_rate)
        if offset < count:
            mix[offset:] += dry[:-offset, ::-1] * gain
    del dry
    # Gentle sidechain motion is strongest in the climax, never a harsh gate.
    timeline = np.arange(count, dtype=np.float64) / sample_rate
    climax = smooth((timeline - 82) / 2) * (1 - smooth((timeline - 113.5) / 0.5))
    duck = 1.0 - 0.11 * climax * np.exp(-np.mod(timeline, BEAT) * 16)
    fade = smooth(timeline / 0.8) * smooth((duration - timeline) / 2.0)
    mix *= np.asarray(duck * fade, dtype=np.float32)[:, None]
    peak = float(np.max(np.abs(mix)))
    if peak:
        mix = np.tanh(mix * (0.82 / peak)).astype(np.float32)
        mix *= np.float32(10 ** (-2.5 / 20) / np.max(np.abs(mix)))
    return mix


def write_score(path, duration=120.0, sample_rate=48000):
    path = Path(path)
    samples = compose(duration, sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(np.rint(samples * 32767).astype("<i2").tobytes())
    return {"path": str(path.resolve()), "duration": len(samples) / sample_rate,
            "sample_rate": sample_rate, "channels": 2, "original_synthesis": True,
            "external_samples": False, "bpm": 120,
            "peak_dbfs": 20 * math.log10(max(float(np.max(np.abs(samples))), 1e-12)),
            "rms_dbfs": 20 * math.log10(max(float(np.sqrt(np.mean(samples ** 2))), 1e-12)),
            "sections": [{"start": a, "end": b, "name": name} for a, b, name, _ in SECTIONS]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=120.0)
    args = parser.parse_args()
    print(json.dumps(write_score(args.output, args.duration), indent=2))


if __name__ == "__main__":
    main()
