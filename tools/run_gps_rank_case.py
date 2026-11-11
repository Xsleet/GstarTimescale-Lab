"""Reproduce the archived, correctly initialized 31-GPS native experiment.

No external research workspace, fitting stage, or optimizer is required.
See examples/gps-rank-initialized/README.md for provenance and limitations.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date, datetime, timedelta
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import numpy as np

REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))
from tools import thesis_section43 as archive

EXAMPLE = REPOSITORY / "examples/gps-rank-initialized"
CASE = REPOSITORY / "Runs/gps_rank_data"
METHODS = ("GREENHALL", "KPW", "SUMZERO", "BROWN")
DT = 30
DAY = 86400 // DT
EPOCHS = 22 * DAY
START = datetime(2026, 6, 2)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def dump(path: Path, value: object) -> None:
    write(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def table(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def spans(mask: np.ndarray) -> list[tuple[int, int]]:
    delta = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(delta == 1), np.flatnonzero(delta == -1)))


def deviation(phase: np.ndarray, mask: np.ndarray, metric: str, taus: list[float]) -> list[dict]:
    """Pool variance by difference counts inside continuous spans, never across gaps."""
    import allantools

    x = np.asarray(phase, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    if x.ndim != 1 or x.shape != mask.shape or not np.isfinite(x[mask]).all():
        raise ValueError("Finite phase and a matching explicit validity mask are required")
    order = {"adev": 2, "hdev": 3, "ohdev": 3}[metric]
    factor = 2 if metric == "adev" else 6
    rows = []
    for tau in taus:
        if tau <= 0 or tau % DT:
            raise ValueError("Tau must be a positive integer multiple of 30 seconds")
        step = int(tau / DT)
        total, count = 0.0, 0
        for lo, hi in spans(mask):
            if metric != "ohdev":
                delta = np.diff(x[lo:hi:step], n=order)
                total += float(delta @ delta) / (factor * tau * tau)
                count += len(delta)
                continue
            n = hi - lo - 3 * step
            if n <= 0:
                continue
            segment = x[lo:hi]
            if n == 1:
                dev, _, terms = allantools.allantools.calc_hdev_phase(segment, 1 / DT, step, 1)
            else:
                used, values, _, terms = allantools.ohdev(segment, rate=1 / DT, data_type="phase", taus=[tau])
                np.testing.assert_array_equal(used, [tau])
                dev, terms = values[0], int(terms[0])
            if terms != n:
                raise ValueError("Unexpected overlapping difference count")
            delta = segment
            for _ in range(3):
                delta = delta[step:] - delta[:-step]
            direct = np.sqrt(float(delta @ delta) / (6 * tau * tau * n))
            np.testing.assert_allclose(dev, direct, rtol=2e-7, atol=1e-24)
            total += n * dev * dev
            count += n
        if count >= 2:
            dev = float(np.sqrt(total / count))
            rows.append(dict(tau_s=float(tau), deviation=dev, difference_terms=count,
                             error_proxy_not_ci=dev / np.sqrt(count)))
    return rows


def verify_assets() -> None:
    archive.verify(CASE, "experiment", catalog=load(EXAMPLE / "data-release.json"))


def clocks() -> tuple[np.ndarray, np.ndarray, list[str]]:
    with np.load(CASE / "data/clocks.npz", allow_pickle=False) as data:
        raw, valid, satellites = data["phase"], data["valid"], data["satellites"].tolist()
    if raw.shape != (EPOCHS, 31) or satellites != load(CASE / "case.json")["satellites"]:
        raise ValueError("Clock matrix or satellite order differs from the frozen case")
    np.testing.assert_array_equal(valid, np.isfinite(raw).all(axis=1))
    if not valid[0] or valid.sum() != 31829 or len(spans(valid)) != 7:
        raise ValueError("Unexpected complete-case mask")
    return raw, valid, satellites


def statistics(ensembles: dict[str, np.ndarray], epochs: int = EPOCHS) -> list[dict]:
    raw, mask, satellites = clocks()
    raw, mask = raw[3:epochs], mask[3:epochs]
    series = {satellite: raw[:, i] for i, satellite in enumerate(satellites)}
    series["EqualWeight"] = raw.mean(axis=1)
    series.update(ensembles)
    rows = []
    taus = load(CASE / "case.json")["target_taus_s"]
    for metric in ("adev", "hdev", "ohdev"):
        equal = {r["tau_s"]: r for r in deviation(series["EqualWeight"], mask, metric, taus)}
        for name, values in series.items():
            for row in deviation(values, mask, metric, taus):
                ref = equal[row["tau_s"]]
                if row["difference_terms"] != ref["difference_terms"]:
                    raise ValueError("Series do not use the same mask")
                rows.append(dict(metric=metric, series=name, **row,
                                 ratio_to_equal=row["deviation"] / ref["deviation"]))
    return rows


def verify_reference() -> None:
    verify_assets()
    with np.load(CASE / "data/initialized_ensembles.npz", allow_pickle=False) as data:
        np.testing.assert_array_equal(data["epoch_index"], np.arange(3, EPOCHS))
        if set(data.files) != set(METHODS) | {"epoch_index"}:
            raise ValueError("Unexpected archived result series")
        results = {name: data[name] for name in METHODS}
    rows = statistics(results)
    with (CASE / "reference/stability_summary.tsv").open(encoding="utf-8") as stream:
        reference = {(r["metric"], r["series"], float(r["tau_s"])): r
                     for r in csv.DictReader(stream, delimiter="\t")}
    if len(rows) != len(reference):
        raise ValueError("Reference table has different rows")
    for row in rows:
        ref = reference[row["metric"], row["series"], row["tau_s"]]
        if row["difference_terms"] != int(ref["difference_terms"]):
            raise ValueError("Reference difference count mismatch")
        for key in ("deviation", "ratio_to_equal", "error_proxy_not_ci"):
            np.testing.assert_allclose(row[key], float(ref[key]), rtol=2e-12, atol=0)
    print(f"PASS archived hashes and {len(rows)} exact-tau ADEV/HDEV/OHDEV values; 36 series, 7 spans.")


def prepare(output: Path, epochs: int) -> None:
    verify_assets()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Preparation requires an empty output directory")
    if not 4 <= epochs <= EPOCHS:
        raise ValueError(f"Epochs must be between 4 and {EPOCHS}")
    raw, valid, _ = clocks()
    meta = load(CASE / "case.json")
    for folder in ("config", "clocks_raw", "clk", "pfd", "build", "logs", "results", "analysis", "figures"):
        (output / folder).mkdir(parents=True, exist_ok=True)
    for source in (CASE / "config").rglob("*"):
        if source.is_file():
            target = output / "config" / source.relative_to(CASE / "config")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copyfile(CASE / "data/clocks.npz", output / "clocks_raw/all_gps.npz")
    dump(output / "config/case.json", meta)
    for method in METHODS + ("NONE",):
        name = method.lower()
        (output / "results" / name).mkdir()
        if epochs != EPOCHS:
            path = output / f"config/{name}/Timescale.cfg"
            cfg = re.sub(r"(?m)^ Start time&session length\s*=.*$",
                         f" Start time&session length = 2026 06 02 00 00 00 {epochs * DT} [GPST]",
                         path.read_text())
            write(path, cfg)
    previous = np.maximum.accumulate(np.where(valid, np.arange(EPOCHS), 0))
    held = raw[previous]
    specs = meta["clock_specs"]
    hashes = []
    for day in range((epochs + DAY - 1) // DAY):
        epoch = START + timedelta(days=day)
        tag = epoch.strftime("%Y%j")
        lo, hi = day * DAY, min((day + 1) * DAY, epochs)
        path = output / f"clk/BHU_{tag}.CLK"
        with path.open("w", encoding="ascii", newline="\n") as stream:
            stream.write("     3.00           C                                       RINEX VERSION / TYPE\n")
            stream.write("BHU all GPS; reversible virtual PRN mapping                  COMMENT\n")
            stream.write(f"{DT:10.2f}                                                  INTERVAL\n")
            stream.write(f"{len(specs):6d}                                                      # OF SOLN SATS\n")
            stream.write("     1    AS                                                # / TYPES OF DATA\n")
            stream.write("                                                            END OF HEADER\n")
            for i in range(lo, hi):
                t = START + timedelta(seconds=i * DT)
                for j, spec in enumerate(specs):
                    prefix = "AS %-4s %04d %02d %02d %02d %02d %9.6f  1" % (
                        spec["clk_prn"], t.year, t.month, t.day, t.hour, t.minute, float(t.second))
                    stream.write(prefix.ljust(39) + f"{held[i, j]:20.13E}\n")
        hashes.append(dict(file=path.relative_to(output).as_posix(), sha256=sha(path), rows=(hi - lo) * 31))
        mjd = (epoch.date() - date(1858, 11, 17)).days
        indices = np.flatnonzero(valid[lo:hi]) + lo
        prefixes = {i: f" {mjd:5d}{(i - lo) * DT:12.5f} " for i in indices}
        for a, b in itertools.combinations(range(31), 2):
            pa, pb = specs[a]["session_prn"], specs[b]["session_prn"]
            path = output / f"pfd/{pa}_{pb}_{tag}.txt"
            lines = []
            for i in indices:
                value = raw[i, a] - raw[i, b]
                lines.extend([f"{prefixes[i]}{pa} {pb} {value:25.16e}\n",
                              f"{prefixes[i]}{pb} {pa} {-value:25.16e}\n"])
            write(path, "".join(lines))
            hashes.append(dict(file=path.relative_to(output).as_posix(), sha256=sha(path), rows=len(lines)))
        print(f"Prepared day {day + 1}; common epochs {len(indices)}", flush=True)
    table(output / "config/input_hashes.tsv", hashes)
    if epochs == EPOCHS:
        with (CASE / "reference/input_hashes.tsv").open(encoding="utf-8") as stream:
            expected = {r["file"]: r for r in csv.DictReader(stream, delimiter="\t")}
        if len(expected) != len(hashes):
            raise ValueError("Input file count mismatch")
        for row in hashes:
            ref = expected[row["file"]]
            if row["sha256"] != ref["sha256"] or row["rows"] != int(ref["rows"]):
                raise ValueError(f"Generated input differs from the experiment: {row['file']}")
    dump(output / "config/run.json", dict(epochs=epochs, full_case=epochs == EPOCHS,
                                         input_files=len(hashes), full_input_hashes_checked=epochs == EPOCHS))
    print(f"PASS prepared {len(hashes)} files; full reference case: {epochs == EPOCHS}")


def run(output: Path, exe: Path, methods: list[str], jobs: int, timeout: int) -> None:
    if not exe.is_file():
        raise FileNotFoundError(exe)
    require_initialization_support(exe)
    load(output / "config/run.json")
    for method in methods:
        if (output / f"results/{method.lower()}/IEM.txt").exists() or (output / f"logs/{method.lower()}_status.json").exists():
            raise FileExistsError(f"Refusing to overwrite native results: {method}")

    def one(method: str) -> dict:
        name = method.lower()
        environment = os.environ.copy()
        environment["GSTAR_STRICT_INNOVATION_TSV"] = str(output / f"results/{name}/innovations.tsv")
        started = time.perf_counter()
        with (output / f"logs/{name}.log").open("w", encoding="utf-8") as stream:
            try:
                process = subprocess.run([str(exe), f"config/{name}/file_table"], cwd=output,
                                         env=environment, stdin=subprocess.DEVNULL, stdout=stream,
                                         stderr=subprocess.STDOUT, timeout=timeout)
                status = dict(method=method, returncode=process.returncode)
            except subprocess.TimeoutExpired:
                status = dict(method=method, returncode=None, failure="timeout")
        status.update(seconds=time.perf_counter() - started, binary_sha256=sha(exe))
        dump(output / f"logs/{name}_status.json", status)
        print(status, flush=True)
        return status

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(one, methods))
    if any(r["returncode"] != 0 for r in results):
        raise RuntimeError("At least one native run failed; inspect its status/log. Failed methods are excluded from analysis.")


def require_initialization_support(exe: Path) -> None:
    """Reject old engines before a long run; analysis also verifies actual initial values."""
    binary = exe.read_bytes()
    if b"CLOCK_PHASE_INITIALIZATION" not in binary or b"SUMZERO_INITIALIZATION" not in binary:
        raise ValueError("This engine does not expose relative-phase initialization diagnostics. "
                         "Obtain the updated authorized engine from the maintainer; the original 0.1.0 package is insufficient.")


def read_iem(path: Path, epochs: int) -> np.ndarray:
    values = []
    with path.open() as stream:
        for index, line in enumerate(stream, start=3):
            fields = line.split()
            actual = datetime(*map(int, fields[:3])) + timedelta(seconds=float(fields[3]))
            if actual != START + timedelta(seconds=index * DT) or fields[-2] != "IEM":
                raise ValueError(f"Invalid native output epoch/label: {path}")
            values.append(float(fields[-1]))
    result = np.array(values)
    if len(result) != epochs - 3 or not np.isfinite(result).all():
        raise ValueError(f"Incomplete/nonfinite IEM: {path}")
    return result


def analyze(output: Path) -> None:
    verify_assets()
    epochs = load(output / "config/run.json")["epochs"]
    raw, _, _ = clocks()
    q = np.array([spec["diffusion_intensities"][0] for spec in load(CASE / "case.json")["clock_specs"]])
    weights = 1 / np.sqrt(q)
    weights /= weights.sum()
    # The native CLK formatter rounds the original product to 14 significant digits.
    first_clk = np.array([float(f"{x:20.13E}") for x in raw[0]])
    expected = first_clk - weights @ first_clk
    ensembles, status = {}, []
    for method in METHODS + ("NONE",):
        name = method.lower()
        path = output / f"logs/{name}_status.json"
        native_iem = output / f"results/{name}/IEM.txt"
        if not path.exists() and not native_iem.exists():
            continue
        record = load(path) if path.exists() else dict(method=method, returncode=0,
                                                      execution="direct; validated using log and complete IEM")
        status.append(record)
        if record["returncode"] != 0:
            continue
        phases = []
        log = output / f"logs/{name}.log"
        if not log.exists():
            log = output / f"results/{name}/gstar.log"
        with log.open(errors="replace") as stream:
            for line in stream:
                if re.search(r"\[(error|critical)\]|Invalid strict|KKT solve failed", line, re.I):
                    raise ValueError(f"Native numerical error: {line.strip()}")
                if "_INITIALIZATION sat_id=" in line:
                    phases.append(float(line.split("initial_phase=")[1].split()[0]))
        np.testing.assert_allclose(phases, expected, rtol=0, atol=2e-18)
        ensembles[method] = read_iem(output / f"results/{name}/IEM.txt", epochs)
    if not ensembles:
        raise ValueError("No completed initialized native runs to analyze")
    rows = statistics(ensembles, epochs)
    table(output / "analysis/stability_summary.tsv", rows)
    dump(output / "analysis/run_validation.json", dict(epochs=epochs, full_case=epochs == EPOCHS,
                                                       completed_methods=list(ensembles), status=status))
    print(f"PASS native epochs/finite IEM/initial phases; wrote {len(rows)} exact-tau results.")


def main() -> None:
    global CASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fetch", "verify-reference", "prepare", "run", "analyze", "check-engine"])
    parser.add_argument("--data", type=Path, default=CASE)
    parser.add_argument("--archive", type=Path, help="Install a previously downloaded experiment ZIP")
    parser.add_argument("--output", type=Path, default=REPOSITORY / "Runs/gps_rank_initialized")
    parser.add_argument("--epochs", type=int, default=EPOCHS, help="Use a shorter prefix only for a smoke test")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--methods", nargs="+", choices=METHODS + ("NONE",), default=list(METHODS))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=14400)
    args = parser.parse_args()
    CASE = args.data.resolve()
    output = args.output.resolve()
    if args.action == "fetch":
        archive.fetch("experiment", CASE, args.archive, catalog=load(EXAMPLE / "data-release.json"))
    elif args.action == "check-engine":
        if args.exe is None:
            parser.error("check-engine requires --exe")
        require_initialization_support(args.exe)
        print("PASS engine exposes initialization diagnostics; verify actual initial phases after running.")
    elif args.action == "verify-reference":
        verify_reference()
    elif args.action == "prepare":
        prepare(output, args.epochs)
    elif args.action == "run":
        if args.exe is None or args.jobs < 1 or args.timeout < 1:
            parser.error("run requires --exe and positive --jobs/--timeout")
        if len(args.methods) != len(set(args.methods)):
            parser.error("Duplicate methods are not allowed")
        run(output, args.exe.resolve(), args.methods, args.jobs, args.timeout)
    else:
        analyze(output)


if __name__ == "__main__":
    main()
