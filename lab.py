#!/usr/bin/env python3
"""Command-line entry point. The numerical solver is supplied separately by the maintainer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and "\\" not in name and ":" not in name and all(
        part not in ("", ".", "..") for part in name.split("/")
    )


def release_manifest(root: Path = ROOT) -> dict:
    manifest = json.loads((root / "engine-release.json").read_text(encoding="utf-8"))
    if manifest.get("platform") != "windows-x64" or manifest.get("distribution") != "restricted":
        raise ValueError("Unsupported runtime release manifest")
    files = manifest.get("files", {})
    if "GstarTimescale.exe" not in files or any(not safe_name(name) for name in files):
        raise ValueError("Invalid runtime file list")
    for spec in files.values():
        if not isinstance(spec["size"], int) or not 0 <= spec["size"] <= 100_000_000:
            raise ValueError("Invalid runtime file size")
    return manifest


def install_engine(archive: Path, root: Path = ROOT) -> Path:
    """Install only the exact maintainer archive described by this checkout."""
    manifest = release_manifest(root)
    destination = root / "engine"
    if destination.exists() or destination.is_symlink():
        raise ValueError("engine already exists. Keep your current installation; use a new checkout to upgrade.")
    # Hash and extract the same open file, without executing anything in it.
    with archive.open("rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        if digest.hexdigest() != manifest["archive_sha256"]:
            raise ValueError("Archive SHA256 mismatch. Ask your maintainer for the matching version; do not bypass the check.")
        stream.seek(0)
        with zipfile.ZipFile(stream) as package:
            entries = package.infolist()
            names = [item.filename for item in entries]
            if len(names) != len(set(names)) or set(names) != set(manifest["files"]):
                raise ValueError("Archive has duplicate, missing, or unexpected files")
            for item in entries:
                mode = item.external_attr >> 16
                if (not safe_name(item.filename) or item.is_dir() or stat.S_ISLNK(mode)
                        or item.file_size != manifest["files"][item.filename]["size"]):
                    raise ValueError(f"Unsafe archive entry: {item.filename}")
            with tempfile.TemporaryDirectory(prefix=".engine-install-", dir=root) as staging:
                stage = Path(staging) / "engine"
                stage.mkdir()
                for item in entries:
                    data = package.read(item)
                    if hashlib.sha256(data).hexdigest() != manifest["files"][item.filename]["sha256"]:
                        raise ValueError(f"Runtime file SHA256 mismatch: {item.filename}")
                    target = stage / item.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                # Refuse a destination introduced during extraction as well.
                if destination.exists() or destination.is_symlink():
                    raise ValueError("engine was created during installation; refusing to overwrite it")
                stage.rename(destination)
    return destination


def check_engine(root: Path = ROOT) -> Path:
    manifest = release_manifest(root)
    engine = root / "engine"
    if not engine.is_dir() or engine.is_symlink():
        raise ValueError("Runtime missing. Receive the ZIP from your maintainer, then run: python lab.py install-engine <zip>")
    paths = list(engine.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Runtime directory must not contain symbolic links")
    present = {path.relative_to(engine).as_posix() for path in paths if path.is_file()}
    if present != set(manifest["files"]):
        raise ValueError("Runtime file list differs from the release; reinstall in a new checkout")
    for name, spec in manifest["files"].items():
        path = engine / name
        if path.stat().st_size != spec["size"] or sha256(path) != spec["sha256"]:
            raise ValueError(f"Runtime file changed: {name}; obtain a fresh package from your maintainer")
    return engine / "GstarTimescale.exe"


def check_platform() -> None:
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("This runtime requires Windows x64. Input preparation and report analysis can run elsewhere.")


def check_dependencies() -> None:
    missing = [name for name in ("numpy", "pandas", "matplotlib", "allantools")
               if importlib.util.find_spec(name) is None]
    if missing:
        raise ValueError(f"Missing Python packages: {', '.join(missing)}. Run: python -m pip install -r requirements-demo.txt")
    from tools.run_demo import check_analysis_dependencies
    check_analysis_dependencies()


def resolve_output(value: Path | None, case: str, days: float) -> Path:
    value = value or Path("Runs") / f"{case}_{days:g}days"
    return (value if value.is_absolute() else ROOT / value).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-engine", help="Install the ZIP provided privately by your maintainer")
    install.add_argument("archive", type=Path)
    commands.add_parser("doctor", help="Check Python, platform, dependencies, and runtime integrity")
    for name in ("inspect", "execute"):
        command = commands.add_parser(name, help="Inspect an existing configuration" if name == "inspect" else
                                      "Run an existing file_table without generating inputs or rewriting settings")
        command.add_argument("--file-table", type=Path, default=Path("config/file_table"))
        command.add_argument("--workdir", type=Path, required=True, help="Run working directory; relative paths start at this repository")
        if name == "execute":
            command.add_argument("--timeout", type=float, default=1800)
    for name in ("run", "prepare"):
        command = commands.add_parser(name, help="Run a complete experiment" if name == "run" else "Generate input files only")
        command.add_argument("--case", choices=("heterogeneous", "basic"), default="heterogeneous")
        command.add_argument("--days", type=float, default=10)
        command.add_argument("--seed", type=int, default=2026)
        command.add_argument("--architecture", choices=("centralized", "distributed_if", "distributed_ci"), default="centralized")
        command.add_argument("--output", type=Path, help="New/empty folder; relative paths are resolved from this repository")
        command.add_argument("--timeout", type=float, default=1800)
    report = commands.add_parser("report", help="Rebuild HTML/ADEV for an existing experiment without rerunning the solver")
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if not (3, 10) <= sys.version_info[:2] <= (3, 12):
            raise ValueError("Use Python 3.11 or 3.12 for the tested dependency set (3.10 is also supported)")
        if args.command == "install-engine":
            print(f"Installed: {install_engine(args.archive.resolve())}")
            print("Next: python lab.py doctor")
            return 0
        if args.command == "doctor":
            checks = (("Windows x64", check_platform), ("Python packages", check_dependencies), ("Runtime SHA256", check_engine))
            failed = False
            print(f"Python: {platform.python_version()} ({sys.executable})")
            for label, action in checks:
                try:
                    action()
                    print(f"PASS: {label}")
                except (ValueError, OSError, ImportError) as exc:
                    failed = True
                    print(f"FAIL: {label}: {exc}")
            return int(failed)
        if args.command in ("inspect", "execute"):
            from tools.run_config import execute_config, inspect_config
            workdir = (args.workdir if args.workdir.is_absolute() else ROOT / args.workdir).resolve()
            if args.command == "inspect":
                print(json.dumps(inspect_config(args.file_table, workdir), indent=2, ensure_ascii=False))
            else:
                check_platform()
                record = execute_config(args.file_table, workdir, check_engine(), args.timeout)
                print(f"Engine execution completed. Results: {record['configuration']['result_dir']}")
                print(f"Run record: {Path(record['console_log']).parent / 'execution.json'}")
                print("Custom runs require case-specific validation and analysis; no demo HTML report was generated.")
            return 0
        from tools import run_demo
        if args.command == "report":
            check_dependencies()
            output = resolve_output(args.output, "heterogeneous", 10)
            return run_demo.main(["--report-only", "--output", str(output)])
        output = resolve_output(args.output, args.case, args.days)
        forwarded = ["--output", str(output), "--clock-profile", "csac-mro" if args.case == "heterogeneous" else "basic",
                     "--days", str(args.days), "--seed", str(args.seed), "--architecture", args.architecture,
                     "--timeout", str(args.timeout)]
        if args.command == "prepare":
            forwarded.append("--prepare-only")
        else:
            check_platform()
            check_dependencies()
            forwarded.extend(["--exe", str(check_engine())])
        result = run_demo.main(forwarded)
        if result == 0 and args.command == "run":
            manifest = release_manifest()
            record = {"version": manifest["version"], "platform": manifest["platform"],
                      "executable_sha256": manifest["files"]["GstarTimescale.exe"]["sha256"],
                      "archive_sha256": manifest["archive_sha256"],
                      "python_version": platform.python_version()}
            (output / "config/runtime.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return result
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
