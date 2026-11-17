"""Host resources for separately parameterized, small-uniform postprocess draws.

Each process draws one tile directly from two payload vec4 values and copies
TEXTURE_0 elsewhere. There is no atlas, atlas consumer, or explicit pass link.
Shared shader source still means independently named process parameter sets;
``shader_mode='distinct'`` also supplies separate material and shader resources.
Neither mode increases the uniform limit of any individual GPU program.

All targets are full screen. A P-page configuration therefore performs P full
screen draws, even though each draw changes only its own small tile. The host
limit is an allocation guard, not a claim that Minecraft can render that scale.
"""
import json
import math
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORDS_PER_PAGE = 8
BYTES_PER_PAGE = 24
MAX_PAGES = 10000
PACKET_DIVISOR = 16777216.0
MATERIAL = "pmanim_packet_uniform_split"
DISPLAY_RECT = [0.05, 0.05, 0.90, 0.90]
PARAMETER_NAMES = ["tile", "packet0", "packet1"]
SCREEN_SIZE = (720, 1080)
SHADER_MODES = ("shared", "distinct")


def _positive_size(screen_size):
    if not isinstance(screen_size, (list, tuple)) or len(screen_size) != 2:
        raise ValueError("screen_size must contain two positive finite dimensions")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
           not math.isfinite(value) or value <= 0 for value in screen_size):
        raise ValueError("screen_size must contain two positive finite dimensions")
    return list(screen_size)


def _display_rect(display_rect):
    rect = list(DISPLAY_RECT if display_rect is None else display_rect)
    if len(rect) != 4 or any(isinstance(value, bool) or
                             not isinstance(value, (int, float)) or
                             not math.isfinite(value) for value in rect):
        raise ValueError("display_rect must contain four finite normalized values")
    left, top, width, height = rect
    if left < 0 or top < 0 or width <= 0 or height <= 0 or left + width > 1 or top + height > 1:
        raise ValueError("display_rect must fit inside the normalized screen")
    return rect


def default_words(page_count):
    """Use the atlas probe's deterministic payload, including uint24 edges."""
    edges = [0, 1, 255, 256, 65535, 65536, 8388609, 16777215]
    return [list(edges) if page == 0 else [
        ((page * 104729 + word * 7919 + 0x123456) * 257) & 0xffffff
        for word in range(WORDS_PER_PAGE)] for page in range(page_count)]


def packet_parameters(words):
    """Encode exactly 24 bytes in two float32-exact, dyadic payload vec4s."""
    if not isinstance(words, (list, tuple)) or len(words) != WORDS_PER_PAGE:
        raise ValueError("each page must contain exactly 8 uint24 words")
    if any(type(word) is not int or not 0 <= word < 16777216 for word in words):
        raise ValueError("words must be integers in [0, 16777215]")
    return [[word / PACKET_DIVISOR for word in words[offset:offset + 4]]
            for offset in (0, 4)]


def _layout(page_count, screen_size, rect):
    # A tile contains 24 horizontal byte cells. Choose the grid with the
    # largest smaller cell dimension in physical pixels, including spare tiles.
    area_width, area_height = screen_size[0] * rect[2], screen_size[1] * rect[3]
    columns = max(range(1, page_count + 1), key=lambda count: min(
        area_width / (count * BYTES_PER_PAGE),
        area_height / math.ceil(page_count / count)))
    rows = math.ceil(page_count / columns)
    width, height = rect[2] / columns, rect[3] / rows
    rectangles = [[rect[0] + (page % columns) * width,
                   rect[1] + (page // columns) * height, width, height]
                  for page in range(page_count)]
    return columns, rows, rectangles, [area_width / columns / BYTES_PER_PAGE,
                                      area_height / rows]


def _shader_stem(page, shader_mode):
    return "uniform_split" if shader_mode == "shared" else "uniform_split_%05d" % page


def _material_name(page, shader_mode):
    return MATERIAL if shader_mode == "shared" else MATERIAL + "_%05d" % page


def uniform_split_config(page_count=4, screen_size=SCREEN_SIZE, words=None,
                         namespace=None, display_rect=None, shader_mode="shared"):
    """Return AddPostProcess dictionaries and independently addressed tiles.

    SetParameter(process_name, 'packet0'/'packet1', vec4) uploads each page.
    U1 stores that process's normalized tile rectangle; U2/U3 hold its payload.
    U4 is deliberately unused because the target client reserves it for screen
    information. The documented four-slot ceiling still applies per shader.
    """
    if type(page_count) is not int or not 1 <= page_count <= MAX_PAGES:
        raise ValueError("page_count must be an integer in [1, 10000]")
    if shader_mode not in SHADER_MODES:
        raise ValueError("shader_mode must be 'shared' or 'distinct'")
    screen_size = _positive_size(screen_size)
    rect = _display_rect(display_rect)
    namespace = namespace or "pmanim_packet_uniform_split_%s_%d" % (shader_mode, page_count)
    if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9_]+", namespace):
        raise ValueError("namespace must contain only ASCII letters, digits and underscores")
    words = default_words(page_count) if words is None else words
    if not isinstance(words, (list, tuple)) or len(words) != page_count:
        raise ValueError("word page count must match page_count")
    # Validate every page before constructing process definitions or writing files.
    packets = [packet_parameters(row) for row in words]
    words = [list(row) for row in words]
    columns, rows, rectangles, cell_size = _layout(page_count, screen_size, rect)
    names = [namespace + "_page_%05d" % page for page in range(page_count)]
    processes = []
    for page, payload in enumerate(packets):
        paras = [{"name": "tile", "value": rectangles[page], "range": [0.0, 1.0]}]
        paras.extend({"name": PARAMETER_NAMES[index + 1], "value": value,
                      "range": [0.0, 1.0]} for index, value in enumerate(payload))
        processes.append({"name": names[page], "enable": False, "paras": paras,
                          "pass_array": [{"render_target": {"width": 1.0, "height": 1.0},
                                          "material": _material_name(page, shader_mode),
                                          "depth_enable": False}]})
    expected = [[channel for word in row for channel in
                 ((word >> 16) & 255, (word >> 8) & 255, word & 255)] for row in words]
    return {"kind": "uniform_split", "transport": "uniform_split", "name": namespace,
            "namespace": namespace, "pages": page_count, "words": words,
            "expected_bytes": expected, "processes": processes,
            "producer_names": names, "display_name": None, "connections": [],
            "parameter_names": list(PARAMETER_NAMES), "metadata_parameter": "tile",
            "metadata_values": rectangles, "rectangles_norm": rectangles,
            "display_rect_norm": rect, "screen_size": screen_size,
            "grid_columns": columns, "grid_rows": rows, "cell_pixels": cell_size,
            "packet_divisor": int(PACKET_DIVISOR), "words_per_page": WORDS_PER_PAGE,
            "bytes_per_page": BYTES_PER_PAGE, "byte_order": "big_endian_rgb",
            "query": None, "shader_mode": shader_mode,
            "shader_program_resources": 1 if shader_mode == "shared" else page_count,
            "payload_vec4s_per_process": 2, "metadata_vec4s_per_process": 1,
            "payload_scalar_slots": page_count * WORDS_PER_PAGE,
            "payload_bytes": page_count * BYTES_PER_PAGE,
            "parameter_calls_per_update": page_count * 2,
            "fullscreen_passes": page_count,
            "nominal_fragments_per_frame": page_count * screen_size[0] * screen_size[1],
            "nominal_byte_cell_pixels": cell_size[0] * cell_size[1],
            "requires_explicit_connections": False,
            "composition": "sequential_TEXTURE_0_passthrough",
            "validation": "host_configuration_only"}


def _material(stem):
    return {"vertexShader": "shaders/" + stem + ".vertex",
            "fragmentShader": "shaders/" + stem + ".fragment",
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": 0, "textureWrap": "Clamp",
                               "textureFilter": "Point"}],
            "states": ["DisableDepthTest", "DisableDepthWrite"], "msaaSupport": "Both"}


def build_uniform_split_assets(resource_pack, page_count=4, screen_size=SCREEN_SIZE,
                                words=None, namespace=None, display_rect=None,
                                shader_mode="shared"):
    """Merge dedicated resources into a marked probe; never write global config.

    Distinct mode changes resource paths and source markers per page. The
    renderer/driver may still deduplicate equivalent compiled machine code;
    independent process parameter state is the behavior the runtime must test.
    """
    resource = Path(resource_pack).resolve()
    marker = resource.parent / ".pmanim_packet_probe.json"
    if resource.name != "resource_pack" or not marker.is_file():
        raise ValueError("uniform split resources require an isolated marked packet probe")
    ownership = json.loads(marker.read_text(encoding="utf-8"))
    if ownership.get("kind") != "pmanim_runtime_packet_probe":
        raise ValueError("resource parent is not owned by the packet probe")
    config = uniform_split_config(page_count, screen_size, words, namespace,
                                  display_rect, shader_mode)
    path = resource / "materials/postprocess.material"
    materials = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    templates = {suffix: (HERE / ("uniform_split." + suffix)).read_text(encoding="utf-8")
                 for suffix in ("vertex", "fragment")}
    variants = range(page_count) if shader_mode == "distinct" else range(1)
    shader_dir = resource / "shaders/glsl"
    shader_dir.mkdir(parents=True, exist_ok=True)
    for page in variants:
        stem = _shader_stem(page, shader_mode)
        materials[_material_name(page, shader_mode)] = _material(stem)
        for suffix, source in templates.items():
            if shader_mode == "distinct":
                source = source.replace("// __multiversion__\n", "// __multiversion__\n"
                                        "#define PMANIM_UNIFORM_SPLIT_VARIANT %d\n" % page, 1)
            (shader_dir / (stem + "." + suffix)).write_text(source, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materials, indent=2) + "\n", encoding="utf-8")
    return config
