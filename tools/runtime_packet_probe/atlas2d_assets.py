"""Host-only configuration for a bounded two-dimensional uint24 packet atlas.

This research format is separate from the established aggregate probe. Each
page carries eight uint24 words (24 bytes); producer U1 is page/layout metadata
and U2/U3 are payload. U4 remains owned by the engine's ScreenInfo binding.
Nothing in this module imports ModSDK, starts Minecraft, or verifies game GPUs.
"""
import json
import math
from pathlib import Path
import re
import shutil
import uuid


HERE = Path(__file__).resolve().parent
WORDS_PER_PAGE = 8
BYTES_PER_PAGE = WORDS_PER_PAGE * 3
MAX_PAGES = 16384
PACKET_DIVISOR = 16777216.0
MATERIAL = "pmanim_packet_atlas2d"
DISPLAY_MATERIAL = "pmanim_packet_atlas2d_display"
DISPLAY_RECT = [0.05, 0.05, 0.90, 0.90]
PARAMETER_NAMES = ["page", "packet0", "packet1"]
QUERY_FIELDS = ["page_count", "page_start", "display_count", "word_shift"]


def default_words(page_count):
    """Make deterministic diagnostic data, including exact uint24 boundaries."""
    edges = [0, 1, 255, 256, 65535, 65536, 8388609, 16777215]
    return [list(edges) if page == 0 else [
        ((page * 104729 + word * 7919 + 0x123456) * 257) & 0xffffff
        for word in range(WORDS_PER_PAGE)] for page in range(page_count)]


def packet_parameters(words):
    """Pack eight exact uint24 dyadic fractions into two payload vec4 values."""
    if len(words) != WORDS_PER_PAGE:
        raise ValueError("each page must contain exactly 8 uint24 words")
    if any(type(word) is not int or not 0 <= word < 16777216 for word in words):
        raise ValueError("words must be integers in [0, 16777215]")
    return [[word / PACKET_DIVISOR for word in words[offset:offset + 4]]
            for offset in (0, 4)]


def _layout(page_count, screen_size, texels_per_word):
    """Fit a grid without clamping or dropping logical word cells.

    A page occupies eight horizontal cells in one grid row. Prefer the requested
    square cell size, then halve to two or one texels if the screen requires it.
    Within that density choose the grid whose aspect most closely fits the
    physical screen. The finite search is bounded by the screen's page columns.
    """
    for density in (4, 2, 1):
        if density > texels_per_word:
            continue
        max_columns = min(page_count, screen_size[0] // (WORDS_PER_PAGE * density))
        max_rows = screen_size[1] // density
        if not max_columns or not max_rows or max_columns * max_rows < page_count:
            continue
        candidates = []
        for columns in range(1, max_columns + 1):
            rows = (page_count + columns - 1) // columns
            if rows > max_rows:
                continue
            # Equal relative use of screen width/height makes a balanced atlas.
            aspect = WORDS_PER_PAGE * columns * screen_size[1] / (rows * screen_size[0])
            candidates.append((abs(math.log(aspect)), columns * rows - page_count, columns, rows))
        _, empty_pages, columns, rows = min(candidates)
        return {"kind": "uint24_atlas_2d", "version": 1,
                "columns": columns, "rows": rows,
                "logical_width": columns * WORDS_PER_PAGE, "logical_height": rows,
                "texels_per_word": density, "requested_texels_per_word": texels_per_word,
                "capacity_pages": columns * rows, "empty_pages": empty_pages,
                "words_per_page": WORDS_PER_PAGE, "bytes_per_page": BYTES_PER_PAGE,
                "page_order": "row_major_from_uv_y_zero",
                "word_order": "left_to_right", "byte_order": "big_endian_rgb"}
    raise ValueError("screen cannot fit every atlas word at one texel per word")


def _pass(material, width=1.0, height=1.0):
    return {"render_target": {"width": width, "height": height},
            "material": material, "depth_enable": False}


def atlas2d_config(page_count=4, screen_size=(720, 1080), words=None,
                   namespace=None, display_rect=None, texels_per_word=4,
                   display_count=128):
    """Return isolated AddPostProcess dictionaries and a complete layout receipt.

    Producer U1: [page_index, page_count, page_columns, page_rows].
    Producer U2/U3: the page's eight words divided by 2**24.
    Consumer U1: query=[page_count, page_start, display_count, word_shift].
    Consumer U2: top-left screen rectangle [left, top, width, height].
    Consumer U3: [page_columns, page_rows, 0, 0].

    Each display row contains all 24 bytes of one page, as grayscale cells.
    Queries do not wrap pages: rows beyond page_count are zero. Shifted words
    wrap within their eight-word page; channel order stays big endian RGB.
    ``select(*query[1:])`` still uploads three positional query controls. A
    runtime must restore producer metadata from ``page_uniforms`` and consumer
    layout from ``display_layout``, and retain ``atlas_layout`` in its snapshot.
    The legacy AggregateProbe's hardcoded one-dimensional metadata needs that
    explicit adaptation before it can run these shaders.
    """
    if type(page_count) is not int or not 1 <= page_count <= MAX_PAGES:
        raise ValueError("page_count must be an integer in [1, 16384]")
    if (len(screen_size) != 2 or
            any(type(value) is not int or value <= 0 for value in screen_size)):
        raise ValueError("screen_size must contain positive integer physical dimensions")
    if type(texels_per_word) is not int or texels_per_word not in (1, 2, 4):
        raise ValueError("texels_per_word must be 1, 2 or 4")
    if type(display_count) is not int or not 1 <= display_count <= MAX_PAGES:
        raise ValueError("display_count must be an integer in [1, 16384]")
    rect = list(DISPLAY_RECT if display_rect is None else display_rect)
    if (len(rect) != 4 or any(type(value) not in (int, float) or not math.isfinite(value)
                              for value in rect) or min(rect[:2]) < 0 or
            min(rect[2:]) <= 0 or rect[0] + rect[2] > 1 or rect[1] + rect[3] > 1):
        raise ValueError("display_rect must be a finite positive rectangle inside the screen")
    window_count = min(page_count, display_count)
    if rect[2] * screen_size[0] < BYTES_PER_PAGE or rect[3] * screen_size[1] < window_count:
        raise ValueError("display rectangle needs at least one physical pixel per byte cell and page row")
    layout = _layout(page_count, screen_size, texels_per_word)
    namespace = namespace or "pmanim_packet_atlas2d_%d_%s" % (page_count, uuid.uuid4().hex[:12])
    if not isinstance(namespace, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", namespace) is None:
        raise ValueError("namespace must be a nonempty ASCII process identifier")
    words = default_words(page_count) if words is None else [list(row) for row in words]
    if len(words) != page_count:
        raise ValueError("word page count must match page_count")
    # Validate all pages before producing any externally usable process config.
    packets = [packet_parameters(row) for row in words]
    target_pixels = [layout["logical_width"] * layout["texels_per_word"],
                     layout["logical_height"] * layout["texels_per_word"]]
    # A small subpixel bias keeps both floor() and nearest-integer allocation at
    # the intended integer size after float32 transport (e.g. 632/1080 can round
    # to a product just below 632). This matters at one texel per logical cell.
    ratios = [min(1.0, (target_pixels[index] + 0.25) / float(screen_size[index]))
              for index in (0, 1)]
    columns, rows = layout["columns"], layout["rows"]
    page_uniforms = [[float(page), float(page_count), float(columns), float(rows)]
                     for page in range(page_count)]
    names = [namespace + "_page_%05d" % page for page in range(page_count)]
    processes, connections = [], []
    for page, packet in enumerate(packets):
        parameters = [{"name": "page", "value": page_uniforms[page],
                       "range": [0.0, float(MAX_PAGES)]}]
        parameters.extend({"name": PARAMETER_NAMES[index + 1], "value": value,
                           "range": [0.0, 1.0]} for index, value in enumerate(packet))
        processes.append({"name": names[page], "enable": False, "paras": parameters,
                          "pass_array": [_pass(MATERIAL, *ratios)]})
        if page:
            connections.append([names[page - 1], 0, names[page], 0, 3])
    query = [float(page_count), 0.0, float(window_count), 0.0]
    display_layout = [float(columns), float(rows), 0.0, 0.0]
    display_name = namespace + "_display"
    processes.append({"name": display_name, "enable": False, "paras": [
        {"name": "query", "value": query, "range": [0.0, float(MAX_PAGES)]},
        {"name": "display_rect", "value": rect, "range": [0.0, 1.0]},
        {"name": "atlas_layout", "value": display_layout, "range": [0.0, float(MAX_PAGES)]}],
        "pass_array": [_pass(DISPLAY_MATERIAL)]})
    connections.append([names[-1], 0, display_name, 0, 3])
    expected = [[channel for word in row for channel in
                 ((word >> 16) & 255, (word >> 8) & 255, word & 255)] for row in words]
    return {"transport": "atlas2d", "pages": page_count, "words": words, "expected_bytes": expected,
            "processes": processes, "connections": connections, "producer_names": names,
            "display_name": display_name, "namespace": namespace,
            "parameter_names": list(PARAMETER_NAMES), "page_uniforms": page_uniforms,
            "display_rect_norm": rect, "target_pixels": target_pixels,
            "screen_size": list(screen_size), "packet_divisor": int(PACKET_DIVISOR),
            "words_per_page": WORDS_PER_PAGE, "bytes_per_page": BYTES_PER_PAGE,
            "payload_bytes": page_count * BYTES_PER_PAGE, "max_pages": MAX_PAGES,
            "byte_order": "big_endian_rgb", "query": query,
            "query_fields": list(QUERY_FIELDS), "display_layout": display_layout,
            "atlas_layout": layout, "layout": dict(layout), "gpu_verified": False}


def window_queries(config, word_shift=0):
    """Enumerate fixed-height, nonoverlapping windows including the final page."""
    if type(word_shift) is not int:
        raise ValueError("word_shift must be an integer")
    count = int(config["query"][2])
    return [[float(config["pages"]), float(start), float(count), float(word_shift)]
            for start in range(0, config["pages"], count)]


def _material(fragment):
    return {"vertexShader": "shaders/uv_fullscreen.vertex", "fragmentShader": "shaders/" + fragment,
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": index, "textureWrap": "Clamp", "textureFilter": "Point"}
                              for index in (0, 1, 3)],
            "states": ["DisableDepthTest", "DisableDepthWrite"], "msaaSupport": "Both"}


def build_atlas2d_assets(resource_pack, page_count=4, screen_size=(720, 1080), **options):
    """Install only new research materials/shaders into an owned isolated probe."""
    resource = Path(resource_pack).resolve()
    marker = resource.parent / ".pmanim_packet_probe.json"
    if resource.name != "resource_pack" or not marker.is_file():
        raise ValueError("atlas2d resources require an isolated marked packet probe")
    ownership = json.loads(marker.read_text(encoding="utf-8"))
    if ownership.get("kind") != "pmanim_runtime_packet_probe":
        raise ValueError("resource parent is not owned by the packet probe")
    config = atlas2d_config(page_count, screen_size, **options)
    path = resource / "materials/postprocess.material"
    materials = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    materials[MATERIAL] = _material("atlas2d.fragment")
    materials[DISPLAY_MATERIAL] = _material("atlas2d_display.fragment")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materials, indent=2) + "\n", encoding="utf-8")
    for filename in ("atlas2d.fragment", "atlas2d_display.fragment"):
        destination = resource / "shaders/glsl" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / filename, destination)
    return config
