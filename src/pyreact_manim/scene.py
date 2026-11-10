"""A small sequential/parallel timeline for host-authored 2D scenes."""
import math
from dataclasses import replace

from .compiler.validation import MAX_FRAMES, validate_scene
from .geometry import resample


def _evaluate(animation, source, alpha):
    eased = animation.easing(alpha)
    if not math.isfinite(eased) or not 0 <= eased <= 1:
        raise ValueError("Easing must produce finite values within [0, 1]")
    return animation.evaluate(source, eased)


def _fix_frame_topology(frames):
    """Promote sparse polygon frames; preserve already dense/Create contours."""
    first_paths = frames[0]["paths"]
    sizes = [list(map(len, path["contours"])) for path in first_paths]
    for frame in frames:
        for index, path in enumerate(frame["paths"]):
            if len(path["contours"]) != len(sizes[index]):
                raise ValueError("Animation changed contour count: " + path["id"])
            sizes[index] = [max(count, len(contour))
                            for count, contour in zip(sizes[index], path["contours"])]
    for frame in frames:
        for path, counts in zip(frame["paths"], sizes):
            path["contours"] = [
                [list(point) for point in resample(contour, count)] if len(contour) < count else contour
                for contour, count in zip(path["contours"], counts)]


class Scene:
    def __init__(self, name, *, width=14.222222, height=8, background=(0.025, 0.03, 0.045)):
        self.name, self.width, self.height = name, width, height
        self.background = background
        self.cursor = 0.0
        self._initial = {}
        self._current = {}
        self._clips = []
        self._original_alpha = {}

    def add(self, name, shape):
        if self.cursor:
            raise ValueError("Declare objects before animation; use FadeIn to reveal them later")
        if name in self._initial:
            raise ValueError("Duplicate object name: " + name)
        self._initial[name] = self._current[name] = shape
        self._original_alpha[name] = (shape.fill[3], shape.stroke[3])
        return self

    def play(self, *animations, duration=1.0):
        if not animations or not math.isfinite(duration) or duration <= 0:
            raise ValueError("play needs animations and a finite positive duration")
        if len({animation.target for animation in animations}) != len(animations):
            raise ValueError("Parallel animations cannot write the same object")
        prepared = []
        for animation in animations:
            if animation.target not in self._current:
                raise ValueError("Unknown object: " + animation.target)
            source = self._current[animation.target]
            if animation.restore_opacity:
                fill_alpha, stroke_alpha = self._original_alpha[animation.target]
                source = replace(source, fill=source.fill[:3] + (fill_alpha,),
                                 stroke=source.stroke[:3] + (stroke_alpha,))
            first = animation.initial(source) if animation.initial else source
            last = _evaluate(animation, source, 1.0)
            # Vertex counts may grow when a sparse polygon morphs to a dense one;
            # export promotes every frame. Splitting/merging contours is separate.
            count = len(source.contours)
            if len(first.contours) != count or len(last.contours) != count:
                raise ValueError("Animation changed contour count: " + animation.target)
            prepared.append((animation, source, first, last))
        for animation, source, first, last in prepared:
            previously_animated = any(clip[2].target == animation.target for clip in self._clips)
            if animation.initial and not previously_animated:
                self._initial[animation.target] = first
            self._clips.append((self.cursor, self.cursor + duration, animation, source))
            self._current[animation.target] = last
        self.cursor += duration
        return self

    def wait(self, duration=1.0):
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("wait duration must be finite and positive")
        self.cursor += duration
        return self

    def at(self, timestamp):
        objects = dict(self._initial)
        for start, end, animation, source in self._clips:
            if timestamp < start:
                continue
            alpha = min(1.0, max(0.0, (timestamp - start) / (end - start)))
            objects[animation.target] = _evaluate(animation, source, alpha)
        return objects

    def export(self, fps=30):
        if not self._initial or self.cursor <= 0 or not math.isfinite(fps) or fps <= 0:
            raise ValueError("Export needs objects, positive duration and sample rate")
        # Include exact clip boundaries, even when not on the regular sample grid.
        count = max(1, math.ceil(self.cursor * fps))
        if count + 1 > MAX_FRAMES:
            raise ValueError("Scene exceeds the frame budget; reduce duration or export fps")
        timestamps = {self.cursor * i / count for i in range(count + 1)}
        timestamps.update(value for clip in self._clips for value in clip[:2])
        raw = {"schema_version": 1, "name": self.name, "duration": self.cursor,
               "width": self.width, "height": self.height, "background": list(self.background),
               "frames": [{"time": t, "paths": [shape.path(name) for name, shape in self.at(t).items()]}
                          for t in sorted(timestamps)]}
        _fix_frame_topology(raw["frames"])
        return validate_scene(raw)
