"""Schema 2: preserve native independent curve slots and explicit skip markers."""

import math
from pathlib import Path
import struct

from .exporter import (_reference_environment, _render_native_reference, _sha256,
                       _snapshot, _write_json)
from .sampling import (choose_subdivisions, chord_error_bound, contour_curves,
                       marker_behavior, sample_curve)


def _curve_snapshot(mobject, topology):
    paths = _snapshot(mobject, topology)
    for path in paths:
        points = path["points"]
        path["skip_markers"] = [points[i] == points[i + 1] for i in range(0, len(points) - 2, 2)]
    return paths


def _inverse_rate(rate_func, target):
    lo, hi = 0.0, 1.0
    for _ in range(80):
        middle = (lo + hi) * 0.5
        if rate_func(middle) < target:
            lo = middle
        else:
            hi = middle
    return (lo + hi) * 0.5


def _reject(output, reason, details, settings, source, animation):
    report = {"schema_version": 1, "accepted": False, "reason": reason, "details": details,
              "input": {"source": settings.source, "target": settings.target,
                        "geometry_mode": "curve_slots"}}
    if settings.render_reference:
        report["native_render"] = _render_native_reference(output, settings, source, animation)
    _write_json(output / "rejected_reference.json", report)
    raise ValueError(reason + "; see " + str(output / "rejected_reference.json"))


def _marker_candidate(curve_a, curve_b):
    """Include planar near-zeros obscured by tiny native rotated-Z roundoff.

    The 12*u*scale threshold conservatively exceeds the anchor/handle error
    from separate float32 multiply/add interpolation. It is a candidate bound,
    not a claim about an exact native equality window.
    """
    behavior = marker_behavior(curve_a, curve_b)
    if behavior["kind"] == "always_skip":
        return behavior, None
    before = [curve_a[0][k] - curve_a[1][k] for k in (0, 1)]
    after = [curve_b[0][k] - curve_b[1][k] for k in (0, 1)]
    delta = [b - a for a, b in zip(before, after)]
    denominator = sum(v * v for v in delta)
    nearest = min(1.0, max(0.0, -sum(a * d for a, d in zip(before, delta)) / denominator)) if denominator else 0.5
    distance = math.hypot(*(a + nearest * d for a, d in zip(before, delta)))
    scale = max(1.0, *(abs(v) for curve in (curve_a, curve_b) for point in curve[:2] for v in point[:2]))
    threshold = 12 * 2 ** -24 * scale
    if distance > threshold and behavior["kind"] == "never_skip":
        return behavior, None
    rate = behavior["rate_fraction"] if behavior["rate_fraction"] is not None else nearest
    return behavior, {"rate_fraction": rate, "minimum_xy_separation": distance,
                      "float32_candidate_separation_bound": threshold,
                      "kind": behavior["kind"] if behavior["kind"] != "never_skip" else "xy_roundoff_candidate"}


def export_curve_text_transform(output, settings):
    """Export native fan geometry with explicit opt-in for marker approximation."""
    if type(settings.allow_marker_approximation) is not bool:
        raise ValueError("allow_marker_approximation must be an explicit bool")
    if not settings.source or not settings.target or not 2 <= settings.frame_count <= 256:
        raise ValueError("Visible source/target and 2..256 frames are required")
    if any(not math.isfinite(v) or v <= 0 for v in
           (settings.duration, settings.width, settings.height, settings.glyph_height, settings.tolerance)):
        raise ValueError("All geometric/time settings and tolerance must be finite and positive")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = _reference_environment()
    from manimlib import Transform
    from manimlib.config import manim_config
    from .mobject_source import create_source_pair

    cache = output.parent / "manim-cache"
    cache.mkdir(parents=True, exist_ok=True)
    manim_config.directories.cache = str(cache)
    with create_source_pair(settings, output) as (source, target, source_metadata):
        animation = Transform(source, target, run_time=settings.duration)
        animation.begin()
        if animation.path_func.__name__ != "straight_path" or animation.rate_func.__name__ != "smooth":
            raise ValueError("Curve slot marker certification currently requires upstream straight_path and smooth")
        start = animation.starting_mobject.family_members_with_points()
        end = animation.target_copy.family_members_with_points()
        if not start or len(start) != len(end):
            raise ValueError("No fixed aligned glyph family to export")
        topology = []
        behaviors = []
        events = []
        for pi, (before, after) in enumerate(zip(start, end)):
            a, b = before.get_points().tolist(), after.get_points().tolist()
            if len(a) < 3 or len(a) != len(b) or len(a) % 2 != 1:
                raise ValueError("Upstream aligned point counts must stay equal and odd")
            topology.append({"id": "glyph-%d" % pi, "point_count": len(a), "curve_count": (len(a) - 1) // 2})
            path_behaviors = []
            for ci, (curve_a, curve_b) in enumerate(zip(contour_curves(a), contour_curves(b))):
                behavior, candidate = _marker_candidate(curve_a, curve_b)
                path_behaviors.append(behavior)
                if candidate is not None:
                    alpha = _inverse_rate(animation.rate_func, candidate["rate_fraction"])
                    animation.interpolate(alpha)
                    raw = source.family_members_with_points()[pi].get_points()
                    native_skip = bool((raw[ci * 2] == raw[ci * 2 + 1]).all())
                    events.append(dict(candidate, path=pi, curve=ci,
                                       alpha=alpha, time=alpha * settings.duration,
                                       native_skip_at_inverse_time=native_skip,
                                       native_anchor_handle_delta=(raw[ci * 2] - raw[ci * 2 + 1]).tolist()))
            behaviors.append(path_behaviors)
        if events and not settings.allow_marker_approximation:
            _reject(output, "Native floating-point skip windows require allow_marker_approximation=True for preview",
                    {"candidate_events": events, "full_timeline_marker_parity_verified": False},
                    settings, source, animation)
        # Previews retain true markers at ordinary sampled frames. Narrow native
        # equality windows are NOT disguised as transparent edges or point keys.
        alphas = [i / (settings.frame_count - 1) for i in range(settings.frame_count)]
        float32_times = [struct.unpack("f", struct.pack("f", a * settings.duration))[0] for a in alphas]
        if any(b <= a for a, b in zip(float32_times, float32_times[1:])):
            _reject(output, "Distinct marker key times collide after float32 upload", {"events": events},
                    settings, source, animation)
        raw_frames = []
        for alpha in alphas:
            animation.interpolate(alpha)
            raw_frames.append({"time": alpha * settings.duration, "paths": _curve_snapshot(source, topology)})

        time_error = 0.0
        marker_failures = []
        for i, (lo, hi) in enumerate(zip(alphas, alphas[1:])):
            for fraction in (0.25, 0.5, 0.75):
                alpha = lo + (hi - lo) * fraction
                animation.interpolate(alpha)
                actual = _curve_snapshot(source, topology)
                for pi, path in enumerate(actual):
                    before, after = raw_frames[i]["paths"][pi], raw_frames[i + 1]["paths"][pi]
                    for ci, (a, b, real) in enumerate(zip(before["skip_markers"], after["skip_markers"],
                                                        path["skip_markers"])):
                        if real != (a and b):
                            marker_failures.append({"alpha": alpha, "path": pi, "curve": ci,
                                                    "native_skip": real, "interpolated_skip": a and b})
                    for point, a, b in zip(path["points"], before["points"], after["points"]):
                        time_error = max(time_error, math.hypot(*[point[k] - (a[k] + (b[k] - a[k]) * fraction)
                                                                 for k in (0, 1)]))
        if marker_failures and not settings.allow_marker_approximation:
            _reject(output, "Native float32 skip bands are not representable by point-event markers",
                    {"candidate_events": events, "marker_probe_mismatches": marker_failures},
                    settings, source, animation)

        all_counts = []
        error_bound = 0.0
        for pi, info in enumerate(topology):
            counts = [1] * info["curve_count"]
            for frame in raw_frames:
                for ci, curve in enumerate(contour_curves(frame["paths"][pi]["points"])):
                    counts[ci] = max(counts[ci], choose_subdivisions(curve, settings.tolerance))
            for frame in raw_frames:
                for curve, count in zip(contour_curves(frame["paths"][pi]["points"]), counts):
                    error_bound = max(error_bound, chord_error_bound(curve, count))
            all_counts.append(counts)
        frames = []
        orientations = None
        for raw in raw_frames:
            paths = []
            for pi, path in enumerate(raw["paths"]):
                normal = path["native_unit_normal"]
                if abs(abs(normal[2]) - 1.0) > 1e-5 or max(abs(normal[0]), abs(normal[1])) > 1e-5:
                    raise ValueError("Only planar native fill normals are supported")
                curves = [{"points": sample_curve(curve, count), "skip_marker": skipped}
                          for curve, count, skipped in zip(contour_curves(path["points"]), all_counts[pi],
                                                           path["skip_markers"])]
                paths.append({"id": path["id"], "base": path["points"][0][:2], "curves": curves,
                              "fill": path["fill"], "stroke": path["stroke"], "stroke_width": 0.0,
                              "fill_border_width": path["native_fill_border_width"] * 0.01 * settings.height / 8.0,
                              "anti_alias_width": path["native_anti_alias_width"],
                              "fill_orientation": 1 if normal[2] > 0 else -1})
            current_orientations = [path["fill_orientation"] for path in paths]
            if orientations is not None and current_orientations != orientations:
                raise ValueError("Native fill orientation changes across frames; a fixed-style scene cannot represent this")
            orientations = current_orientations
            frames.append({"time": raw["time"], "paths": paths})
        scene = {"schema_version": 2, "name": settings.name, "duration": settings.duration,
                 "width": settings.width, "height": settings.height, "background": [0, 0, 0], "frames": frames}
        scene_path, raw_path = output / "scene.json", output / "upstream_control_points.json"
        _write_json(scene_path, scene)
        _write_json(raw_path, {"schema_version": 2, "coordinate_system": "XY, Y up",
                              "data_layout": "raw quadratic slots points[2*i:2*i+3], includes native move markers",
                              "topology": topology, "frames": raw_frames})
        report = {
            "schema_version": 2, "environment": environment,
            "input": {"source": settings.source, "target": settings.target, **source_metadata,
                      "per_text_height": settings.glyph_height, "duration": settings.duration,
                      "canvas": [settings.width, settings.height], "geometry_mode": "curve_slots",
                      "allow_marker_approximation": settings.allow_marker_approximation},
            "upstream_execution": {"classes": [source_metadata["mobject_class"], "manimlib.Transform"],
                                   "rate_func": "manimlib.utils.rate_functions.smooth",
                                   "path_func": "manimlib.utils.paths.straight_path",
                                   "native_fill_border": {"source": "StringMobject.fill_border_width default=0.5",
                                                          "conversion": "0.01 * native_width * (camera_frame_height / 8)",
                                                          "anti_alias_width_unit": "pixels",
                                                          "composition": "MAX border alpha after signed fill, then native 1.06 adjustment"}},
            "markers": {"raw_rule": "all three native anchor_0 components equal handle components",
                        "interpolation_rule": "exact keyframe bool; strictly inside interval skip only if both endpoints skip",
                        "affine_behaviors": behaviors, "known_floating_point_candidates": events,
                        "approximation_enabled": settings.allow_marker_approximation,
                        "full_timeline_parity_verified": False,
                        "probe_count": 3 * (len(frames) - 1), "probe_mismatch_count": len(marker_failures),
                        "probe_mismatches": marker_failures,
                        "event_time_float32_max_error_seconds": max(abs(a * settings.duration - b)
                                                                      for a, b in zip(alphas, float32_times))},
            "sampling": {"frame_count": len(frames), "requested_chord_tolerance_scene_units": settings.tolerance,
                         "max_chord_error_bound_scene_units_at_exported_frames": error_bound,
                         "measured_time_interpolation_max_control_error_scene_units": time_error,
                         "subdivisions": all_counts,
                         "vertices_per_path": [sum(n + 1 for n in counts) for counts in all_counts]},
            "artifacts": {"scene": {"file": scene_path.name, "sha256": _sha256(scene_path)},
                          "raw_upstream": {"file": raw_path.name, "sha256": _sha256(raw_path)}},
            "verification": {"real_upstream_execution": True, "native_reference_rendered": False,
                             "minecraft_pixel_parity_verified": False,
                             "full_timeline_marker_parity_verified": False,
                             "preview_uses_marker_approximation": bool(events or marker_failures),
                             "notes": ["Curve fans jointly accumulate winding; they are not independent filled paths.",
                                       "Marker candidates include exact rational zeros and planar near-zeros affected by native float32 roundoff.",
                                       "Opt-in previews retain true sampled markers but may miss narrow native equality windows between frames.",
                                       "Probe acceptance is not a proof of all native floating-point equality bands."]}}
        if settings.render_reference:
            report["native_render"] = _render_native_reference(output, settings, source, animation)
            report["verification"]["native_reference_rendered"] = True
        _write_json(output / "reference_report.json", report)
        return {"scene": scene_path, "raw_reference": raw_path, "report": output / "reference_report.json", "data": report}
