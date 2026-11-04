"""Download four existing simulated CSAC clocks and editable native configuration.

Run from the repository root: python tools/prepare_csac.py --output Runs/csac_10days
Use --archive csac4-10days-inputs-v1.zip for an offline installation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from tools.thesis_section43 import extract_archive


def descriptor() -> dict:
    return json.loads((ROOT / "examples/csac/data-release.json").read_text(encoding="utf-8"))


def prepare(output: Path, archive: Path | None = None) -> None:
    """Install pinned inputs unchanged; never generate clocks or run the solver."""
    output = output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Choose a new experiment directory.")
    info = descriptor()
    if archive is not None:
        extract_archive(archive.resolve(), output, info)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".csac-download-", dir=output.parent) as temporary:
            downloaded = Path(temporary) / info["filename"]
            url = ("https://github.com/Xsleet/GstarTimescale-Lab/releases/download/"
                   f"{info['release_tag']}/{info['filename']}")
            print(f"Downloading four archived CSAC clocks ({info['bytes'] / 1e6:.1f} MB)", flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "GstarTimescale-Lab"})
            with urllib.request.urlopen(request, timeout=60) as response, downloaded.open("wb") as stream:
                total = 0
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > info["bytes"]:
                        raise ValueError("Download exceeds the pinned archive size")
                    stream.write(block)
            extract_archive(downloaded, output, info)
    print(f"Ready: {output}")
    print("Edit config/file_table, config/Timescale.cfg and config/session.obj, then run the engine.")
    print("Results: results/IEM.txt and SIM1.txt through SIM4.txt; plot them with tools/plot_results.py.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("Runs/csac_10days"))
    parser.add_argument("--archive", type=Path, help="Previously downloaded data ZIP; skips the network")
    args = parser.parse_args(argv)
    try:
        prepare(args.output, args.archive)
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
