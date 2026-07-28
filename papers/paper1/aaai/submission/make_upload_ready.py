#!/usr/bin/env python3
"""Assemble the four AAAI-27 upload artifacts and their SHA-256 manifest."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

SUBMISSION_DIR = Path(__file__).resolve().parent
AAAI_DIR = SUBMISSION_DIR.parent
UPLOAD_DIR = SUBMISSION_DIR / "upload_ready"

DELIVERABLES = {
    "01_main_anonymous.pdf": AAAI_DIR / "main.pdf",
    "02_reproducibility_checklist.pdf": AAAI_DIR
    / "ReproducibilityChecklist.pdf",
    "03_supplement_anonymous.pdf": AAAI_DIR / "supplement.pdf",
    "04_code_data_anonymous.zip": AAAI_DIR
    / "artifact"
    / "agentproof-anonymized.zip",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    missing = [str(path) for path in DELIVERABLES.values() if not path.is_file()]
    if missing:
        raise SystemExit("missing build output(s):\n" + "\n".join(missing))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for upload_name, source in DELIVERABLES.items():
        destination = UPLOAD_DIR / upload_name
        temporary = destination.with_suffix(destination.suffix + ".new")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)

    manifest = "".join(
        f"{sha256(UPLOAD_DIR / name)}  {name}\n" for name in DELIVERABLES
    )
    manifest_path = UPLOAD_DIR / "SHA256SUMS.txt"
    temporary_manifest = manifest_path.with_suffix(".txt.new")
    temporary_manifest.write_text(manifest, encoding="ascii")
    temporary_manifest.replace(manifest_path)

    for name in DELIVERABLES:
        path = UPLOAD_DIR / name
        print(f"{name}: {path.stat().st_size} bytes")
    print("wrote upload_ready/SHA256SUMS.txt")


if __name__ == "__main__":
    main()
