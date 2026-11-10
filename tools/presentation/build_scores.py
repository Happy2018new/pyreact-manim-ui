"""Two original scene-specific scores, made entirely with oscillator synthesis.

Mathematics: 80 BPM, D Lydian, felt/wood keys and narrow string harmonics.
Story: 90 BPM in three, E minor opening into G major, plucks and dark choir.
Cue sheets are independent of the visual compiler. No recorded instruments,
external samples, or previously rendered score are used.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RATE = 48000
DURATION = 120.0
PEAK_DBFS = -1.5


def smooth(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def frequency(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def register(note, low=57, high=81):
    while note < low:
        note += 12
    while note > high:
        note -= 12
    return note


def chord_at(harmony, when):
    for start, end, notes in harmony:
        if start <= when < end:
            return notes
    return harmony[-1][2]


class Orchestra:
    """Small, band-limited additive instruments and deterministic performances."""

    def __init__(self, seed):
        self.mix = np.zeros((round(DURATION * RATE), 2), dtype=np.float32)
        self.rng = np.random.default_rng(seed)
        self.dips = []

    def clock(self, seconds):
        return np.arange(round(seconds * RATE), dtype=np.float64) / RATE

    def add(self, start, signal, gain=1.0, pan=0.0):
        offset = round(start * RATE)
        skip = max(0, -offset)
        offset = max(0, offset)
        count = min(len(signal) - skip, len(self.mix) - offset)
        if count <= 0:
            return
        pan = float(np.clip(pan, -1, 1))
        values = np.asarray(signal[skip:skip + count] * gain, dtype=np.float32)
        self.mix[offset:offset + count, 0] += values * math.sqrt((1 - pan) / 2)
        self.mix[offset:offset + count, 1] += values * math.sqrt((1 + pan) / 2)

    def key(self, start, note, gain=.1, pan=0, length=2.3, felt=True):
        """Rounded hammer attack and quickly darkening wooden partials."""
        t = self.clock(length)
        phase = 2 * np.pi * frequency(note) * t
        voice = (np.sin(phase + .045 * np.sin(phase * 2) * np.exp(-t * 8))
                 * np.exp(-t * (1.75 if felt else 2.2))
                 + (.19 if felt else .29) * np.sin(phase * 2.001) * np.exp(-t * 4)
                 + .065 * np.sin(phase * 3.002) * np.exp(-t * 6.8)
                 + .024 * np.sin(phase * 4.012) * np.exp(-t * 11))
        # A pitched short hammer replaces noisy or glassy attacks.
        voice += .022 * np.sin(phase * 6.73) * np.exp(-t * 42)
        voice *= smooth(t / (.014 if felt else .008)) * smooth((length - t) / .22)
        self.add(start, voice, gain, pan)

    def bass(self, start, note, length=.62, gain=.14):
        t = self.clock(length)
        phase = 2 * np.pi * frequency(note) * t
        voice = np.sin(phase) + .16 * np.sin(phase * 2) + .028 * np.sin(phase * 3)
        envelope = smooth(t / .022) * np.exp(-t * 1.9) * smooth((length - t) / .12)
        self.add(start, voice * envelope, gain)

    def pad(self, start, notes, length, gain=.16, choir=False, width=.72,
            attack=1.0, release=1.6):
        """Narrow strings or a dark vowel, both synthesized from sine partials."""
        t = self.clock(length)
        envelope = smooth(t / attack) * smooth((length - t) / release)
        for index, note in enumerate(notes):
            f = frequency(note)
            phase = (2 * np.pi * f * t + index * .71
                     + .0011 * f / 4.6 * (1 - np.cos(2 * np.pi * 4.6 * t))
                     * smooth(t / .9))
            voice = np.zeros(len(t), dtype=np.float64)
            total = 0.0
            for harmonic in range(1, 9 if choir else 7):
                partial = harmonic * f
                if choir:
                    formant = (.80 * math.exp(-((partial - 540) / 245) ** 2)
                               + .42 * math.exp(-((partial - 1030) / 340) ** 2)
                               + .15 * math.exp(-((partial - 1780) / 480) ** 2))
                    amplitude = (.36 / harmonic + formant) / math.sqrt(harmonic)
                else:
                    amplitude = harmonic ** -1.65
                amplitude *= math.exp(-(partial / (2600 if choir else 2050)) ** 2)
                voice += amplitude * np.sin(phase * harmonic + harmonic * .12)
                total += amplitude
            voice += .18 * np.sin(2 * np.pi * f * 1.0014 * t + .4 + index)
            voice *= envelope * (.96 + .04 * np.sin(t * .73 + index)) / (total + .18)
            pan = (2 * index / max(1, len(notes) - 1) - 1) * width
            self.add(start, voice, gain / math.sqrt(len(notes)), pan)

    def ribbon(self, start, note, length, gain=.08, pan=0):
        """Breath-shaped bowed/vocal line, without a flute or sample layer."""
        t = self.clock(length)
        f = frequency(note)
        phase = (2 * np.pi * f * t
                 + .0016 * f / 5.1 * (1 - np.cos(2 * np.pi * 5.1 * t))
                 * smooth(t / .45))
        voice = (np.sin(phase) + .24 * np.sin(phase * 2 + .2)
                 + .10 * np.sin(phase * 3 + .5) + .035 * np.sin(phase * 4))
        envelope = smooth(t / .19) * smooth((length - t) / .48)
        self.add(start, voice * envelope, gain, pan)

    def drum(self, start, gain=.12, brush=False, pan=0):
        length = .24 if brush else .48
        t = self.clock(length)
        if brush:
            # Inharmonic oscillators form a short, soft brush texture.
            voice = np.zeros(len(t), dtype=np.float64)
            for index in range(18):
                f = 310 + index * 113.7 + 23 * math.sin(index * 1.8)
                voice += np.sin(2 * np.pi * f * t + index * 2.399) / 18
            voice = (voice * np.exp(-t * 24)
                     + .13 * np.sin(2 * np.pi * 174 * t) * np.exp(-t * 30))
        else:
            phase = 2 * np.pi * (44 * t + 47 * (1 - np.exp(-t * 30)) / 30)
            voice = np.sin(phase) * np.exp(-t * 10)
            voice += .018 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 75)
        envelope = smooth(t / .004) * smooth((length - t) / .055)
        self.add(start, voice * envelope, gain, pan)

    def impact(self, start, gain=.22, length=.72):
        t = self.clock(length)
        phase = 2 * np.pi * (41.2 * t + 34 * (1 - np.exp(-t * 32)) / 32)
        voice = (np.sin(phase) + .12 * np.sin(phase * 2)) * np.exp(-t * 7)
        self.add(start, voice * smooth(t / .006) * smooth((length - t) / .15), gain)

    def wind(self, start, length, gain=.025, pan=0, rise=False):
        """Brief low-band turbulence for gestures, never a white-noise bed."""
        t = self.clock(length)
        voice = np.zeros(len(t), dtype=np.float64)
        for index in range(16):
            f = 88 + index * 41.73 + self.rng.uniform(-12, 12)
            voice += (np.sin(2 * np.pi * f * t + self.rng.uniform(0, 2 * np.pi))
                      * (1 + .28 * np.sin(t * (1.7 + index * .23))) / 16)
        envelope = np.sin(np.pi * np.clip(t / length, 0, 1)) ** 2
        if rise:
            envelope *= smooth(t / max(.1, length * .75))
        self.add(start, voice * envelope, gain, pan)

    def sweep(self, start, length, low=180.0, high=700.0, gain=.025, pan=0):
        t = self.clock(length)
        phase = 2 * np.pi * (low * t + (high - low) * t * t / (2 * length))
        voice = np.sin(phase) + .10 * np.sin(phase * 2.001)
        envelope = np.sin(np.pi * np.clip(t / length, 0, 1)) ** 2
        self.add(start, voice * envelope, gain, pan)

    def dip(self, start, quiet_start, quiet_end, end, floor=.04):
        self.dips.append((start, quiet_start, quiet_end, end, floor))

    def finish(self, room=.7):
        dry = self.mix.copy()
        for delay, gain in ((.127, .10), (.239, .075), (.383, .052),
                            (.617, .031), (.947, .018)):
            offset = round(delay * RATE)
            self.mix[offset:] += dry[:-offset, ::-1] * (gain * room)
        del dry
        t = np.arange(len(self.mix), dtype=np.float64) / RATE
        envelope = smooth(t / .18) * smooth((DURATION - t) / 2.1)
        # After the room, so silence includes the earlier instruments' tails.
        for start, quiet_start, quiet_end, end, floor in self.dips:
            depth = smooth((t - start) / (quiet_start - start))
            depth *= smooth((end - t) / (end - quiet_end))
            envelope *= 1 - (1 - floor) * depth
        self.mix *= np.asarray(envelope, dtype=np.float32)[:, None]
        peak = float(np.max(np.abs(self.mix)))
        if peak:
            # One linear gain preserves the score's written dynamics.
            self.mix *= np.float32(10 ** (PEAK_DBFS / 20) / peak)
        return self.mix


def compose_math():
    score = Orchestra(202611108)
    beat = .75  # 80 BPM, continuous through the visual cue changes.
    harmony = (
        (0, 7, (50, 57, 61, 66, 76)), (7, 14, (47, 54, 57, 62, 73)),
        (14, 20, (50, 57, 61, 66, 76)), (20, 27, (47, 54, 57, 62, 73)),
        (27, 34, (52, 59, 61, 66, 80)), (34, 40, (50, 57, 61, 66, 76)),
        (40, 46, (47, 54, 57, 62, 73)), (46, 50, (52, 59, 61, 66, 80)),
        (50, 54, (45, 52, 57, 62, 66)), (54, 61, (50, 57, 61, 66, 76)),
        (61, 68, (52, 59, 61, 66, 80)), (68, 74, (47, 54, 57, 62, 73)),
        (74, 80, (50, 57, 61, 66, 76)), (80, 86, (47, 54, 57, 62, 73)),
        (86, 92, (52, 59, 61, 66, 80)), (92, 96, (45, 52, 57, 62, 66)),
        (96, 100, (47, 54, 57, 62, 73)), (100, 104, (45, 52, 57, 62, 68)),
        (104, 112, (50, 57, 61, 66, 76, 80)), (112, 120, (50, 57, 61, 66, 76)),
    )
    for start, end, notes in harmony:
        if start < 14:
            gain = .095
        elif start < 34:
            gain = .125
        elif start < 54:
            gain = .145
        elif start < 74:
            gain = .155
        elif start < 96:
            gain = .17 + .025 * (start - 74) / 22
        elif start < 104:
            gain = .20 + .05 * (start - 96) / 8
        elif start < 112:
            gain = .30
        else:
            gain = .13
        score.pad(start, notes, end - start + 1.8, gain,
                  width=.40 if start < 34 else .76,
                  attack=.55 if start == 104 else 1.1, release=1.8)

    # D-F#-E-A begins as two incomplete gestures, then develops.
    opening = ((1.5, 62), (3, 66), (5.25, 64), (8.25, 69), (10.5, 66), (12, 64))
    for index, (when, note) in enumerate(opening):
        score.key(when, note, .105 if index < 3 else .085,
                  math.sin(index * 1.3) * .36, 3.0)

    # Pulse, harmonic figures and melody have independent entrances and rests.
    for index in range(round(DURATION / beat)):
        when = index * beat
        notes = chord_at(harmony, when)
        if 14 <= when < 54 or 74 <= when < 104:
            strength = (.105 if when < 34 else .13 if when < 54
                        else .14 if when < 96 else .15 + .06 * (when - 96) / 8)
            if index % 2 == 0 or (96 <= when < 104 and index % 4 == 3):
                score.bass(when, notes[0] - 12, .68, strength)
            if index % 4 == 0:
                score.drum(when, strength * .68)
            if (34 <= when < 54 or 80 <= when < 104) and index % 4 == 2:
                score.drum(when, strength * .40, True, .12)
        elif 54 <= when < 74 and index % 4 == 0:
            score.bass(when, notes[0] - 12, 1.25, .073)

    # Circle/projection: broken eighths with a full-beat rest in each phrase.
    for index, when in enumerate(np.arange(14.25, 34, beat / 2)):
        if index % 8 in (3, 6, 7):
            continue
        notes = chord_at(harmony, float(when))
        note = register(notes[(0, 2, 1, 3, 1, 2, 3, 1)[index % 8]], 57, 76)
        score.key(float(when), note, .060 if index % 4 else .083,
                  math.sin(index * 1.39) * .48, 1.9, False)
    for index, note in enumerate((74, 78, 76, 81, 78, 76)):
        score.key(18 + index * beat * 2, note, .092, -.16, 2.6)

    # Koch: the intervals recur in shortened and answering fragments.
    koch = (62, 66, 64, 69, 66, 62, 69, 64, 74, 78, 76, 81)
    for index, when in enumerate(np.arange(34.125, 53.75, beat / 2)):
        if index % 12 in (5, 9, 11):
            continue
        notes = chord_at(harmony, float(when))
        note = (koch[index % len(koch)] if index % 12 < 4 else
                register(notes[(index // 2 + 1) % len(notes)], 62, 81))
        score.key(float(when), note, .077 if index % 4 else .105,
                  math.sin(index * 2.399) * .63, 1.55, False)

    # Sine/harmonics: withdraw busy keys and let longer notes breathe.
    for index, (when, note, length) in enumerate(((55.5, 66, 3.7), (60, 69, 3.4),
                                               (64.5, 68, 3.8), (69, 66, 3.4))):
        score.ribbon(when, note, length, .068, (-1) ** index * .22)
        score.key(when + .75, note - 12, .065, (-1) ** index * -.4, 3.1)
    for index, when in enumerate((55.5, 58.5, 63, 66, 70.5, 72)):
        notes = chord_at(harmony, when)
        score.key(when, register(notes[(index + 1) % len(notes)], 62, 76),
                  .045, math.sin(index * 1.4) * .45, 2.5)

    # Folded corolla: wider interlocking figures and the complete upper theme.
    for index, when in enumerate(np.arange(74.25, 103.875, beat / 2)):
        if index % 16 in (3, 7, 12, 15) and when < 96:
            continue
        notes = chord_at(harmony, float(when))
        note = register(notes[(0, 2, 1, 3, 2, 4, 1, 3)[index % 8] % len(notes)], 62, 81)
        rise = float(np.clip((when - 96) / 8, 0, 1))
        score.key(float(when), note, .070 + .045 * rise,
                  math.sin(index * 1.47) * .70, 1.8, False)
    for begin, transpose, strength in ((76.5, 0, .105), (85.5, -12, .09), (94.5, 0, .11)):
        for index, note in enumerate((74, 78, 76, 81)):
            score.ribbon(begin + index * beat * 2, note + transpose,
                         1.7, strength, math.sin(index * 1.2) * .28)

    # Short pitched breaths underline the visual changes without repeated crashes.
    for cue, low, high in ((14, 160, 430), (34, 210, 620),
                           (54, 460, 230), (74, 190, 590)):
        score.sweep(cue - .85, .95, low, high, .018, -.2)
        score.key(cue, register(chord_at(harmony, cue)[1], 62, 74), .09, .22, 2.4)
    score.sweep(96, 3.2, 130, 400, .018, -.28)
    score.sweep(100.3, 3.5, 250, 860, .035, .26)
    for index, when in enumerate((100.5, 102, 102.75, 103.125, 103.5, 103.75)):
        score.drum(when, .08 + .014 * index)

    # 104: the fractal star opens. The large harmony holds; rapid figures stop.
    score.impact(104, .24, .85)
    score.bass(104, 38, 2.8, .23)
    for index, note in enumerate((62, 69, 73, 78, 80, 88)):
        score.key(104 + index * .045, note, .12 if index < 4 else .055,
                  -.62 + index * .24, 4.2)
    for index, (when, note) in enumerate(((105.75, 78), (107.25, 76), (109.5, 74))):
        score.ribbon(when, note, 2.4, .105 - index * .015, .18 - index * .18)
    score.bass(108, 38, 2.6, .105)

    # 112: the original timbre and a quiet resolving answer remain.
    for index, (when, note) in enumerate(((112, 66), (113.5, 64), (115.75, 62))):
        score.key(when, note, .10 - index * .018, (-1) ** index * .24, 4.0)
    score.bass(112, 38, 3.4, .075)
    return score.finish(room=.58)


def compose_story():
    score = Orchestra(202611109)
    beat = 2 / 3  # 90 BPM in three; each bar lasts two seconds.
    harmony = (
        (0, 8, (52, 59, 67, 78)), (8, 16, (48, 55, 59, 64)),
        (16, 24, (45, 52, 55, 59, 64)), (24, 32, (43, 52, 59, 66, 71)),
        (32, 38, (47, 54, 57, 64, 66)), (38, 42.7, (47, 54, 57, 63, 66)),
        (44.4, 50, (55, 59, 64, 78)), (50, 56, (55, 59, 64, 69)),
        (56, 64, (54, 59, 64, 69)), (64, 70, (52, 59, 67, 78)),
        (70, 78, (48, 55, 59, 62, 64)), (78, 84, (45, 52, 55, 59, 64)),
        (84, 88, (48, 55, 59, 62, 64)), (88, 92, (50, 57, 62, 64, 67)),
        (92, 94, (50, 57, 62, 66, 69)), (94, 102, (43, 50, 57, 59, 64, 67)),
        (102, 110, (43, 55, 59, 62, 64, 67)), (110, 120, (52, 59, 67, 78)),
    )
    # No sustained chord crosses the impact; drifting fragments omit the root.
    for start, end, notes in harmony:
        if start < 16:
            gain = .105
        elif start < 32:
            gain = .16
        elif start < 43:
            gain = .14
        elif start < 64:
            gain = .070
        elif start < 78:
            gain = .12 + .035 * (start - 64) / 14
        elif start < 94:
            gain = .17 + .095 * (start - 78) / 16
        elif start < 110:
            gain = .285 if start == 94 else .23
        else:
            gain = .115
        tail = 0 if 32 <= start < 43 else 1.8
        score.pad(start, notes, end - start + tail, gain, choir=True,
                  width=.50 if start < 16 else .83,
                  attack=.55 if start == 94 else 1.25,
                  release=.65 if 32 <= start < 43 else 1.8)
        if 78 <= start < 110:
            score.pad(start + .1, tuple(note + 12 for note in notes[1:4]),
                      end - start + 1.7, gain * .31, width=.90,
                      attack=.85, release=1.8)

    # The wind's letter begins with the unfinished E-B-G-F#-E sentence.
    for index, (when, note) in enumerate(((1.3, 64), (3.3, 71), (5.3, 67),
                                        (7.3, 66), (11.3, 64), (13.3, 59))):
        score.key(when, note, .095 if index < 4 else .075,
                  math.sin(index * 1.5) * .36, 3.2)
    for cue, pan in ((1, -.45), (5.3, .45)):
        score.wind(cue + .2, 1.4, .024, pan)
        score.sweep(cue + .5, 1.2, 210, 410, .012, pan)

    # Star: lilting lower accompaniment, rather than continuous high bells.
    for index, when in enumerate(np.arange(16, 32, beat)):
        notes = chord_at(harmony, float(when))
        position = index % 3
        if position == 0:
            score.bass(float(when), notes[0] - 12, 1.1, .11)
            if index % 6 == 0:
                score.drum(float(when), .065)
        else:
            note = register(notes[(index // 3 + position) % len(notes)], 57, 74)
            score.key(float(when), note, .065, (-1) ** position * .33, 2.2)
    for index, (when, note) in enumerate(((17.33, 76), (19.33, 83), (22, 79),
                                        (24.67, 78), (28, 76))):
        score.ribbon(when, note, 2.2, .075, math.sin(index) * .23)
    score.key(16, 71, .12, -.25, 3.4)
    score.key(16.12, 79, .035, .3, 3.4)

    # Meteors gain motion and tension, then stop at the single low impact.
    for index, when in enumerate(np.arange(32, 42.7, beat)):
        notes = chord_at(harmony, float(when))
        if index % 3 == 0:
            score.bass(float(when), notes[0] - 12, .75, .105)
            score.drum(float(when), .09)
        if index % 3 == 2:
            score.drum(float(when), .045, True, -.12)
        if index % 6 in (0, 1, 3, 4):
            score.key(float(when), register(notes[(index + 2) % len(notes)], 62, 78),
                      .070 + index * .001, math.sin(index * 1.7) * .64, 1.45, False)
    score.sweep(32.3, 2.4, 190, 680, .022, -.5)
    score.sweep(36.1, 2.2, 330, 980, .025, .45)
    score.sweep(40.5, 1.75, 1100, 170, .035, -.2)
    score.wind(41.7, 1.1, .065, .2, True)
    score.impact(43, .34, .42)
    # The pause includes reverberation, giving the shattering room to read.
    score.dip(43.18, 43.48, 44.18, 44.65, .025)

    # Drift: sparse warm fragments answer across a wide stereo field.
    drift = ((45.3, 71), (47.8, 67), (51.2, 64), (54.3, 69),
             (57.1, 66), (60.2, 71), (62.3, 64))
    for index, (when, note) in enumerate(drift):
        score.key(when, note, .052, math.sin(index * 2.399) * .78, 3.7)
    for when, pan in ((47, -.6), (53.3, .55), (59.5, -.3)):
        score.wind(when, 1.2, .025, pan)
    score.ribbon(58.2, 66, 3.6, .035, -.3)

    # Orbit: the root returns, then the pulse rebuilds one layer at a time.
    for index, when in enumerate(np.arange(64, 78, beat)):
        notes = chord_at(harmony, float(when))
        amount = (when - 64) / 14
        if index % 3 == 0:
            score.bass(float(when), notes[0] - 12, 1.0, .08 + .05 * amount)
            if when >= 68:
                score.drum(float(when), .045 + .045 * amount)
        elif index % 6 != 5:
            score.key(float(when), register(notes[(index + 1) % len(notes)], 57, 76),
                      .047 + .03 * amount, math.sin(index * 1.2) * .46, 2.0)
        if when >= 72 and index % 3 == 2:
            score.drum(float(when), .035, True, .12)
    for index, note in enumerate((64, 71, 67, 66)):
        score.ribbon(65.33 + index * 2.67, note, 2.0, .058, (-1) ** index * .24)
    score.key(64, 64, .10, -.2, 3)

    # Reassembly grows register, counter-voice and harmony in one long crescendo.
    for index, when in enumerate(np.arange(78, 94, beat / 2)):
        notes = chord_at(harmony, float(when))
        amount = (when - 78) / 16
        if index % 6 in (0, 2, 3, 4) or (when >= 90 and index % 6 == 5):
            note = register(notes[(0, 2, 1, 3, 2, 4)[index % 6] % len(notes)], 62, 81)
            score.key(float(when), note, .060 + .038 * amount,
                      math.sin(index * 1.73) * .73, 1.9, False)
        if index % 6 == 0:
            score.bass(float(when), notes[0] - 12, .95, .13 + .055 * amount)
            score.drum(float(when), .10 + .055 * amount)
        if index % 6 == 4:
            score.drum(float(when), .045 + .028 * amount, True, .12)
    for index, (when, note, length) in enumerate(((78.67, 76, 2.4), (81.33, 83, 2.4),
                                               (84, 79, 2.4), (86.67, 78, 2.4),
                                               (89.33, 76, 2.5), (92, 78, 1.8))):
        score.ribbon(when, note, length, .095 + index * .008, math.sin(index * .9) * .3)
    for index, when in enumerate((79.5, 83.5, 87.5, 91.3)):
        score.sweep(when, .8, 210 + index * 35, 520 + index * 55,
                    .014 + index * .003, (-1) ** index * .48)
    score.sweep(91.9, 1.9, 230, 790, .032, .25)

    # 94: G6/9 opens with the two wings. Space replaces the fast motion.
    score.impact(94, .22, .95)
    score.bass(94, 31, 2.8, .23)
    for index, note in enumerate((55, 62, 69, 71, 76, 79)):
        score.key(94 + index * .05, note, .115 if index < 4 else .07,
                  -.65 + index * .26, 4.5)
    for index, (when, note, length) in enumerate(((95.33, 79, 3.2), (99.33, 78, 3.1),
                                               (103.33, 76, 3.1), (107.33, 74, 2.5))):
        score.ribbon(when, note, length, .11 - index * .008, (-1) ** index * .32)
    for index, when in enumerate((98, 102, 106)):
        score.bass(when, 31, 1.8, .10 - index * .014)
        score.key(when + 1.33, (71, 74, 71)[index], .065, (-1) ** index * .4, 3.0)

    # Title: the first small voice returns with its final E, without a new swell.
    for index, (when, note) in enumerate(((110.4, 71), (112.4, 67),
                                        (114.4, 66), (116.4, 64))):
        score.key(when, note, .09 - index * .014, math.sin(index * 1.3) * .32, 3.4)
    score.bass(110, 40, 3.5, .075)
    return score.finish(room=.88)


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
