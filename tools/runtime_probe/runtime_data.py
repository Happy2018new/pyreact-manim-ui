# -*- coding: utf-8 -*-
"""Developer-only, Python 2 compatible runtime PNG data producer.

No ModSDK imports are performed. The owner supplies the already acquired
post-process component and an isolated writable probe resource-pack path.
"""

import json
import os
import re
import struct
import zlib


TEXTURE_DIRECTORY = "textures/pmanim_runtime_probe"
MARKER = ".pmanim-runtime-probe.json"
MATERIAL = "pmanim_runtime_probe"
POINT_COUNT = 128
ATLAS_SIDE = 16
_SLOT = re.compile(r"\A[a-z][a-z0-9_]{0,47}\Z")
try:
    INTEGER_TYPES = (int, long)
except NameError:
    INTEGER_TYPES = (int,)


def generate_values(seed):
    """Generate 256 unsigned values inside game Python, not on the host."""
    state = int(seed) & 0xffffffff
    values = []
    for unused in range(POINT_COUNT * 2):
        state = (1664525 * state + 1013904223) & 0xffffffff
        values.append((state >> 8) & 0xffff)
    return values


def rgba_for_values(values):
    if len(values) != POINT_COUNT * 2:
        raise ValueError("Probe requires exactly 256 scalars / 128 points")
    pixels = []
    for value in values:
        if not isinstance(value, INTEGER_TYPES) or not 0 <= value <= 65535:
            raise ValueError("Scalar must be an unsigned 16-bit integer")
        pixels.append(struct.pack("BBBB", value >> 8, value & 255, 0, 255))
    return b"".join(pixels)


def _chunk(kind, payload):
    checksum = zlib.crc32(kind + payload) & 0xffffffff
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def encode_png(rgba, width=ATLAS_SIDE, height=ATLAS_SIDE):
    """Encode lossless, untagged RGBA8 PNG using only the game stdlib."""
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("RGBA byte length must match positive dimensions")
    stride = width * 4
    rows = [b"\x00" + rgba[offset:offset + stride]
            for offset in range(0, len(rgba), stride)]
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) +
            _chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + _chunk(b"IEND", b""))


def _owned_path(resource_pack, slot):
    if not _SLOT.match(slot):
        raise ValueError("Use a short lowercase ASCII probe slot")
    root = os.path.realpath(resource_pack)
    marker = os.path.join(root, MARKER)
    if not os.path.isfile(marker):
        raise ValueError("Resource pack lacks the explicit runtime-probe marker")
    with open(marker, "rb") as stream:
        metadata = json.loads(stream.read().decode("utf-8"))
    if metadata.get("probe") != "pmanim_runtime_data_v1":
        raise ValueError("Resource pack marker has a different owner")
    directory = os.path.realpath(os.path.join(root, TEXTURE_DIRECTORY))
    if not directory.startswith(root + os.sep):
        raise ValueError("Probe texture path escapes the resource pack")
    path = os.path.join(directory, slot + ".png")
    for target in (path, os.path.join(directory, slot + ".receipt.json")):
        if os.path.lexists(target) and os.path.realpath(target) != target:
            raise ValueError("Probe output must not be a symbolic link")
    return root, directory, path


def write_dataset(resource_pack, slot, seed):
    """Write and receipt a newly generated dataset; no GPU success is inferred."""
    root, directory, path = _owned_path(resource_pack, slot)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    values = generate_values(seed)
    rgba = rgba_for_values(values)
    png = encode_png(rgba)
    with open(path, "wb") as stream:
        stream.write(png)
    receipt = {
        "probe": "pmanim_runtime_data_v1", "producer": "runtime_python",
        "seed": int(seed), "slot": slot, "point_count": POINT_COUNT,
        "scalar_count": len(values), "size": [ATLAS_SIDE, ATLAS_SIDE],
        "png_crc32": "%08x" % (zlib.crc32(png) & 0xffffffff),
        "rgba_crc32": "%08x" % (zlib.crc32(rgba) & 0xffffffff),
        "texture": TEXTURE_DIRECTORY + "/" + slot,
        "absolute_png": path, "values": values,
        "gpu_verified": False,
    }
    with open(os.path.join(directory, slot + ".receipt.json"), "wb") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True).encode("utf-8"))
    return receipt


def effect_definition(name, texture, mode=0, flip_y=False):
    """mode 0: all 256 encoded texels. mode 1: decoded 128 point positions."""
    if not _SLOT.match(name):
        raise ValueError("Use a short lowercase ASCII effect suffix")
    if not texture.startswith(TEXTURE_DIRECTORY + "/"):
        raise ValueError("Probe effects only bind the owned texture namespace")
    slot = texture[len(TEXTURE_DIRECTORY) + 1:]
    if not _SLOT.match(slot):
        raise ValueError("Texture must use an owned probe slot")
    if mode not in (0, 1):
        raise ValueError("Unsupported probe display mode")
    return {
        "name": "pmanim_probe_" + name, "enable": False,
        "paras": [{"name": "probe", "value": [float(mode), float(bool(flip_y)), 0.007, 0.0]}],
        "pass_array": [{
            "render_target": {"width": 1.0, "height": 1.0},
            "material": MATERIAL, "depth_enable": False,
            "bindTexture": [{"texture": texture}],
        }],
    }


def install_effect(post_process, name, texture, mode=0, flip_y=False):
    definition = effect_definition(name, texture, mode, flip_y)
    added = bool(post_process.AddPostProcess(definition))
    enabled = bool(post_process.SetEnableByName(definition["name"], True)) if added else False
    return {"name": definition["name"], "added": added, "enabled": enabled,
            "gpu_verified": False, "definition": definition}


def disable_effect(post_process, name):
    if not _SLOT.match(name):
        raise ValueError("Use a short lowercase ASCII effect suffix")
    return bool(post_process.SetEnableByName("pmanim_probe_" + name, False))
