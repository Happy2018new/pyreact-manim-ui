"""Build an isolated uniform atlas with explicit preservation of its input RGBA.

Host-only research tooling. The data producers never sample the scene; the
consumer receives its data and saved incoming picture through separate links.
"""
import json
from pathlib import Path
import shutil

from atlas2d_assets import atlas2d_config, MATERIAL


HERE = Path(__file__).resolve().parent
SAVE_MATERIAL = "pmanim_isolated_save"
CONSUMER_MATERIAL = "pmanim_isolated_consumer"
REFERENCE_MATERIAL = "pmanim_isolated_reference"


def _material(filename, samplers):
    return {"vertexShader": "shaders/uv_fullscreen.vertex",
            "fragmentShader": "shaders/" + filename,
            "vertexFields": [{"field": "Position"}, {"field": "UV0"}],
            "samplerStates": [{"samplerIndex": index, "textureWrap": "Clamp",
                               "textureFilter": "Point"} for index in samplers],
            "states": ["DisableDepthTest", "DisableDepthWrite"], "msaaSupport": "Both"}


def _pass(material):
    return {"render_target": {"width": 1.0, "height": 1.0},
            "material": material, "depth_enable": False}


def isolated_config(screen_size=(720, 1080), namespace=None, payload_bytes=96):
    """One complete, independently addressed array; mode 0 restores input RGBA.

    Mode 1 displays identity queries, mode 2 dependent byte queries. A window
    has 24 columns and ceil(query_count/24) rows; out-of-range cells are zero.
    Storage is rounded up to complete 24-byte pages but the array length is not.
    """
    if type(payload_bytes) is not int or not 1 <= payload_bytes <= 393216:
        raise ValueError("payload_bytes must be an integer in [1, 393216]")
    pages = (payload_bytes + 23) // 24
    config = atlas2d_config(pages, screen_size=screen_size, namespace=namespace,
                            texels_per_word=1, display_count=min(pages, 128))
    name = config["namespace"]
    saved = name + "_saved_scene"
    save = {"name": saved, "enable": False, "paras": [],
            "pass_array": [_pass(SAVE_MATERIAL)]}
    consumer = config["processes"][-1]
    consumer["pass_array"] = [_pass(CONSUMER_MATERIAL)]
    query = [0.0, 0.0, float(min(payload_bytes, 3072)), 7.0]
    layout = [float(config["atlas_layout"]["columns"]),
              float(config["atlas_layout"]["rows"]), float(payload_bytes), 0.0]
    consumer["paras"] = [
        {"name": "query", "value": query, "range": [0.0, 393216.0]},
        {"name": "display_rect", "value": config["display_rect_norm"], "range": [0.0, 1.0]},
        {"name": "atlas_layout", "value": layout, "range": [0.0, 393216.0]}]
    config["processes"].insert(0, save)
    config["connections"].append([saved, 0, config["display_name"], 0, 4])
    config.update(transport="isolated_atlas", saved_scene_name=saved,
                  query=query, display_layout=layout,
                  payload_bytes=payload_bytes, storage_bytes=pages * 24,
                  scene_sampler=4, data_sampler=3,
                  verification_scope="not_yet_verified", gpu_verified=False)
    return config


def reference_process(namespace="pmanim_isolated_reference"):
    """Deterministic visual fixture, independent of every uploaded data byte."""
    return {"name": namespace, "enable": False,
            "paras": [{"name": "phase", "value": 0.0, "range": [0.0, 255.0]}],
            "pass_array": [_pass(REFERENCE_MATERIAL)]}


def build_isolated_assets(resource_pack, **options):
    """Install only research shaders and runtime in an explicitly owned probe."""
    resource = Path(resource_pack).resolve()
    marker = resource.parent / ".pmanim_packet_probe.json"
    if resource.name != "resource_pack" or not marker.is_file():
        raise ValueError("isolated assets require an owned packet probe")
    if json.loads(marker.read_text(encoding="utf-8")).get("kind") != "pmanim_runtime_packet_probe":
        raise ValueError("invalid packet probe ownership marker")
    runtime = resource.parent / "behavior_pack/packet_probe"
    if not runtime.is_dir() or not (HERE / "isolated_runtime.py").is_file():
        raise ValueError("packet probe runtime is missing")
    config = isolated_config(**options)
    path = resource / "materials/postprocess.material"
    materials = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    materials.update({MATERIAL: _material("atlas2d.fragment", (3,)),
                      SAVE_MATERIAL: _material("isolated_copy.fragment", (0,)),
                      CONSUMER_MATERIAL: _material("isolated_consumer.fragment", (3, 4)),
                      REFERENCE_MATERIAL: _material("isolated_reference.fragment", ())})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(materials, indent=2) + "\n", encoding="utf-8")
    for filename in ("atlas2d.fragment", "isolated_copy.fragment",
                     "isolated_consumer.fragment", "isolated_reference.fragment"):
        destination = resource / "shaders/glsl" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / filename, destination)
    shutil.copyfile(HERE / "isolated_runtime.py", runtime / "isolated_runtime.py")
    return config
