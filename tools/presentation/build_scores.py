"""Original film scores and synchronized foley, synthesized without samples."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RATE = 48000
DURATION = 120.0


def smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def frequency(note):
    return 440.0 * 2 ** ((note - 69) / 12)


class Orchestra:
    def __init__(self, seed, samples=None):
        self.mix = (np.zeros((round(DURATION * RATE), 2), dtype=np.float32)
                    if samples is None else samples.copy())
        self.rng = np.random.default_rng(seed)

    def clock(self, seconds):
        return np.arange(round(seconds * RATE), dtype=np.float64) / RATE

    def add(self, start, signal, gain=1.0, pan=0.0):
        offset = round(start * RATE)
        skip = max(0, -offset)
        offset = max(0, offset)
        count = min(len(signal) - skip, len(self.mix) - offset)
        if count <= 0:
            return
        values = np.asarray(signal[skip:skip + count] * gain, dtype=np.float32)
        self.mix[offset:offset + count, 0] += values * math.sqrt((1 - pan) / 2)
        self.mix[offset:offset + count, 1] += values * math.sqrt((1 + pan) / 2)

    def bell(self, start, note, gain=.1, pan=0, length=3.0):
        t = self.clock(length)
        phase = 2 * np.pi * frequency(note) * t
        voice = (np.sin(phase) * np.exp(-t * 1.7)
                 + .22 * np.sin(phase * 2.002) * np.exp(-t * 3.2)
                 + .065 * np.sin(phase * 4.01) * np.exp(-t * 5.6))
        voice *= smooth(t / .007) * smooth((length - t) / .25)
        self.add(start, voice, gain, pan)

    def flute(self, start, note, length=1.9, gain=.1, pan=0):
        t = self.clock(length)
        vibrato = .003 * np.sin(2 * np.pi * 4.8 * t) * smooth(t / .4)
        phase = 2 * np.pi * frequency(note) * t + vibrato
        voice = np.sin(phase) + .17 * np.sin(2 * phase) + .035 * np.sin(3 * phase)
        envelope = smooth(t / .15) * smooth((length - t) / .5)
        self.add(start, voice * envelope, gain, pan)

    def pad(self, start, notes, length, gain=.14, pan=0):
        t = self.clock(length)
        envelope = smooth(t / 1.0) * smooth((length - t) / 1.5)
        for i, note in enumerate(notes):
            phase = 2 * np.pi * frequency(note) * t
            voice = (np.sin(phase + i * .7) + .32 * np.sin(phase * 1.0015)
                     + .1 * np.sin(phase * 2.0) + .025 * np.sin(phase * 3.0))
            self.add(start, voice * envelope, gain / len(notes),
                     np.clip(pan + (i - (len(notes) - 1) / 2) * .2, -.9, .9))

    def wind(self, start, length, gain=.07, pan=0, rise=False):
        t = self.clock(length)
        # Interpolated turbulence avoids a white-noise hiss and large convolutions.
        grid = np.arange(math.ceil(length * 2500) + 2) / 2500
        noise = np.interp(t, grid, self.rng.standard_normal(len(grid)))
        low_grid = np.arange(math.ceil(length * 100) + 2) / 100
        low = np.interp(t, low_grid, self.rng.standard_normal(len(low_grid)))
        gust = .35 + .65 * (.5 + .5 * np.sin(t * 1.3 + start)) ** 2
        envelope = smooth(t / min(.6, length * .25)) * smooth((length - t) / .4)
        if rise:
            envelope *= smooth(t / max(.1, length - .25))
        self.add(start, (.30 * noise + .25 * low) * gust * envelope, gain, pan)

    def impact(self, start, gain=.2, bright=False):
        t = self.clock(2.5)
        phase = 2 * np.pi * (39 * t + 36 * (1 - np.exp(-t * 24)) / 24)
        body = (np.sin(phase) + .18 * np.sin(phase * 2)) * np.exp(-t * 3.0)
        envelope = smooth(t / .008) * smooth((2.5 - t) / .4)
        self.add(start, body * envelope, gain)
        if bright:
            self.bell(start + .02, 86, .075, -.3, 3.0)
            self.bell(start + .075, 93, .035, .4, 2.5)

    def sweep(self, start, length, low=280.0, high=1800.0, gain=.045, pan=0):
        """A soft pitched streak for meteors and converging star fragments."""
        t = self.clock(length)
        # Integral of a linear frequency ramp; reverse the endpoints for a fall.
        phase = 2 * np.pi * (low * t + (high - low) * t * t / (2 * length))
        envelope = np.sin(np.pi * np.clip(t / length, 0, 1)) ** 2
        voice = (np.sin(phase) + .18 * np.sin(phase * 2.003)) * envelope
        self.add(start, voice, gain, pan)

    def finish(self, reverb=True):
        if reverb:
            dry = self.mix.copy()
            for delay, gain in ((.173, .12), (.293, .09), (.431, .065), (.683, .04), (1.01, .02)):
                offset = round(delay * RATE)
                self.mix[offset:] += dry[:-offset, ::-1] * gain
        t = np.arange(len(self.mix), dtype=np.float64) / RATE
        self.mix *= np.asarray(smooth(t / .7) * smooth((DURATION - t) / 2), dtype=np.float32)[:, None]
        peak = float(np.max(np.abs(self.mix)))
        if peak:
            self.mix = np.tanh(self.mix * .85 / peak).astype(np.float32)
            self.mix *= np.float32(10 ** (-1.5 / 20) / np.max(np.abs(self.mix)))
        return self.mix


def compose_story():
    score = Orchestra(202611104)
    # A fragile pentatonic theme blossoms into major harmony after the storm.
    harmony = (
        (0, 8, (50, 57, 64, 69)), (8, 16, (46, 53, 60, 65)),
        (16, 25, (53, 60, 67, 72)), (25, 34, (48, 55, 62, 67)),
        (34, 42, (50, 57, 62, 66)), (42, 48, (55, 62, 69, 74)),
        (48, 54, (57, 64, 69, 73)), (54, 62, (50, 57, 60, 65)),
        (62, 69, (46, 53, 58, 64)), (69, 76, (45, 52, 58, 61)),
        (76, 84, (50, 57, 62, 66)), (84, 90, (55, 62, 67, 71)),
        (90, 96, (57, 64, 69, 73)), (96, 103, (50, 57, 66, 74)),
        (103, 110, (55, 62, 69, 74)), (110, 120, (50, 57, 62, 66, 73)),
    )
    for start, end, notes in harmony:
        storm = 54 <= start < 76
        score.pad(start, notes, end - start + 1.5, .17 if storm else .15)
        if start >= 34 and start < 110:
            score.pad(start, (notes[0] - 12, notes[0]), end - start + 1, .075)
        step = .36 if start >= 76 else .72 if start >= 16 else 1.44
        if storm:
            step = .72
        for i, when in enumerate(np.arange(start + .15, end, step)):
            pattern = (0, 1, 2, 3, 2, 1, 3, 2)
            note = notes[pattern[i % 8] % len(notes)] + 12
            score.bell(float(when), min(90, note), .045 if storm else .06,
                       math.sin(i * 1.4) * .65, 2.2)
    theme = (74, 78, 81, 83, 81, 78, 76, 74)
    for begin, spacing, gain in ((2.1, 1.42, .065), (18.0, 1.60, .095),
                                 (35.2, 1.73, .105), (77.0, 1.45, .105),
                                 (96.2, 1.45, .12), (111.0, .9, .07)):
        for i, note in enumerate(theme):
            if begin + i * spacing < 118:
                score.flute(begin + i * spacing, note,
                            spacing * 1.35, gain, math.sin(i * .9) * .25)
    # Wind is always present, growing from a breeze into the story's obstacle.
    for start in range(0, 120, 8):
        gain = .19 if 54 <= start < 76 else .08 if 32 <= start < 54 else .045
        score.wind(start, min(9.0, 120 - start), gain, math.sin(start * .1) * .6)
    for cue in (16, 34, 43, 54, 76, 96, 110.2):
        score.wind(cue - 2.4, 2.8, .18 if cue == 43 else .10, -.25, True)
        score.impact(cue, .27 if cue == 43 else .11 if cue in (76, 96) else .07,
                     cue in (16, 43, 76, 96))
    # Opening wind underlines, star sparks, meteors, scattering and reunion.
    for cue, pan in ((1.0, -.55), (5.8, .55)):
        score.wind(cue, 4.0, .055, pan, True)
        score.sweep(cue + .8, 2.3, 420, 840, .016, pan)
    for i, note in enumerate((86, 90, 93, 98)):
        score.bell(21 + .16 * i, note, .065, -.5 + i / 3, 3.0)
    score.wind(33.2, 1.5, .13, .65)
    score.sweep(36.0, 6.8, 250, 1700, .035, -.40)
    score.sweep(41.0, 1.9, 1900, 340, .045, .40)
    for i, note in enumerate((98, 93, 90, 86, 81, 78, 74, 69)):
        score.bell(43.05 + i * .14, note, .045, math.sin(i * 2.399) * .8, 2.5)
    for cue in (58.5, 65.5, 71.0):
        score.impact(cue, .075)
        score.wind(cue, 3.5, .13, -.4)
    for i in range(18):
        score.bell(77 + i * .66, (74, 78, 81, 86, 90)[i % 5], .055,
                   math.sin(i * 1.7) * .7, 3)
    # Individual pitched grains draw inward with the fixed-identity fragments.
    for i in range(28):
        start = 78.0 + i * .56
        pan = math.sin(i * 2.399) * .75 * (1 - i / 32)
        score.sweep(start, 1.15, 380 + i * 17, 900 + i * 19, .012, pan)
    score.bell(84.4, 86, .06, -.2, 4)
    score.pad(91.0, (62, 69, 74, 81), 5.5, .08)
    score.bell(93.9, 93, .12, 0, 5)
    for i in range(24):
        score.wind(96 + i * .43, .8, .065, math.sin(i * 1.5) * .7)
    score.bell(110, 86, .14, -.2, 5)
    score.bell(112, 81, .09, .2, 5)
    return score.finish()


def compose_math():
    path = ROOT / "tools/showcase_v2/score.py"
    spec = importlib.util.spec_from_file_location("_metamorphosis_score", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    score = Orchestra(202611105, module.compose(DURATION, RATE) * .8)
    timeline = json.loads((ROOT / "tools/showcase_v2/film.json").read_text(encoding="utf-8"))
    for index, event in enumerate(timeline["glyph_transitions"]):
        cue = event["transition_end"]
        score.wind(event["transition_start"] - .15, 1.12, .065,
                   math.sin(index * 2.4) * .65, True)
        if event["chapter"] in ("opening", "finale", "closing"):
            score.bell(cue, (86, 89, 93)[index % 3], .04, .3, 1.7)
    for cue in (12, 28, 48, 66, 84, 102, 110):
        score.impact(cue, .11, cue in (12, 102, 110))
    return score.finish(False)


def write_score(path, samples):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(np.rint(samples * 32767).astype("<i2").tobytes())
    return {"path": str(path.resolve()), "duration": len(samples) / RATE,
            "sample_rate": RATE, "channels": 2, "original_synthesis": True,
            "external_samples": False,
            "peak_dbfs": round(20 * math.log10(float(np.max(np.abs(samples)))), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/presentation-audio")
    args = parser.parse_args()
    results = {}
    for scene, composer in (("client_showcase", compose_math), ("story_showcase", compose_story)):
        print("Composing " + scene, flush=True)
        results[scene] = write_score(args.output / (scene + ".wav"), composer())
    (args.output / "scores.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
