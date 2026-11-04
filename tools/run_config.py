"""Inspect and execute an existing GSTAR configuration without generating inputs."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import uuid

CONFIG_FILES = ("file_table", "Timescale.cfg", "session.obj", "svinf.dat", "leap.sec", "pan_info")
RANK_REMEDIES = ("NONE", "SUMZERO", "BROWN", "GREENHALL", "KPW")


def set_rank_remedy(config: Path, method: str) -> None:
    """Change only the explicit method field in a newly prepared configuration."""
    method = method.upper()
    if method not in RANK_REMEDIES:
        raise ValueError(f"Unsupported rank deficiency remedy: {method}")
    text = config.read_text(encoding="utf-8")
    pattern = r"(?m)^([ \t]+Rank deficiency remedy[ \t]*=[ \t]*)[A-Za-z_]+([ \t]*)$"
    updated, count = re.subn(pattern, lambda match: match[1] + method + match[2], text)
    if count != 1:
        raise ValueError("Expected exactly one Rank deficiency remedy field")
    config.write_text(updated, encoding="utf-8", newline="\n")


def initialize_case(destination: Path, template_dir: Path) -> Path:
    """Copy editable native files exactly; never generate or replace experiment inputs."""
    destination = destination.resolve()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError(f"Experiment directory is not empty: {destination}. Choose a new --output directory")
    # Read the entire small template first, so a missing file creates no partial case.
    contents = {name: (template_dir / name).read_bytes() for name in CONFIG_FILES}
    for name in ("config", "clocks_raw", "clk", "pfd", "logs", "results", "analysis", "figures", "tools"):
        (destination / name).mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        with (destination / "config" / name).open("xb") as stream:
            stream.write(data)
    (destination / "README.md").write_text(
        "# Configured GSTAR experiment\n\n"
        "Edit config/Timescale.cfg, config/session.obj and config/file_table directly.\n"
        "Provide matching CLK/PFD data or point configuration paths to existing inputs.\n"
        "This directory was initialized from public native configuration templates; no data was generated.\n\n"
        "Run lab.py inspect/execute --workdir <this-directory> from the repository.\n"
        "Configuration guide: https://github.com/Xsleet/GstarTimescale-Lab/blob/main/docs/configuration.md\n",
        encoding="utf-8")
    return destination


def configured_path(value: str, workdir: Path) -> Path:
    # The runtime reads path fields as one whitespace-delimited token.
    if not value or any(char.isspace() for char in value) or '"' in value or "'" in value:
        raise ValueError("Configuration paths must be unquoted and contain no whitespace; use relative paths inside the working directory")
    path = Path(value)
    return (path if path.is_absolute() else workdir / path).resolve()


def inspect_config(file_table: Path, workdir: Path) -> dict:
    """Read the documented text interface; the runtime remains the full validator."""
    workdir = workdir.resolve()
    if not workdir.is_dir():
        raise ValueError(f"Working directory does not exist: {workdir}")
    file_table = (file_table if file_table.is_absolute() else workdir / file_table).resolve()
    entries = {}
    inside = False
    closed = False
    for line in file_table.read_text(encoding="utf-8-sig").splitlines():
        if line.strip() == "+FileTable":
            inside = True
            continue
        if inside and line.startswith("-"):
            closed = True
            break
        if not inside or not line.startswith(" ") or not line.strip():
            continue
        tokens = line.split("!", 1)[0].split()
        if not tokens:
            continue
        if len(tokens) != 2 or tokens[0] in entries:
            raise ValueError(f"Invalid or duplicate file_table entry: {line.strip()}")
        entries[tokens[0]] = str(configured_path(tokens[1], workdir))
    if not inside or not closed or not {"TimescaleCfg", "object"} <= entries.keys():
        raise ValueError("file_table needs +FileTable/-FileTable and TimescaleCfg/object entries")
    for key in ("TimescaleCfg", "object"):
        if not Path(entries[key]).is_file():
            raise ValueError(f"Missing {key} file: {entries[key]}")
    cfg = Path(entries["TimescaleCfg"])
    fields = {}
    for line in cfg.read_text(encoding="utf-8-sig").splitlines():
        content = line.split("!", 1)[0]
        if not line.startswith(" ") or "=" not in content:
            continue
        key, value = content.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in fields:
            raise ValueError(f"Duplicate configuration field: {key}")
        fields[key] = value
    required = {"Start time&session length", "Processing interval", "Project directory",
                "Timescale scope", "Estimation architecture"}
    if not required <= fields.keys():
        raise ValueError(f"Missing configuration fields: {', '.join(sorted(required - fields.keys()))}")
    match = re.fullmatch(r"(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+\[([A-Z0-9]+)\]",
                         fields["Start time&session length"])
    if not match:
        raise ValueError("Expected start: YYYY MM DD hh mm ss duration_seconds [GPST]")
    year, month, day, hour, minute = map(int, match.groups()[:5])
    second, duration = float(match[6]), int(match[7])
    if year > 2026:
        raise ValueError("The current runtime rejects start years after 2026; use a supported runtime version for later dates")
    if not 0 <= second < 60 or not 0 < duration <= 2147483647:
        raise ValueError("Start seconds must be in [0,60) and duration must be a positive 32-bit integer")
    start = datetime(year, month, day, hour, minute) + timedelta(seconds=second)
    end = start + timedelta(seconds=duration)
    interval = float(fields["Processing interval"])
    if not math.isfinite(interval) or interval <= 0 or interval > duration:
        raise ValueError("Processing interval must be finite, positive, and no greater than duration")
    if fields["Estimation architecture"] not in ("centralized", "distributed_if", "distributed_ci"):
        raise ValueError("Unknown estimation architecture")
    if fields["Timescale scope"] not in ("satellite", "constellation"):
        raise ValueError("Unknown timescale scope")
    result_dir = configured_path(fields["Project directory"], workdir)
    if re.search(r"-[A-Z]+-", fields["Project directory"]):
        raise ValueError("Use a concrete Project directory; wildcard expansion is supported only for input paths in this launcher")
    input_keys = ("GNSS Sp3 full name", "GNSS Clk full name", "LEO Sp3 full name",
                  "LEO Clk full name", "PFD data directory", "ISL data directory")
    inputs = {key: str(configured_path(fields[key], workdir)) for key in input_keys if key in fields}
    return {"workdir": str(workdir), "file_table": str(file_table), "tables": entries,
            "start": start.isoformat(), "end": end.isoformat(), "time_frame": match[8],
            "duration_s": duration, "interval_s": interval,
            "architecture": fields["Estimation architecture"], "scope": fields["Timescale scope"],
            "trend_states": fields.get("Clock Trend state num"),
            "harmonic_states": fields.get("Clock Harmonics state num"),
            "rank_remedy": fields.get("Rank deficiency remedy"),
            "inputs": inputs, "result_dir": str(result_dir)}


def execute_config(file_table: Path, workdir: Path, executable: Path, timeout: float = 1800) -> dict:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive and finite")
    info = inspect_config(file_table, workdir)
    project = Path(info["result_dir"])
    if project.exists() and (not project.is_dir() or any(project.iterdir())):
        raise ValueError(f"Project directory is not empty: {project}. Choose a new output path in Timescale.cfg")
    executable = executable.resolve()
    if not executable.is_file():
        raise ValueError(f"Executable missing: {executable}")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    log_dir = Path(info["workdir"]) / "logs" / f"execute_{run_id}"
    log_dir.mkdir(parents=True)
    console = log_dir / "console.log"
    record_path = log_dir / "execution.json"
    hashed_files = {"file_table": Path(info["file_table"]), "TimescaleCfg": Path(info["tables"]["TimescaleCfg"]),
                    "object": Path(info["tables"]["object"]), "executable": executable}
    record = {"configuration": info, "sha256": {key: hashlib.sha256(path.read_bytes()).hexdigest()
              for key, path in hashed_files.items()}, "status": "started", "console_log": str(console)}
    def save_record():
        record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    save_record()
    try:
        with console.open("wb") as stream:
            process = subprocess.run([str(executable), info["file_table"]], cwd=info["workdir"],
                                     stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        record["returncode"] = process.returncode
        if process.returncode != 0:
            raise ValueError(f"Engine exited with code {process.returncode}; inspect {console}")
        engine_log = project / "gstar.log"
        if not engine_log.is_file():
            raise ValueError(f"Engine log was not created: {engine_log}; inspect {console}")
        errors = re.compile(r"\[(?:error|critical|fatal)\]|(?:\*{3}|#{3})\s*error|\b(?:fatal|exception|nan|inf)\b", re.I)
        for path in (console, engine_log):
            if errors.search(path.read_text(encoding="utf-8", errors="replace")):
                raise ValueError(f"Engine log contains an error or nonfinite value; inspect {path}")
        record["status"] = "execution_completed"
        record["validation_scope"] = "Exit code and log error checks only; scientific outputs require case-specific validation and analysis"
        save_record()
        return record
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        save_record()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise ValueError(f"Engine timed out after {timeout:g} seconds; inspect {console}") from exc
        raise
