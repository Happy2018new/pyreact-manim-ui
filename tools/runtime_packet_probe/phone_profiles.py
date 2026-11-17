"""Pure host plans for physical pixel sizes and fixed screenshot windows.

The default is the user's requested 720 x 1080 portrait viewport. Other sizes
are optional planning inputs only. A PC run at one of these sizes is evidence
for that PC and pixel workload; it does not simulate phone hardware or the
mobile client's UI scale. This module never resizes a window, starts Minecraft,
reads native options, or changes a frame limiter.
"""
import argparse
import json
import math


DEFAULT_PROFILE = "720x1080"
PROFILES = {
    "720x1080": {"width": 720, "height": 1080, "orientation": "portrait"},
    "1280x720": {"width": 1280, "height": 720, "orientation": "landscape"},
    "1920x1080": {"width": 1920, "height": 1080, "orientation": "landscape"},
    "2400x1080": {"width": 2400, "height": 1080, "orientation": "landscape"},
}
DISPLAY_RECT = (0.05, 0.05, 0.90, 0.90)
WORDS_PER_PAGE = 8
BYTES_PER_PAGE = WORDS_PER_PAGE * 3
NUMERIC_HEADER_BYTES = 16
DEFAULT_WINDOW_ROWS = 128


def _positive_integer(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(name + " must be a positive integer")
    return value


def fixed_windows(page_count, window_rows=DEFAULT_WINDOW_ROWS):
    """Return nonoverlapping page ranges; retain the fixed final window height.

    The final window can contain padding, so its declared display_count remains
    window_rows while checked_pages records only resident payload pages.
    """
    _positive_integer(page_count, "page_count")
    _positive_integer(window_rows, "window_rows")
    count = min(page_count, window_rows)
    return [{"page_start": start, "display_count": count,
             "checked_pages": min(count, page_count - start)}
            for start in range(0, page_count, count)]


def _axis_sample_widths(origin, extent, count):
    """Use the existing screenshot oracle's fixed cell-center sample rule."""
    widths = []
    for index in range(count):
        low = origin + index * extent / count
        high = origin + (index + 1) * extent / count
        center = math.floor((low + high) / 2)
        if high - low < 1 or not low <= center + 0.5 < high:
            widths.append(0)
        else:
            widths.append(3 if low <= center - 0.5 and center + 1.5 < high else 1)
    return min(widths)


def profile_plan(profile=DEFAULT_PROFILE, page_count=1024,
                 window_rows=DEFAULT_WINDOW_ROWS):
    """Describe capacity and screenshot sampling; make no performance claim."""
    _positive_integer(page_count, "page_count")
    _positive_integer(window_rows, "window_rows")
    if profile not in PROFILES:
        raise ValueError("unknown profile: " + str(profile))
    size = PROFILES[profile]
    width, height = size["width"], size["height"]
    left, top, area_width, area_height = DISPLAY_RECT
    window_count = min(page_count, window_rows)
    sample_width = min(
        _axis_sample_widths(left * width, area_width * width, BYTES_PER_PAGE),
        _axis_sample_widths(top * height, area_height * height, window_count))
    payload_bytes = page_count * BYTES_PER_PAGE
    return {
        "profile": profile, "orientation": size["orientation"],
        "requested_physical_client": [width, height],
        "scope": "PC physical pixel workload; phone hardware is not simulated",
        "measurement_status": "plan_only",
        "pages": page_count, "words_per_page": WORDS_PER_PAGE,
        "bytes_per_page": BYTES_PER_PAGE, "resident_payload_bytes": payload_bytes,
        "float32_capacity_with_16_byte_header": max(0, (payload_bytes - NUMERIC_HEADER_BYTES) // 4),
        "display_rect_norm": list(DISPLAY_RECT),
        "legacy_single_column_max_page_rows": math.floor(area_height * height),
        "legacy_single_column_all_pages_fit": page_count <= math.floor(area_height * height),
        "window_rows": window_count,
        "windows": fixed_windows(page_count, window_rows),
        "window_byte_cell_physical_size": [area_width * width / BYTES_PER_PAGE,
                                            area_height * height / window_count],
        "minimum_center_sample_width": sample_width,
        "all_windows_have_physical_samples": sample_width >= 1,
        "all_windows_have_3x3_samples": sample_width == 3,
        "capture_requirements": {
            "native_wgc_size": [width, height],
            "per_monitor_dpi_aware_client_size": [width, height],
            "resampling_allowed": False,
            "record_separately": ["GetScreenSize", "GetScreenViewInfo",
                                  "native_options_fps_cap", "external_fps_cap",
                                  "frame_interval_samples", "sdk_upload_cpu_time"],
        },
    }


def validate_capture_size(capture_size, physical_client_size, profile=DEFAULT_PROFILE):
    """Require native WGC and a DPI-aware client measurement to match exactly."""
    if profile not in PROFILES:
        raise ValueError("unknown profile: " + str(profile))
    expected = [PROFILES[profile]["width"], PROFILES[profile]["height"]]
    return {"passed": list(capture_size) == expected and list(physical_client_size) == expected,
            "expected": expected, "native_capture": list(capture_size),
            "physical_client": list(physical_client_size)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILES), default=DEFAULT_PROFILE)
    parser.add_argument("--pages", type=int, default=1024)
    parser.add_argument("--window-rows", type=int, default=DEFAULT_WINDOW_ROWS)
    args = parser.parse_args(argv)
    print(json.dumps(profile_plan(args.profile, args.pages, args.window_rows), indent=2))


if __name__ == "__main__":
    main()
