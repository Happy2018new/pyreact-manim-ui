"""Optional desktop-OpenGL diagnostic backend for the generated MC shader.

Only syntax and the engine UV include are adapted. This backend does not verify
Minecraft's shader translation, texture import, camera or game lifecycle.
"""

import json
import math
from pathlib import Path
import struct

from PIL import Image


VERTEX = """#version 330
in vec2 position;
out vec2 uv;
void main() {
    uv = vec2(position.x * 0.5 + 0.5, 0.5 - position.y * 0.5);
    gl_Position = vec4(position, 0.0, 1.0);
}
"""


def desktop_fragment(source):
    include = '#include "fragmentVersionCentroidUV.h"'
    if source.count(include) != 1 or not source.startswith("// __multiversion__"):
        raise ValueError("Expected the compiler's Minecraft fragment shader")
    return (source.replace("// __multiversion__", "#version 330", 1)
            .replace("precision highp float;", "")
            .replace(include, "in vec2 uv;\nout vec4 fragmentColor;")
            .replace("texture2D(", "texture(")
            .replace("gl_FragColor", "fragmentColor"))


def render_compiled(manifest_path, timestamp, width=960, height=540, viewport_uniform=None,
                    canvas_viewport=None):
    """Return (RGB image, driver information) using an isolated OpenGL context."""
    import moderngl

    viewport_width, viewport_height = viewport_uniform if viewport_uniform is not None else (width, height)
    if not all(math.isfinite(value) and value > 0 for value in (viewport_width, viewport_height)):
        raise ValueError("Viewport uniform dimensions must be finite and positive")
    canvas_top, canvas_height = canvas_viewport if canvas_viewport is not None else (0.0, 1.0)
    if not all(math.isfinite(value) for value in (canvas_top, canvas_height)) or canvas_height <= 0:
        raise ValueError("Canvas viewport must have finite top and positive height ratios")
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    fragment = desktop_fragment((root / manifest["shader"]["path"]).read_text(encoding="utf-8"))
    context = moderngl.create_standalone_context(require=330)
    resources = []
    try:
        program = context.program(vertex_shader=VERTEX, fragment_shader=fragment)
        resources.append(program)
        vertices = context.buffer(struct.pack("8f", -1, -1, 1, -1, -1, 1, 1, 1))
        resources.append(vertices)
        vertex_array = context.simple_vertex_array(program, vertices, "position")
        resources.append(vertex_array)
        with Image.open(root / manifest["texture"]["path"]) as source:
            atlas_image = source.convert("RGBA")
        atlas = context.texture(atlas_image.size, 4, atlas_image.tobytes())
        resources.append(atlas)
        atlas.filter = (moderngl.NEAREST, moderngl.NEAREST)
        atlas.repeat_x = atlas.repeat_y = False
        atlas.use(2)
        background = context.texture((1, 1), 4, bytes([0, 0, 0, 255]))
        resources.append(background)
        background.use(0)
        program["TEXTURE_2"].value = 2
        program["TEXTURE_0"].value = 0
        canvas_pixels = viewport_height * canvas_height
        program["EXTRA_VECTOR1"].value = (timestamp, viewport_width / canvas_pixels, float(canvas_pixels), 1.0)
        program["EXTRA_VECTOR2"].value = (0.0, canvas_top, canvas_height, 0.0)
        framebuffer = context.simple_framebuffer((width, height), components=4)
        resources.append(framebuffer)
        framebuffer.use()
        vertex_array.render(moderngl.TRIANGLE_STRIP)
        pixels = framebuffer.read(components=3, alignment=1)
        image = Image.frombytes("RGB", (width, height), pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        driver = {key: context.info.get(key) for key in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}
        return image, driver
    finally:
        for resource in reversed(resources):
            resource.release()
        context.release()
