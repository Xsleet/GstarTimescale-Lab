"""Audit the Git index before publishing; ignored local runtime files are not read."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "LICENSE.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md",
              "lab.py", "requirements-demo.txt", "engine-release.json", ".gitignore", ".gitattributes"}
FOLDERS = {"docs", "examples", "tools", "tests", ".github", ".githooks", "config"}
SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".svg"}


def audit_file(name: str, data: bytes, mode: str = "100644") -> list[str]:
    issues = []
    path = PurePosixPath(name)
    if mode not in ("100644", "100755"):
        issues.append("symlinks/submodules are not permitted")
    special = name in ROOT_FILES or name in {"config/leap.sec", ".githooks/pre-commit"}
    if not special and (len(path.parts) < 2 or path.parts[0] not in FOLDERS or path.suffix not in SUFFIXES):
        issues.append("path/type is outside the public file allowlist")
    if any(part.lower() in {"engine", "private", "runs", "build", "src", "include", ".git", ".claude"} for part in path.parts):
        issues.append("private/runtime/source directory is forbidden")
    if len(data) > 2_000_000 or data.startswith((b"MZ", b"PK\x03\x04", b"\x7fELF")) or b"\x00" in data:
        issues.append("binary/archive/oversized file is forbidden")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return issues + ["file is not UTF-8 text"]
    if re.search(r"(?i)[a-z]:[/\\](?:users|leotimescale)[/\\]", text):
        issues.append("local workspace/user path found")
    if re.search(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)", text):
        issues.append("possible credential/private key found")
    return issues


def main() -> int:
    listing = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=ROOT).decode("utf-8")
    issues = []
    records = [record for record in listing.split("\0") if record]
    if not records:
        print("FAIL: no staged/tracked files to audit")
        return 1
    for record in records:
        metadata, name = record.split("\t", 1)
        mode, blob, stage = metadata.split()
        if stage != "0":
            issues.append(f"{name}: unresolved merge")
            continue
        data = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=ROOT)
        issues.extend(f"{name}: {issue}" for issue in audit_file(name, data, mode))
    if issues:
        print("\n".join(f"FAIL: {issue}" for issue in issues))
        return 1
    print(f"PASS: {len(records)} public text files; no runtime, core source, archive, or detected secrets in Git index")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
