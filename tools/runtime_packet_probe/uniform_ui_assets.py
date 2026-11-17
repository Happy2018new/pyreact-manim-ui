"""Small-screen direct actor-uniform resources, without image carriers or RTs.

Every screen has at most 64 paperdolls. Splitting creation into screens is an
experiment, not a documented way to bypass an engine-wide UI control limit.
"""
import json
from pathlib import Path
import shutil

from uniform_split_assets import uniform_split_config


HERE = Path(__file__).resolve().parent
MAX_SLOTS = 2048
SLOTS_PER_SCREEN = 64
UI_NAMESPACE = "pmanim_packet_uniform_ui"
MATERIAL = "pmanim_packet_uniform_ui"


def uniform_ui_config(slot_count=128, screen_size=(720, 1080), display_rect=None,
                      slots_per_screen=SLOTS_PER_SCREEN):
    """Return independent identifiers and small UI definitions for the same bytes."""
    if type(slot_count) is not int or not 1 <= slot_count <= MAX_SLOTS:
        raise ValueError("slot_count must be an integer in [1, 2048]")
    if type(slots_per_screen) is not int or not 1 <= slots_per_screen <= SLOTS_PER_SCREEN:
        raise ValueError("slots_per_screen must be an integer in [1, 64]")
    spatial = uniform_split_config(slot_count, screen_size=screen_size, display_rect=display_rect)
    fields = ("pages", "words", "expected_bytes", "rectangles_norm", "display_rect_norm",
              "screen_size", "grid_columns", "grid_rows", "cell_pixels", "packet_divisor",
              "words_per_page", "bytes_per_page", "byte_order", "payload_scalar_slots",
              "payload_bytes", "parameter_calls_per_update")
    config = {key: spatial[key] for key in fields}
    screens = []
    for index, offset in enumerate(range(0, slot_count, slots_per_screen)):
        screens.append({"index": index, "key": "slice_%03d" % index,
                        "definition": UI_NAMESPACE + ".main_%03d" % index,
                        "offset": offset, "count": min(slots_per_screen, slot_count - offset),
                        "root_layer": 1000 + index * 128})
    config.update({"kind": "uniform_ui", "transport": "uniform_ui", "slot_count": slot_count,
                   "slots_per_screen": slots_per_screen, "screens": screens,
                   "ui_namespace": UI_NAMESPACE, "screen_count": len(screens),
                   "runtime_class": "packet_probe.uniform_ui_runtime.UniformUISlice",
                   "identifiers": ["pmanim_packet_uniform_ui:slot_%05d" % index
                                   for index in range(slot_count)],
                   "payload_uniform_indices": [1, 2], "rectangle_uniform_index": 3,
                   "payload_vec4s_per_draw": 2, "metadata_vec4s_per_draw": 1,
                   "shader_program_resources": 1, "shader_mode": "shared",
                   "target_pixels": list(config['screen_size']),
                   "draw_calls": slot_count, "fullscreen_passes": 0,
                   "image_carriers": 0, "query": None,
                   "validation": "host_configuration_only"})
    return config


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _control(kind, size, layer=0, **values):
    result = {"type": kind, "size": list(size), "offset": [0, 0],
              "anchor_from": "top_left", "anchor_to": "top_left", "layer": layer}
    result.update(values)
    return result


def _ui(config):
    definitions = {"namespace": UI_NAMESPACE}
    for screen in config["screens"]:
        controls = []
        for slot in range(screen["count"]):
            canvas = _control("custom", (270, 16), layer=1,
                              renderer="netease_paper_doll_renderer", rotation="none",
                              init_rot_x=0.0, init_rot_y=0.0, init_rot_z=0.0,
                              screen_scale=1.0, enable_scissor_test=True)
            controls.append({"slot_%03d" % slot: _control(
                "panel", (270, 16), layer=1 + slot * 2, visible=False,
                controls=[{"canvas": canvas}])})
        # A transparent panel root has no full-screen image/background to cover
        # prior screens. Root and local layers form a stable global ordering.
        definitions["main_%03d" % screen["index"]] = _control(
            "panel", ("100%", "100%"), layer=screen["root_layer"], controls=controls)
    return definitions


def _write_ui_and_material(resource, config):
    ui_path = resource / "ui/pmanim_packet_uniform_ui.json"
    defs_path = resource / "ui/_ui_defs.json"
    defs = json.loads(defs_path.read_text(encoding="utf-8")) if defs_path.is_file() else {"ui_defs": []}
    relative_ui = "ui/pmanim_packet_uniform_ui.json"
    if relative_ui not in defs["ui_defs"]:
        defs["ui_defs"].append(relative_ui)
    material_path = resource / "materials/entity.material"
    materials = json.loads(material_path.read_text(encoding="utf-8")) if material_path.is_file() else {
        "materials": {"version": "1.0.0"}}
    materials["materials"][MATERIAL + ":entity_static"] = {
        "vertexShader": "shaders/uniform_ui.vertex", "fragmentShader": "shaders/uniform_ui.fragment",
        "+states": ["DisableCulling", "DisableDepthTest", "DisableDepthWrite"]}
    _write(ui_path, _ui(config))
    _write(defs_path, defs)
    _write(material_path, materials)


def _write_entity_resources(resource, behavior, config):
    _write(resource / "models/entity/pmanim_packet_uniform_ui.geo.json", {
        "format_version": "1.12.0", "minecraft:geometry": [{
            "description": {"identifier": "geometry.pmanim_packet_uniform_ui",
                            "texture_width": 16, "texture_height": 16,
                            "visible_bounds_width": 8, "visible_bounds_height": 8,
                            "visible_bounds_offset": [0, 0.5, 0]},
            "bones": [{"name": "root", "pivot": [0, 0, 0], "cubes": [{
                "origin": [-16, 0, 0], "size": [32, 18, 0],
                "uv": {"south": {"uv": [0, 0], "uv_size": [16, 16]}}}]}]}]})
    controller = "controller.render.pmanim_packet_uniform_ui"
    _write(resource / "render_controllers/pmanim_packet_uniform_ui.render_controllers.json", {
        "format_version": "1.8.0", "render_controllers": {controller: {
            "geometry": "Geometry.default", "materials": [{"*": "Material.default"}],
            "textures": ["Texture.default"]}}})
    for index, identifier in enumerate(config["identifiers"]):
        name = "pmanim_packet_uniform_ui_slot_%05d" % index
        _write(resource / ("entity/" + name + ".entity.json"), {
            "format_version": "1.10.0", "minecraft:client_entity": {"description": {
                "identifier": identifier, "materials": {"default": MATERIAL},
                "geometry": {"default": "geometry.pmanim_packet_uniform_ui"},
                "textures": {"default": "textures/pmanim_packet/white"},
                "render_controllers": [controller]}}})
        _write(behavior / ("entities/" + name + ".json"), {
            "format_version": "1.16.0", "minecraft:entity": {
                "description": {"identifier": identifier, "is_spawnable": False,
                                "is_summonable": False, "is_experimental": False},
                "components": {"minecraft:physics": {"has_gravity": False, "has_collision": False}}}})


def build_uniform_ui_assets(resource_pack, slot_count=128, screen_size=(720, 1080),
                            display_rect=None, slots_per_screen=SLOTS_PER_SCREEN):
    """Merge into an isolated marked packet probe and install its game runtime."""
    resource = Path(resource_pack).resolve()
    output = resource.parent
    marker = output / ".pmanim_packet_probe.json"
    if resource.name != "resource_pack" or not marker.is_file():
        raise ValueError("uniform UI resources require an isolated marked packet probe")
    if json.loads(marker.read_text(encoding="utf-8")).get("kind") != "pmanim_runtime_packet_probe":
        raise ValueError("resource parent is not owned by the packet probe")
    config = uniform_ui_config(slot_count, screen_size, display_rect, slots_per_screen)
    behavior = output / "behavior_pack"
    _write_ui_and_material(resource, config)
    _write_entity_resources(resource, behavior, config)
    # The marked base packet probe supplies the existing 1x1 white entity texture.
    for filename in ("uniform_ui.vertex", "uniform_ui.fragment"):
        destination = resource / "shaders/glsl" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / filename, destination)
    package = behavior / "packet_probe"
    package.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "uniform_ui_runtime.py", package / "uniform_ui_runtime.py")
    _write(output / "uniform_ui_resources.json", config)
    return config
