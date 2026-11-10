"""Two original scene-specific scores, made entirely with oscillator synthesis.

Mathematics: 80 BPM, D Lydian, interlocking synth figures and warm low pulses.
Story: 90 BPM in three, E minor opening into G major, moving air and crystal.
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
        voice = (np.sin(phase) + .23 * np.sin(phase * 2) * np.exp(-t * 2.5)
                 + .075 * np.sin(phase * 3) * np.exp(-t * 6))
        envelope = smooth(t / .016) * np.exp(-t * 1.65) * smooth((length - t) / .12)
        self.add(start, voice * envelope, gain)

    def crystal(self, start, note, gain=.055, pan=0, length=1.5):
        """Short glass-like pluck; upper partials disappear before the warm tail."""
        t = self.clock(length)
        phase = 2 * np.pi * frequency(note) * t
        voice = (np.sin(phase + .32 * np.sin(phase * 2) * np.exp(-t * 11))
                 * np.exp(-t * 2.5)
                 + .23 * np.sin(phase * 2.003) * np.exp(-t * 7)
                 + .085 * np.sin(phase * 3.997) * np.exp(-t * 14)
                 + .028 * np.sin(phase * 6.013) * np.exp(-t * 23))
        envelope = smooth(t / .009) * smooth((length - t) / .18)
        self.add(start, voice * envelope, gain, pan)

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
        """Evolving oscillator turbulence, with softer and slower outer bands."""
        t = self.clock(length)
        voice = np.zeros(len(t), dtype=np.float64)
        for index in range(24):
            f = 113 + index * 59.73 + self.rng.uniform(-22, 22)
            drift = .8 + index * .031
            phase = (2 * np.pi * f * t + self.rng.uniform(0, 2 * np.pi)
                     + (2.2 + index * .11) * np.sin(t * drift + index))
            shade = math.exp(-((f - 480) / 840) ** 2)
            voice += (np.sin(phase) * shade
                      * (1 + .45 * np.sin(t * (1.7 + index * .23))) / 20)
        envelope = np.sin(np.pi * np.clip(t / length, 0, 1)) ** 2
        if rise:
            envelope *= smooth(t / max(.1, length * .75))
        motion = .5 + .5 * np.sin(t * (1.6 / max(1.0, length)) + pan * 2)
        self.add(start, voice * envelope * motion, gain, min(.95, pan + .35))
        self.add(start, voice * envelope * (1 - motion), gain, max(-.95, pan - .35))

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
        if 74 <= start < 112:
            score.pad(start + .22, (notes[1] + 12, notes[3] + 12),
                      end - start + 1.2, gain * (.32 if start >= 96 else .19),
                      width=.92, attack=.8, release=1.5)

    # D-F#-E-A begins as two incomplete gestures, then develops.
    opening = ((1.5, 62), (3, 66), (5.25, 64), (8.25, 69), (10.5, 66), (12, 64))
    for index, (when, note) in enumerate(opening):
        score.key(when, note, .105 if index < 3 else .085,
                  math.sin(index * 1.3) * .36, 3.0)
    for index, when in enumerate((7.5, 9, 10.5, 12)):
        score.bass(when, chord_at(harmony, when)[0] - 12, .70, .04 + .012 * index)
        score.crystal(when + .375, (73, 74, 78, 76)[index], .026 + .004 * index,
                      (-1) ** index * .55)

    # Pulse, harmonic figures and melody have independent entrances and rests.
    for index in range(round(DURATION / beat)):
        when = index * beat
        notes = chord_at(harmony, when)
        if 14 <= when < 54 or 74 <= when < 112:
            strength = (.105 if when < 34 else .13 if when < 54
                        else .14 if when < 96 else .16 + .06 * min(1, (when - 96) / 8))
            phrase = index % 8
            active = when < 110.5
            if active and (phrase in (0, 2, 3, 4, 6) or when >= 96):
                score.bass(when, notes[0] - 12, .58,
                           strength * (1.0 if phrase % 2 == 0 else .65))
            if active and (index % 2 == 0 or (100 <= when < 104)):
                score.drum(when, strength * (.72 if index % 4 == 0 else .44))
            if (34 <= when < 54 or 80 <= when < 110) and index % 4 == 2:
                score.drum(when, strength * .46, True, .24)
            if (40 <= when < 54 or 86 <= when < 104) and phrase in (1, 5, 7):
                score.bass(when + beat * .5, notes[1] - 12, .30, strength * .42)
                score.drum(when + beat * .5, .026, True, -.35)
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
    # Offbeat answers make the rotating lines feel like separate moving voices.
    for index, when in enumerate(np.arange(20.0625, 33.5, beat)):
        if index % 8 in (2, 6, 7):
            continue
        notes = chord_at(harmony, float(when))
        note = register(notes[(3, 1, 4, 2)[index % 4]], 69, 81)
        score.crystal(float(when), note, .035 + .008 * (index % 4 == 0),
                      (-1) ** index * .68, 1.2)

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
        if index % 6 in (1, 4):
            answer = register(notes[(index + 2) % len(notes)], 69, 83)
            score.crystal(float(when + beat / 4), answer, .043,
                          -math.sin(index * 2.399) * .78, 1.1)

    # Sine/harmonics: withdraw busy keys and let longer notes breathe.
    for index, (when, note, length) in enumerate(((55.5, 66, 3.7), (60, 69, 3.4),
                                               (64.5, 68, 3.8), (69, 66, 3.4))):
        score.ribbon(when, note, length, .068, (-1) ** index * .22)
        score.key(when + .75, note - 12, .065, (-1) ** index * -.4, 3.1)
    for index, when in enumerate((55.5, 58.5, 63, 66, 70.5, 72)):
        notes = chord_at(harmony, when)
        score.key(when, register(notes[(index + 1) % len(notes)], 62, 76),
                  .045, math.sin(index * 1.4) * .45, 2.5)
    # A slower pulse remains beneath the harmonic wave, then gathers momentum.
    for index, when in enumerate(np.arange(60, 73.5, beat)):
        notes = chord_at(harmony, float(when))
        if index % 4 in (0, 3):
            score.bass(float(when), notes[0] - 12, .65, .065 + .025 * (when - 60) / 14)
        if index % 4 in (1, 2):
            score.crystal(float(when), register(notes[index % len(notes)], 64, 80),
                          .027 + .015 * (when - 60) / 14, math.sin(index * .8) * .7, 1.9)

    # Folded corolla: wider interlocking figures and the complete upper theme.
    for index, when in enumerate(np.arange(74.25, 103.875, beat / 2)):
        if index % 16 in (3, 7, 12, 15) and when < 96:
            continue
        notes = chord_at(harmony, float(when))
        note = register(notes[(0, 2, 1, 3, 2, 4, 1, 3)[index % 8] % len(notes)], 62, 81)
        rise = float(np.clip((when - 96) / 8, 0, 1))
        score.key(float(when), note, .070 + .045 * rise,
                  math.sin(index * 1.47) * .70, 1.8, False)
        if index % 4 in (1, 3) and (when >= 86 or index % 8 == 3):
            answer = register(notes[(index + 3) % len(notes)], 69, 83)
            score.crystal(float(when + beat / 4), answer, .038 + .032 * rise,
                          -math.sin(index * 1.47) * .82, 1.05)
    for begin, transpose, strength in ((76.5, 0, .105), (85.5, -12, .09), (94.5, 0, .11)):
        for index, note in enumerate((74, 78, 76, 81)):
            score.ribbon(begin + index * beat * 2, note + transpose,
                         1.7, strength, math.sin(index * 1.2) * .28)

    # Short pitched breaths underline the visual changes without repeated crashes.
    for cue, low, high in ((14, 160, 430), (34, 210, 620),
                           (54, 460, 230), (74, 190, 590)):
        score.sweep(cue - .85, .95, low, high, .018, -.2)
        score.wind(cue - 1.2, 1.3, .055, .35, True)
        score.key(cue, register(chord_at(harmony, cue)[1], 62, 74), .09, .22, 2.4)
        score.dip(cue - .34, cue - .12, cue - .045, cue + .04,
                  .30 if cue == 54 else .52)
    score.dip(95.55, 95.82, 95.94, 96.07, .28)
    score.sweep(96, 3.2, 130, 400, .018, -.28)
    score.sweep(100.3, 3.5, 250, 860, .035, .26)
    score.wind(99.5, 4.45, .12, -.3, True)
    for index, when in enumerate((100.5, 102, 102.75, 103.125, 103.5, 103.75)):
        score.drum(when, .08 + .014 * index)

    # 104: the star opens; a broad chord carries a slower, sparkling orbit.
    score.dip(103.79, 103.92, 103.965, 104.015, .18)
    score.impact(104, .24, .85)
    score.bass(104, 38, 2.8, .23)
    for index, note in enumerate((62, 69, 73, 78, 80, 88)):
        score.key(104 + index * .045, note, .12 if index < 4 else .055,
                  -.62 + index * .24, 4.2)
    for index, (when, note) in enumerate(((105.75, 78), (107.25, 76), (109.5, 74))):
        score.ribbon(when, note, 2.4, .105 - index * .015, .18 - index * .18)
    for index, when in enumerate(np.arange(104.375, 110.75, beat / 2)):
        if index % 8 in (3, 7):
            continue
        note = (74, 81, 78, 80, 73, 78, 76, 81)[index % 8]
        score.crystal(float(when), note, .072 - .022 * (when - 104) / 7,
                      math.sin(index * 1.14) * .84, 1.7)
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
        score.wind(cue + .2, 1.4, .055, pan)
        score.sweep(cue + .5, 1.2, 210, 410, .012, pan)
    # Long air gestures cross shorter crystalline letters, leaving real gaps.
    for when, length, pan, gain in ((.2, 6.8, -.5, .085), (7.7, 7.9, .45, .10),
                                    (17, 6.1, -.3, .065), (24, 7.7, .4, .075)):
        score.wind(when, length, gain, pan)
    for phrase, begin in enumerate((3.8, 9.4, 13.7)):
        notes = chord_at(harmony, begin)
        for index in range(4):
            note = register(notes[(index + phrase) % len(notes)], 67, 83)
            score.crystal(begin + index * beat / 2, note, .032 - index * .004,
                          -.65 + index * .42, 1.6)

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
    for index, when in enumerate(np.arange(16 + beat / 2, 31.5, beat / 2)):
        if index % 12 in (3, 6, 9, 10, 11):
            continue
        notes = chord_at(harmony, float(when))
        note = register(notes[(0, 2, 1, 3, 2, 4)[index % 6] % len(notes)], 64, 83)
        score.crystal(float(when), note, .035 + .012 * (index % 6 == 0),
                      math.sin(index * 1.13) * .76, 1.35)

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
    for index, (begin, length, pan) in enumerate(((32.2, 1.8, -.7), (35.4, 1.6, .65),
                                                 (38.6, 1.5, -.45), (40.4, 2.2, .5))):
        score.wind(begin, length, .10 + index * .025, pan, True)
        notes = chord_at(harmony, begin)
        for part in range(5):
            note = register(notes[(4 - part) % len(notes)], 66, 83)
            score.crystal(begin + .18 + part * .14, note, .043 + index * .005,
                          pan * (1 - part * .45), .95)
    for index, when in enumerate((40.67, 41, 41.33, 41.67, 42, 42.33, 42.5, 42.67)):
        score.bass(when, 35, .30, .07 + index * .01)
        score.drum(when, .045 + index * .007, index % 2 == 1, .18)
    score.wind(41.7, 1.1, .13, .2, True)
    score.dip(42.7, 42.84, 42.94, 43.015, .18)
    score.impact(43, .34, .42)
    # The pause includes reverberation, giving the shattering room to read.
    score.dip(43.18, 43.48, 44.18, 44.65, .025)

    # Drift: sparse warm fragments answer across a wide stereo field.
    drift = ((45.3, 71), (47.8, 67), (51.2, 64), (54.3, 69),
             (57.1, 66), (60.2, 71), (62.3, 64))
    for index, (when, note) in enumerate(drift):
        score.key(when, note, .052, math.sin(index * 2.399) * .78, 3.7)
    for when, pan in ((47, -.6), (53.3, .55), (59.5, -.3)):
        score.wind(when, 3.2, .055, pan)
    score.ribbon(58.2, 66, 3.6, .035, -.3)
    for index, (when, note) in enumerate(((46.1, 78), (51.9, 76), (57.9, 78), (62.8, 76))):
        score.crystal(when, note, .025, (-1) ** index * .85, 2.1)

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
    score.wind(62.7, 3.8, .09, -.6, True)
    score.wind(68.2, 4.5, .11, .5, True)
    score.wind(73.2, 4.7, .13, -.3, True)
    for index, when in enumerate(np.arange(64 + beat / 2, 77.85, beat / 2)):
        amount = (when - 64) / 14
        if index % 6 in (3, 5) and when < 70:
            continue
        notes = chord_at(harmony, float(when))
        note = register(notes[(0, 1, 3, 2, 4, 1)[index % 6] % len(notes)], 64, 81)
        score.crystal(float(when), note, .026 + .029 * amount,
                      math.sin(index * (.54 + amount * .32)) * .84, 1.2)

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
        if when >= 82 and index % 6 in (2, 5):
            score.bass(float(when), notes[0] - 12, .48, .07 + .045 * amount)
        if index % 6 in (1, 4) or (when >= 88 and index % 6 == 5):
            note = register(notes[(index + 3) % len(notes)], 69, 83)
            score.crystal(float(when + beat / 4), note, .035 + .035 * amount,
                          -math.sin(index * 1.73) * .86, 1.1)
        if when >= 86 and index % 6 in (1, 3, 5):
            score.drum(float(when), .024 + .020 * amount, True, -.30)
    for index, (when, note, length) in enumerate(((78.67, 76, 2.4), (81.33, 83, 2.4),
                                               (84, 79, 2.4), (86.67, 78, 2.4),
                                               (89.33, 76, 2.5), (92, 78, 1.8))):
        score.ribbon(when, note, length, .095 + index * .008, math.sin(index * .9) * .3)
    for index, when in enumerate((79.5, 83.5, 87.5, 91.3)):
        score.sweep(when, .8, 210 + index * 35, 520 + index * 55,
                    .014 + index * .003, (-1) ** index * .48)
    score.sweep(91.9, 1.9, 230, 790, .032, .25)
    score.wind(78.3, 5.2, .085, .5)
    score.wind(84.1, 5.6, .11, -.5, True)
    score.wind(90.1, 3.8, .17, .35, True)
    for cue in (16, 32, 64, 78):
        score.dip(cue - .28, cue - .09, cue - .03, cue + .055, .60)
    score.dip(93.58, 93.82, 93.93, 94.025, .24)

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
    # The wings retain a few luminous moving threads inside the broad release.
    for phrase, begin in enumerate((94.67, 98.67, 102.67)):
        notes = chord_at(harmony, begin)
        for index in range(6):
            note = register(notes[(index + 1) % len(notes)], 67, 83)
            score.crystal(begin + index * beat / 2, note, .05 - phrase * .009,
                          math.sin(index * .85 + phrase) * .86, 1.8)
    score.pad(94.2, (62, 67, 71, 76), 9.2, .09, width=.96, attack=1.4, release=3.0)
    score.wind(94, 6.5, .10, -.45)
    score.wind(102, 5.8, .065, .4)

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
