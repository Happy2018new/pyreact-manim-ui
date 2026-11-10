"""Package only the playable addon, excluding host tools and private evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "dist/pyreact-manim-ui-0.1.0-preview.mcaddon")
    args = parser.parse_args()
    files = []
    for pack in ("behavior_pack", "resource_pack"):
        manifest = json.loads((ROOT / pack / "manifest.json").read_text(encoding="utf-8"))
        if not manifest.get("modules"):
            raise ValueError("Pack has no modules: " + pack)
        files.extend(path for path in (ROOT / pack).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts
                     and path.suffix not in (".pyc", ".pyo"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    with zipfile.ZipFile(args.output) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError("Archive verification failed: " + corrupt)
    print(json.dumps({"output": str(args.output.resolve()), "files": len(files),
                      "bytes": args.output.stat().st_size,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "target": "NetEase Windows ModSDK; not international Bedrock Python support"}, indent=2))


if __name__ == "__main__":
    main()
