"""Build a small, renamed OFL Chinese font subset from a pinned official font."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FONTTOOLS_VERSION = "4.62.1"
SOURCE_COMMIT = "a85815a42757630ce188fdad368c2dfc444d4773"
FONT_HASH = "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da"
LICENSE_HASH = "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9"
DEFAULT_TEXT = "中文变换数学动画汉字公式测试你好世界示例量子函数圆形中文轉換數學動畫"
FAMILY = "Pyreact Manim CJK"
STYLES = {
    "serif": {"commit": "8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5", "directory": "notoserifsc",
              "source_name": "NotoSerifSC", "font_hash": "050080d9255a86808f2945bffac582b31ef32bc36411ce29563b4961670c66f9",
              "license_hash": "5e0da210fb04058a8c0087985d2d456b931c2579811a49655721d3cf0c36b6d6",
              "family": "Pyreact Manim Song", "stem": "PyreactManimSong-Regular",
              "license_file": "LICENSE_NOTO_SERIF_SC.txt", "cache_subdir": "serif"},
    "sans": {"commit": SOURCE_COMMIT, "directory": "notosanssc", "source_name": "NotoSansSC",
             "font_hash": FONT_HASH, "license_hash": LICENSE_HASH, "family": FAMILY,
             "stem": "PyreactManimCJK-Regular", "license_file": "LICENSE_CJK_OFL.txt", "cache_subdir": ""},
}


def fetch_verified(directory, filename, url, expected, offline=False):
    path = directory / filename
    if path.exists():
        data = path.read_bytes()
    else:
        if offline:
            raise FileNotFoundError("Pinned source not cached: " + str(path))
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "pyreact-manim-ui-font-setup"}),
                                    timeout=60) as response:
            data = response.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError("Pinned source SHA256 mismatch for " + filename)
    if not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path


def build_subset(source_path, output_path, text, style="serif"):
    import fontTools
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    if fontTools.__version__ != FONTTOOLS_VERSION:
        raise RuntimeError("Reproducible CJK setup requires fontTools==" + FONTTOOLS_VERSION)
    config = STYLES[style]
    family, stem = config["family"], config["stem"]
    characters = set(text) | {chr(i) for i in range(32, 127)}
    with TTFont(source_path, recalcTimestamp=False) as font:
        original_stamp = font["head"].modified
        cmap = font.getBestCmap()
        missing = sorted(ord(character) for character in characters if not character.isspace() and ord(character) not in cmap)
        if missing:
            raise ValueError("Pinned Noto source lacks " + ", ".join("U+%04X" % point for point in missing))
        options = subset.Options()
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.name_legacy = True
        options.recommended_glyphs = True
        options.notdef_outline = True
        options.recalc_timestamp = False
        sub = subset.Subsetter(options=options)
        sub.populate(unicodes=sorted(ord(character) for character in characters if ord(character) in cmap))
        sub.subset(font)
        instantiateVariableFont(font, {"wght": 400}, inplace=True)
        # A modified OFL font is explicitly renamed; do not imply unmodified Noto.
        replacements = {1: family, 2: "Regular", 3: stem + ";source-" + config["font_hash"][:8] + ";subset-v1",
                        4: family + " Regular", 6: stem, 16: family, 17: "Regular",
                        21: family, 22: "Regular"}
        font["name"].names = [record for record in font["name"].names if record.nameID != 25]
        for record in font["name"].names:
            if record.nameID in replacements:
                record.string = replacements[record.nameID]
        for name_id, value in replacements.items():
            font["name"].setName(value, name_id, 3, 1, 0x409)
        font["head"].modified = original_stamp
        font.recalcTimestamp = False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        font.save(output_path)
    return {"family": family, "file": output_path.name, "style": style, "weight": 400,
            "characters": "".join(sorted(characters, key=ord)),
            "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            "bytes": output_path.stat().st_size, "fonttools": FONTTOOLS_VERSION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="", help="Additional characters; bundled demo characters and ASCII are always included")
    parser.add_argument("--text-file", type=Path, help="UTF-8 text to include along with --text")
    parser.add_argument("--style", choices=sorted(STYLES), default="serif", help="Default: Song/Serif; optional Sans")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / ".runtime/cjk-font-source")
    parser.add_argument("--offline", action="store_true", help="Use pinned cached inputs only")
    args = parser.parse_args()
    config = STYLES[args.style]
    source_root = "https://raw.githubusercontent.com/google/fonts/" + config["commit"] + "/ofl/" + config["directory"] + "/"
    source_url = source_root + config["source_name"] + "%5Bwght%5D.ttf"
    cache = args.cache / config["cache_subdir"]
    output = args.output or ROOT / ("tools/reference/fonts/" + config["stem"] + ".ttf")
    text = DEFAULT_TEXT + args.text + (args.text_file.read_text(encoding="utf-8-sig") if args.text_file else "")
    font = fetch_verified(cache, config["source_name"] + "-VF.ttf", source_url, config["font_hash"], args.offline)
    license_path = fetch_verified(cache, "OFL.txt", source_root + "OFL.txt", config["license_hash"], args.offline)
    report = build_subset(font, output, text, args.style)
    report["source"] = {"repository": "https://github.com/google/fonts", "commit": config["commit"],
                        "url": source_url, "sha256": config["font_hash"],
                        "bytes": font.stat().st_size, "license": "SIL Open Font License 1.1",
                        "license_url": source_root + "OFL.txt", "license_sha256": config["license_hash"]}
    output.with_name(config["license_file"]).write_bytes(license_path.read_bytes())
    output.with_suffix(".source.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8", newline="\n")
    print(json.dumps({key: report[key] for key in ("file", "family", "bytes", "sha256")}, indent=2))


if __name__ == "__main__":
    main()
