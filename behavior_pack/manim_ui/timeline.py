# -*- coding: utf-8 -*-
"""Deterministic playback clock, independent of ModSDK and rendering."""
import math
import time


def get_playback_clock(time_module=time, platform=None):
    """Select once: host Py3 perf_counter, or Windows Py2's QPC clock.

    Python 2 time.clock is elapsed real time only on Windows. Unix Python 2
    reports CPU time instead, so it is deliberately not a playback fallback.
    See https://docs.python.org/2/library/time.html#time.clock.
    """
    counter = getattr(time_module, "perf_counter", None)
    if counter is not None:
        return counter
    # ModSDK GetPlatform() returns 0 for Windows (1 iOS, 2 Android, -1 other).
    if platform == 0:
        return time_module.clock
    raise RuntimeError("Playback requires Windows Python 2 or Python 3 perf_counter")


def finite_number(value, name):
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(name + " must be finite")
    return value


class Timeline(object):
    def __init__(self, duration):
        self.duration = finite_number(duration, "duration")
        if self.duration <= 0:
            raise ValueError("duration must be positive")
        self.position = 0.0
        self.playing = False
        self.speed = 1.0
        self.loop = False
        self._anchor_time = 0.0
        self._anchor_position = 0.0

    def sample(self, now):
        if not self.playing:
            return self.position
        elapsed = max(0.0, finite_number(now, "now") - self._anchor_time)
        value = self._anchor_position + elapsed * self.speed
        if self.loop:
            self.position = value % self.duration
        elif value >= self.duration:
            self.position = self.duration
            self.playing = False
        else:
            self.position = max(0.0, value)
        return self.position

    def play(self, now):
        if self.playing:
            return
        if self.position >= self.duration:
            self.position = 0.0
        self._anchor_position = self.position
        self._anchor_time = finite_number(now, "now")
        self.playing = True

    def pause(self, now):
        self.sample(now)
        self.playing = False

    def seek(self, position, now):
        self.position = min(self.duration, max(0.0, finite_number(position, "position")))
        self._anchor_position = self.position
        self._anchor_time = finite_number(now, "now")
        return self.position

    def set_speed(self, speed, now):
        value = finite_number(speed, "speed")
        if value <= 0:
            raise ValueError("speed must be positive")
        self.sample(now)
        self.speed = value
        self._anchor_position = self.position
        self._anchor_time = finite_number(now, "now")
