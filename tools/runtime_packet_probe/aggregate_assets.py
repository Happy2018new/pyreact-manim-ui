"""Host-side assets/config for explicit GPU accumulation of uint24 packets.

Only writes the supplied isolated probe resource pack. No ModSDK imports,
game startup, UI capture, or production-resource mutation occurs here.
"""
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
WORDS_PER_PAGE = 8
MAX_PAGES = 1024
PACKET_DIVISOR = 16777216.0
MATERIAL = "pmanim_packet_aggregate"
DISPLAY_MATERIAL = "pmanim_packet_aggregate_display"
DISPLAY_RECT = [0.05, 0.05, 0.90, 0.90]
PARAMETER_NAMES = ["page", "packet0", "packet1"]


def default_words(page_count):
    """Deterministic bytes include uint24 and byte-boundary cases on page zero."""
    edges = [0, 1, 255, 256, 65535, 65536, 8388609, 16777215]
    return [edges if page == 0 else [
        ((page * 104729 + word * 7919 + 0x123456) * 257) & 0xffffff
        for word in range(WORDS_PER_PAGE)] for page in range(page_count)]


def packet_parameters(words):
    """Normalize eight uint24 values into the two payload vec4 uniforms."""
    if len(words) != WORDS_PER_PAGE:
        raise ValueError("each page must contain exactly 8 uint24 words")
    if any(type(word) is not int or not 0 <= word < 16777216 for word in words):
        raise ValueError("words must be integers in [0, 16777215]")
    return [[word / PACKET_DIVISOR for word in words[offset:offset + 4]]
            for offset in (0, 4)]


def _pass(material, width=1.0, height=1.0):
    return {"render_target": {"width": width, "height": height},
            "material": material, "depth_enable": False}


def aggregate_config(page_count=4, screen_size=(1280, 720), words=None,
                     namespace=None, display_rect=None):
    """Return AddPostProcess dictionaries and positional connection arguments.

    Runtime may reproduce these pure dictionaries for any supported page count.
    All producers need distinct process names and the same preinstalled shader.
    """
    if type(page_count) is not int or not 1 <= page_count <= MAX_PAGES:
        raise ValueError("page_count must be an integer in [1, 1024]")
    if len(screen_size) != 2 or min(screen_size) <= 0:
        raise ValueError("screen_size must contain positive physical dimensions")
    words = default_words(page_count) if words is None else words
    if len(words) != page_count:
        raise ValueError("word page count must match page_count")
    namespace = namespace or "pmanim_packet_aggregate_%d" % page_count
    display_rect = list(DISPLAY_RECT if display_rect is None else display_rect)
    if len(display_rect) != 4 or min(display_rect[2:]) <= 0:
        raise ValueError("display_rect must be left/top/positive width/height")
    # Four physical pixels per texel tolerate render-target rounding. Normalized
    # cell-center lookups work independently of the precise target dimensions.
    target_pixels = [WORDS_PER_PAGE * 4, page_count * 4]
    ratios = [min(1.0, target_pixels[i] / float(screen_size[i])) for i in (0, 1)]
    processes, connections = [], []
    names = [namespace + "_page_%02d" % page for page in range(page_count)]
    for page, values in enumerate(words):
        packets = packet_parameters(values)
        # The engine writes ScreenInfo into EXTRA_VECTOR4 on the target client.
        # Sequential paras therefore use only U1 metadata and U2/U3 payloads.
        parameters = [{"name": "page",
                       "value": [float(page), float(page_count), float(WORDS_PER_PAGE), 0.0],
                       "range": [0.0, float(MAX_PAGES)]}]
        parameters.extend({"name": PARAMETER_NAMES[index + 1], "value": packet,
                           "range": [0.0, 1.0]} for index, packet in enumerate(packets))
        processes.append({"name": names[page], "enable": False, "paras": parameters,
                          "pass_array": [_pass(MATERIAL, *ratios)]})
        if page:
            connections.append([names[page - 1], 0, names[page], 0, 3])
    display_name = namespace + "_display"
    processes.append({"name": display_name, "enable": False, "paras": [
        {"name": "query", "value": [float(page_count), 0.0, 0.0, 0.0],
         "range": [0.0, float(MAX_PAGES)]},
        {"name": "display_rect", "value": display_rect, "range": [0.0, 1.0]}],
        "pass_array": [_pass(DISPLAY_MATERIAL)]})
    connections.append([names[-1], 0, display_name, 0, 3])
    expected = [[channel for word in row for channel in
                 ((word >> 16) & 255, (word >> 8) & 255, word & 255)] for row in words]
    return {"pages": page_count, "words": words, "expected_bytes": expected,
            "processes": processes, "connections": connections, "producer_names": names,
            "display_name": display_name, "parameter_names": PARAMETER_NAMES,
            "display_rect_norm": display_rect, "target_pixels": target_pixels,
            "screen_size": list(screen_size), "packet_divisor": int(PACKET_DIVISOR),
            "words_per_page": WORDS_PER_PAGE, "byte_order": "big_endian_rgb",
            "query": [float(page_count), 0.0, 0.0, 0.0]}


def _material(fragment):
    return {"vertexShader": "shaders/uv_fullscreen.vertex", "fragmentShader": "shaders/" + fragment,
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": index, "textureWrap": "Clamp", "textureFilter": "Point"}
                              for index in (0, 1, 3)],
            "states": ["DisableDepthTest", "DisableDepthWrite"], "msaaSupport": "Both"}


def build_aggregate_assets(resource_pack, page_count=4, screen_size=(1280, 720)):
    """Merge dedicated post materials, copy two shaders, return runtime config."""
    resource = Path(resource_pack).resolve()
    marker = resource.parent / ".pmanim_packet_probe.json"
    if resource.name != "resource_pack" or not marker.is_file():
        raise ValueError("aggregate resources require an isolated marked packet probe")
    ownership = json.loads(marker.read_text(encoding="utf-8"))
    if ownership.get("kind") != "pmanim_runtime_packet_probe":
        raise ValueError("resource parent is not owned by the packet probe")
    config = aggregate_config(page_count, screen_size)
    path = resource / "materials/postprocess.material"
    materials = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    materials[MATERIAL] = _material("aggregate.fragment")
    materials[DISPLAY_MATERIAL] = _material("aggregate_display.fragment")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materials, indent=2) + "\n", encoding="utf-8")
    for filename in ("aggregate.fragment", "aggregate_display.fragment"):
        destination = resource / "shaders/glsl" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / filename, destination)
    return config
