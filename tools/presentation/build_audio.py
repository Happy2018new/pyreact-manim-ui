"""Deploy five-second Ogg music/foley chunks with one-second seek tails."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SCENES = ("client_showcase", "story_showcase")


def build(masters, ffmpeg):
    definition_path = ROOT / "resource_pack/sounds/sound_definitions.json"
    document = (json.loads(definition_path.read_text(encoding="utf-8")) if definition_path.exists()
                else {"format_version": "1.14.0", "sound_definitions": {}})
    definitions = document["sound_definitions"]
    tasks = []
    for scene in SCENES:
        source = masters / (scene + ".wav")
        if not source.is_file():
            raise FileNotFoundError(source)
        folder = ROOT / "resource_pack/sounds/pmanim/presentation" / scene
        folder.mkdir(parents=True, exist_ok=True)
        for segment in range(24):
            for offset in range(5):
                name = "s%02d" % segment + ("_o%02d" % offset if offset else "")
                resource = "sounds/pmanim/presentation/%s/%s" % (scene, name)
                definitions["pmanim.presentation.%s.%s" % (scene, name)] = {
                    "category": "ui", "sounds": [{"name": resource, "stream": True, "volume": 1.0}]}
                tasks.append((source, segment * 5 + offset, 5 - offset, folder / (name + ".ogg")))

    def encode(task):
        source, start, duration, target = task
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start),
                        "-i", str(source), "-t", str(duration), "-c:a", "libvorbis", "-q:a", "4",
                        "-metadata", "comment=Original synthesized film score and wind foley", str(target)],
                       check=True, capture_output=True, timeout=40,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return target.stat().st_size

    with ThreadPoolExecutor(max_workers=4) as pool:
        sizes = list(pool.map(encode, tasks))
    definition_path.parent.mkdir(parents=True, exist_ok=True)
    definition_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    report = {"scenes": list(SCENES), "segment_seconds": 5, "seek_step_seconds": 1,
              "files": len(tasks), "bytes": sum(sizes), "original_synthesis": True,
              "master_sha256": {scene: hashlib.sha256((masters / (scene + ".wav")).read_bytes()).hexdigest()
                                for scene in SCENES},
              "timing_limit": "No SDK sample offset: resumed music can lag picture by less than one second; render-tick scheduling also applies."}
    (masters / "deployment.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--masters", type=Path, default=ROOT / ".runtime/presentation-audio")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "C:/Sharing/ffmpeg/bin/ffmpeg.exe")
    args = parser.parse_args()
    print(json.dumps(build(args.masters, args.ffmpeg), ensure_ascii=False, indent=2))
