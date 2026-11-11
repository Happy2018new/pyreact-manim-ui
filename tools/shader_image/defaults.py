"""Original procedural demo artwork, generated with Pillow and no external assets."""

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter


def gradient(size, top, bottom):
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    for y in range(size[1]):
        t = y / float(size[1] - 1)
        rgb = tuple(round(a * (1.0 - t) + b * t) for a, b in zip(top, bottom))
        draw.line((0, y, size[0], y), fill=rgb + (255,))
    return image


def rounded(image, radius=22):
    """A source alpha ramp also demonstrates filtering of transparent corners."""
    scale = 4
    mask = Image.new("L", (image.width * scale, image.height * scale))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1),
                                          radius=radius * scale, fill=255)
    mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    return image


def aurora():
    image = gradient((384, 256), (8, 17, 42), (24, 58, 72))
    glow = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(glow)
    for band, color in enumerate(((39, 224, 182, 100), (94, 120, 249, 105), (142, 91, 210, 65))):
        upper = [(x, 50 + band * 25 + 26 * math.sin(x / 78.0 + band * 0.6)) for x in range(-20, 410, 4)]
        lower = [(x, y + 22 + 8 * math.sin(x / 33.0)) for x, y in reversed(upper)]
        draw.polygon(upper + lower, fill=color)
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(9)))
    draw = ImageDraw.Draw(image)
    randomizer = random.Random(17)
    for _ in range(65):
        x, y = randomizer.randrange(8, 376), randomizer.randrange(9, 171)
        level = randomizer.randrange(110, 235)
        draw.ellipse((x, y, x + 1, y + 1), fill=(level, level, 245, 255))
    draw.ellipse((286, 35, 312, 61), fill=(229, 245, 242))
    draw.polygon(((0, 210), (56, 149), (93, 188), (145, 126), (210, 193), (251, 157), (332, 213), (384, 175), (384, 256), (0, 256)), fill=(14, 31, 50))
    draw.polygon(((0, 237), (82, 192), (129, 220), (192, 180), (255, 230), (319, 192), (384, 224), (384, 256), (0, 256)), fill=(7, 18, 32))
    return rounded(image)


def sunrise():
    image = gradient((320, 320), (54, 33, 91), (245, 136, 112))
    draw = ImageDraw.Draw(image)
    draw.ellipse((92, 69, 228, 205), fill=(255, 202, 139))
    for y in range(147, 205, 10):
        draw.rectangle((85, y, 235, y + 3), fill=(238, 141, 124))
    draw.polygon(((0, 191), (54, 141), (108, 191), (163, 151), (241, 205), (290, 167), (320, 190), (320, 246), (0, 246)), fill=(83, 55, 107))
    draw.polygon(((0, 216), (70, 184), (127, 216), (207, 175), (263, 220), (320, 195), (320, 250), (0, 250)), fill=(44, 47, 82))
    draw.rectangle((0, 230, 320, 320), fill=(27, 47, 73))
    for index, y in enumerate(range(234, 315, 6)):
        half = 52 - index * 2
        shift = 9 * math.sin(index * 1.7)
        draw.line((160 + shift - half, y, 160 + shift + half, y), fill=(223 - index * 7, 137 - index * 4, 114), width=2)
    for x in (21, 294):
        draw.line((x, 232, x, 174), fill=(13, 32, 53), width=3)
        for y, half in ((177, 10), (188, 14), (201, 19), (216, 22)):
            draw.polygon(((x, y - 13), (x - half, y + 10), (x + half, y + 10)), fill=(13, 32, 53))
    return rounded(image)


def prism():
    image = gradient((256, 384), (25, 28, 68), (13, 63, 78))
    haze = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(haze)
    draw.ellipse((30, 58, 240, 307), fill=(74, 139, 228, 80))
    image = Image.alpha_composite(image, haze.filter(ImageFilter.GaussianBlur(28)))
    draw = ImageDraw.Draw(image)
    for x in range(-220, 420, 30):
        draw.line((x, 300, x + 230, 384), fill=(29, 82, 102))
    for y in (300, 311, 327, 347, 373):
        draw.line((0, y, 256, y), fill=(29, 82, 102))
    top, left, middle, right, bottom = (138, 54), (54, 162), (135, 187), (208, 156), (123, 302)
    draw.polygon((top, left, middle), fill=(97, 220, 227))
    draw.polygon((top, middle, right), fill=(145, 144, 240))
    draw.polygon((left, middle, bottom), fill=(51, 117, 187))
    draw.polygon((middle, right, bottom), fill=(90, 75, 168))
    draw.line((top, left, bottom, right, top, middle, bottom), fill=(190, 239, 255), width=2)
    draw.line((left, middle, right), fill=(173, 210, 251), width=2)
    for x, y, radius in ((36, 78, 4), (220, 244, 5), (192, 37, 3), (43, 276, 3)):
        draw.line((x - radius, y, x + radius, y), fill=(206, 240, 244), width=1)
        draw.line((x, y - radius, x, y + radius), fill=(206, 240, 244), width=1)
    return rounded(image)


def default_images():
    return {"aurora": (aurora(), "极光山野"),
            "sunrise": (sunrise(), "日出湖畔"),
            "prism": (prism(), "星光棱镜")}


def checkerboard():
    image = Image.new("RGBA", (64, 64), (39, 47, 64, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, 64, 8):
        for x in range(0, 64, 8):
            if (x // 8 + y // 8) % 2:
                draw.rectangle((x, y, x + 7, y + 7), fill=(57, 67, 86, 255))
    return image
