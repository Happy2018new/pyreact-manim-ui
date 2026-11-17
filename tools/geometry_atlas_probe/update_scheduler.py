# -*- coding: utf-8 -*-
"""Render-event scheduling and CPU/frame statistics; no native readiness fence."""
import math
import time


STAGES = ('generation_ms', 'encode_ms', 'deserialize_ms', 'combine_ms', 'attach_ms', 'total_ms')


def statistics(values, intervals=False):
    ordered = sorted(values)
    result = {'count': len(ordered)}
    if ordered:
        result.update(mean=sum(ordered) / len(ordered), min=ordered[0], max=ordered[-1],
                      p95=ordered[int((len(ordered) - 1) * .95)])
    if intervals:
        result.update(over_25_ms=sum(value > 25. for value in ordered),
                      over_33_3_ms=sum(value > 33.3 for value in ordered),
                      over_50_ms=sum(value > 50. for value in ordered))
        if ordered:
            result['p99']=ordered[int((len(ordered)-1)*.99)]
    return result


class UpdateScheduler(object):
    def __init__(self, probe, duration, interval_ms, maximum, now):
        self.probe = probe
        self.start = now
        self.until = now + duration
        self.duration = duration
        self.warm_until = now + 1.
        self.interval = interval_ms / 1000.
        self.next_due = now
        self.maximum = maximum
        self.frames = 0
        self.previous = None
        self.intervals = []
        self.fps = []
        self.uploads = []
        self.published = 0
        self.skipped = 0
        self.overruns = 0
        self.pending_skips = 0
        self.truncated = False
        self.budget_limited = False
        self.error = None
        self.stopping = False
        self.end_reason = 'duration'

    def on_frame(self, now):
        self.frames += 1
        if now >= self.warm_until and self.previous is not None:
            self.intervals.append((now - self.previous) * 1000.)
        self.previous = now
        if now >= self.warm_until and self.frames % 15 == 0:
            self.fps.append(self.probe.game.GetFps())
        if now >= self.until:
            self.stopping = True
        if self.stopping:
            if self.probe.pending_upload is None:
                self.finish(time.clock())
            return
        if now < self.next_due:
            return
        due = 1
        if self.interval > 0.:
            due += int(math.floor((now - self.next_due) / self.interval))
            self.next_due += due * self.interval
        else:
            self.next_due = now
        self.overruns += due - 1
        self.skipped += due - 1
        if self.probe.pending_upload is not None:
            self.skipped += 1
            self.pending_skips += 1
            return
        if len(self.uploads) >= self.maximum:
            self.truncated = True
            self.end_reason = 'max_updates'
            self.skipped += 1
            return
        if not self.probe.can_upload(self.probe.slot_count):
            self.truncated = True
            self.budget_limited = True
            self.end_reason = 'budget'
            self.skipped += 1
            return
        try:
            candidate = self.probe._submit_upload(
                self.probe.slot_count, self.probe.seed, (self.probe.generation + 1) & 0xffffffff)
            self.uploads.append(candidate)
            self.probe._publish_pending(time.clock())
        except (RuntimeError, ValueError, TypeError) as error:
            self.error = '%s: %s' % (type(error).__name__, error)
            self.end_reason = 'error'
            self.probe.error = self.error
            self.stopping = True
            self.finish(time.clock())

    def note_publish(self, candidate):
        self.published += 1

    def finish(self, now):
        if self.error is None:
            try:
                self.probe._dependent_query()
            except (RuntimeError, ValueError, TypeError) as error:
                self.error = '%s: %s' % (type(error).__name__, error)
                self.end_reason = 'error'
                self.probe.error = self.error
        result = {'status': 'failed' if self.error else 'completed', 'success': self.error is None,
                  'error': self.error, 'elapsed': now - self.start, 'frames': self.frames,
                  'updates': len(self.uploads), 'published': self.published,
                  'skipped_updates': self.skipped, 'overruns': self.overruns,
                  'pending_skips': self.pending_skips, 'truncated': self.truncated,
                  'budget_limited': self.budget_limited,
                  'requested_max_updates': self.maximum, 'interval_ms_requested': self.interval * 1000.,
                  'duration_seconds': self.duration, 'duration_completed': now>=self.until,
                  'end_reason': 'error' if self.error else self.end_reason,
                  'run_serial': self.probe.update_run_serial,
                  'policy': self.probe.update_policy, 'publish_delay_ms': self.probe.publish_delay_ms,
                  'seed': self.probe.seed, 'generation': self.probe.generation,
                  'geometry_name': self.probe.geometry_name,
                  'geometry_build_serial': self.probe.geometry_build_serial,
                  'query': list(self.probe.query_value), 'salt2': self.probe.dimensions[3],
                  'fps': statistics(self.fps), 'interval_ms': statistics(self.intervals, True),
                  'upload_interval_ms': statistics([
                      (self.uploads[index]['started_at']-self.uploads[index-1]['started_at'])*1000.
                      for index in range(1,len(self.uploads))], True),
                  'publish_interval_ms': statistics([
                      (self.uploads[index]['published_at']-self.uploads[index-1]['published_at'])*1000.
                      for index in range(1,len(self.uploads))
                      if self.uploads[index]['published_at'] is not None and
                         self.uploads[index-1]['published_at'] is not None], True),
                  'effective_upload_hz': len(self.uploads)/(now-self.start) if now>self.start else 0.,
                  'effective_publish_hz': self.published/(now-self.start) if now>self.start else 0.,
                  'timings': {stage: statistics([item['timings'][stage] for item in self.uploads])
                              for stage in STAGES},
                  'uploads': [self.probe.upload_receipt(item) for item in self.uploads],
                  'gpu_completion_fence': False, 'every_generation_pixel_verified': False,
                  'wait_semantics': 'CPU elapsed time before publication; not GPU readiness'}
        self.probe.last_updates = result
        self.probe.updates = None
