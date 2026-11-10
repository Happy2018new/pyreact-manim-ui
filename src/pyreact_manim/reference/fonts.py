"""Require actual font coverage instead of accepting invisible fallback glyphs."""
import hashlib
from contextlib import contextmanager
import os
from pathlib import Path


def _family_names(font):
    return sorted({record.toUnicode() for record in font["name"].names
                   if record.nameID in (1, 16)})


def _pango_family(font):
    # Pango's Windows backend may reject localized aliases such as 宋体 even
    # though they are genuine font names. Prefer the same face's English name.
    table = font["name"]
    for name_id in (16, 1):
        for platform_id, encoding_id, language_id in ((3, 1, 0x409), (3, 10, 0x409), (1, 0, 0)):
            record = table.getName(name_id, platform_id, encoding_id, language_id)
            if record is not None:
                return record.toUnicode()
    return table.getBestFamilyName()


def _regular_priority(font):
    weight = font["OS/2"].usWeightClass if "OS/2" in font else 400
    italic = bool(font["head"].macStyle & 2) if "head" in font else False
    return (italic, abs(weight - 400))


@contextmanager
def _font_faces(path):
    from fontTools.ttLib import TTCollection, TTFont

    with path.open("rb") as source:
        is_collection = source.read(4) == b"ttcf"
    if is_collection:
        collection = TTCollection(path, lazy=True)
        try:
            yield [(index, font) for index, font in enumerate(collection.fonts)]
        finally:
            collection.close()
    else:
        with TTFont(path, lazy=True) as font:
            yield [(None, font)]


def _select_face(faces, family, path):
    if not family and len(faces) > 1:
        raise ValueError("Font collection %s has multiple faces; supply the font family" % path.name)
    requested = family.strip().casefold() if family else None
    matches = [(index, font) for index, font in faces
               if requested is None or requested in {name.casefold() for name in _family_names(font)}]
    if not matches:
        names = sorted({name for _, font in faces for name in _family_names(font)})
        raise ValueError("Requested font family %r does not match %s in %s; refusing Pango fallback"
                         % (family, names, path.name))
    return min(matches, key=lambda pair: _regular_priority(pair[1]))


def _system_font_candidates():
    """Yield installed font files, without copying proprietary system fonts."""
    if os.name != "nt":
        raise RuntimeError("Font-name lookup currently supports Windows; pass font_file explicitly on other systems")
    import winreg

    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    directories = [windows_fonts]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        directories.append(Path(local_appdata) / "Microsoft/Windows/Fonts")
    found = set()
    supported_suffixes = (".ttf", ".otf", ".ttc", ".otc")
    registry_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key = winreg.OpenKey(hive, registry_path)
        except FileNotFoundError:
            continue
        with key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                _, value, kind = winreg.EnumValue(key, index)
                if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    continue
                path = Path(os.path.expandvars(value))
                choices = [path] if path.is_absolute() else [directory / path for directory in directories]
                for candidate in choices:
                    if candidate.suffix.lower() in supported_suffixes and candidate.is_file() and candidate not in found:
                        found.add(candidate)
                        yield candidate
    # Localized family names do not necessarily appear in the registry label.
    for directory in directories:
        if directory.is_dir():
            for candidate in sorted(directory.iterdir()):
                if candidate.suffix.lower() in supported_suffixes and candidate not in found:
                    found.add(candidate)
                    yield candidate


def resolve_system_font(font_family):
    """Resolve an installed family or localized alias to its real font file.

    The exporter registers this file with Pango and validates coverage separately.
    Missing family names are errors, never requests for a silent fallback font.
    """
    from fontTools.ttLib import TTLibError

    if not isinstance(font_family, str) or not font_family.strip():
        raise ValueError("An installed font family name is required")
    requested = font_family.strip().casefold()
    matches = []
    for path in _system_font_candidates():
        try:
            with _font_faces(path) as faces:
                for _, font in faces:
                    if requested in {name.casefold() for name in _family_names(font)}:
                        matches.append((_regular_priority(font), str(path).casefold(), path))
        except (OSError, TTLibError):
            # Some OS entries can refer to inaccessible or non-OpenType files.
            continue
    if not matches:
        raise ValueError("Installed font family %r was not found; install it or pass font_file and its matching family"
                         % font_family)
    return min(matches)[2].resolve()


def validate_font_coverage(font_file, text, font_family=None):
    """Return source metadata or reject missing characters and a wrong family.

    Whitespace is layout input, not a request to draw a fallback glyph. Visible
    characters must have a non-.notdef Unicode cmap entry in this very file.
    """
    path = Path(font_file).resolve(strict=True)
    if not isinstance(text, str) or not text or not text.strip():
        raise ValueError("Font coverage requires visible Unicode text")
    with _font_faces(path) as faces:
        collection_index, font = _select_face(faces, font_family, path)
        names = _family_names(font)
        cmap = font.getBestCmap() or {}
        missing = sorted({character for character in text if not character.isspace()
                          and (ord(character) not in cmap or cmap[ord(character)] == ".notdef")}, key=ord)
        if missing:
            details = ", ".join("U+%04X (%s)" % (ord(character), character) for character in missing)
            raise ValueError("Font %s is missing %s; refusing fallback/tofu. Rebuild the CJK subset with "
                             "tools/reference/setup_cjk.py --text-file <UTF-8 file>, or pass a complete "
                             "font_file and its matching font family." % (path.name, details))
        return {"font_file": path.name, "font_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "family_names": names, "checked_codepoints": sorted({ord(c) for c in text if not c.isspace()}),
                "unicode_cmap_size": len(cmap), "coverage_verified": True,
                "collection_index": collection_index, "pango_family": _pango_family(font)}
