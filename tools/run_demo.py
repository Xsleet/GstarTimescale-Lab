"""Generate and run a reproducible GSTAR PFD example with phase and ADEV reports.

The default ten-day synthetic example illustrates the workflow, not calibrated clock performance.
All paths inside generated engine configuration are relative to the run directory.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import date, datetime, timedelta
import html
import hashlib
import importlib
import itertools
import json
import math
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import types

REPO_ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1)
INTERVAL = 10
DURATION = 10 * 86400
SATELLITES = ("0101", "0102", "0103", "0104")
ARCHITECTURES = ("centralized", "distributed_if", "distributed_ci")
CLOCK_PROFILES = ("basic", "csac-mro")
HETEROGENEOUS_PROFILE = REPO_ROOT / "examples/heterogeneous/clocks.json"
SNAPSHOT_ROOT = Path(__file__).resolve().parent / "dataprocess_snapshot"
TARGET_TAUS = (10, 30, 100, 300, 1000, 3000, 10000, 30000, 86400)


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def validate_duration(duration_s: int) -> int:
    if isinstance(duration_s, bool) or not isinstance(duration_s, int) or duration_s < 150 or duration_s % INTERVAL:
        raise ValueError("Duration must be at least 150 seconds and an integer multiple of 10 seconds")
    # The engine currently rejects sessions starting after 2026; keep this demo within its fixed year.
    if START + timedelta(seconds=duration_s) > datetime(2027, 1, 1):
        raise ValueError("This fixed-start demo must finish within 2026")
    if duration_s > 86400 and duration_s % 86400 == INTERVAL:
        raise ValueError("The last partial day needs at least two clock samples (20 seconds)")
    return duration_s


def duration_from_days(days: float) -> int:
    if not math.isfinite(days) or days <= 0 or days > 365:
        raise ValueError("--days must be a positive finite duration no greater than 365")
    seconds = days * 86400
    rounded = round(seconds / INTERVAL) * INTERVAL
    if not math.isclose(seconds, rounded, abs_tol=1e-5, rel_tol=0):
        raise ValueError("--days must describe a whole number of 10-second sampling intervals")
    return validate_duration(rounded)


def duration_label(duration_s: int) -> str:
    unit, divisor = ("天", 86400) if duration_s >= 86400 else ("小时", 3600) if duration_s >= 3600 else ("分钟", 60)
    return f"{duration_s / divisor:g} {unit}"


def clock_specs(clock_profile: str, seed: int) -> list[dict]:
    """Describe profiles; csac-mro shares diffusion coefficients with the engine."""
    if clock_profile == "basic":
        return [{"session_prn": satellite, "clock_type": "synthetic WPM",
                 "phase_offset_s": (index + 1) * 1e-6,
                 "frequency_offset": (index - 1.5) * 2e-12,
                 "white_phase_sigma_s": (index + 1) * 1e-10,
                 "phase_initial_std_s": 1e-5, "frequency_initial_std": 1e-10,
                 "phase_process_std": 1e-20, "frequency_process_std": 1e-26,
                 "link_noise_std_s": 1e-9}
                for index, satellite in enumerate(SATELLITES)]
    if clock_profile != "csac-mro":
        raise ValueError(f"Unsupported clock profile: {clock_profile}")
    if seed < 0:
        # Random uses the absolute value of integer seeds; signed offsets could collide.
        raise ValueError("The heterogeneous base seed must be nonnegative")
    definition = json.loads(HETEROGENEOUS_PROFILE.read_text(encoding="utf-8"))
    specs = definition["clocks"]
    if ([item["session_prn"] for item in specs] != list(SATELLITES)
            or [item["clock_type"] for item in specs] != ["CSAC", "CSAC", "mRO", "mRO"]):
        raise ValueError("The heterogeneous profile must define two CSAC and two mRO clocks in order")
    for spec in specs:
        for key in ("phase_offset_s", "frequency_offset", "wfm_coefficient", "rwfm_coefficient"):
            if not math.isfinite(spec[key]):
                raise ValueError(f"Nonfinite clock parameter: {key}")
        if min(spec["wfm_coefficient"], spec["rwfm_coefficient"]) <= 0:
            raise ValueError("Heterogeneous diffusion coefficients must be positive")
        spec.update({"seed": seed + spec["seed_offset"],
                     "phase_process_std": spec["wfm_coefficient"],
                     "frequency_process_std": math.sqrt(6) * spec["rwfm_coefficient"]})
        for key in ("phase_initial_std_s", "frequency_initial_std", "link_noise_std_s"):
            value = definition[key]
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid uncertainty: {key}")
            spec[key] = value
    return specs


def diffusion_step(phase: float, frequency: float, dt: float,
                   phase_std: float, frequency_std: float, rng: random.Random) -> tuple[float, float]:
    """Exact two-state Gaussian transition, including phase/frequency covariance.

    Q = [[a*a*dt + b*b*dt**3/3, b*b*dt**2/2], [b*b*dt**2/2, b*b*dt]].
    The Brownian bridge term is necessary; simply integrating endpoint frequency
    would produce the wrong phase variance and phase/frequency covariance.
    """
    white, walk, bridge = (rng.gauss(0.0, 1.0) for _ in range(3))
    root_dt = math.sqrt(dt)
    phase += frequency * dt + phase_std * root_dt * white
    phase += frequency_std * dt * root_dt * (walk / 2 + bridge / math.sqrt(12))
    frequency += frequency_std * root_dt * walk
    return phase, frequency


def clock_series(seed: int = 2026, duration_s: int = DURATION,
                 clock_profile: str = "basic") -> dict[str, list[float]]:
    """Generate phase seconds using the selected reproducible clock model."""
    validate_duration(duration_s)
    specs = clock_specs(clock_profile, seed)
    if clock_profile == "csac-mro":
        series = {}
        for spec in specs:
            rng = random.Random(spec["seed"])
            phase, frequency = spec["phase_offset_s"], spec["frequency_offset"]
            phases = [phase]
            for _ in range(1, duration_s // INTERVAL):
                phase, frequency = diffusion_step(phase, frequency, INTERVAL,
                    spec["phase_process_std"], spec["frequency_process_std"], rng)
                phases.append(phase)
            series[spec["session_prn"]] = phases
        return series
    rng = random.Random(seed)
    return {
        satellite: [
            (index + 1) * 1e-6
            + (index - 1.5) * 2e-12 * step * INTERVAL
            + rng.gauss(0.0, (index + 1) * 1e-10)
            for step in range(duration_s // INTERVAL)
        ]
        for index, satellite in enumerate(SATELLITES)
    }


def gstar_number(value: float) -> str:
    # Match the fixed-width RINEX reader and the verified research input writer.
    if not math.isfinite(value):
        raise ValueError("Clock values must be finite")
    if abs(value) < 1e-99:
        return " 0.000000000000E+00"
    exponent = math.floor(math.log10(abs(value)) + 1.0)
    mantissa = f"{abs(value) / 10.0 ** (exponent - 12):012.0f}"
    return f"{'-0' if value < 0 else ' 0'}.{mantissa}E{exponent:+03d}"


def prepare_case(root: Path, architecture: str, seed: int = 2026, duration_s: int = DURATION,
                 clock_profile: str = "basic") -> dict[str, list[float]]:
    validate_duration(duration_s)
    specs = clock_specs(clock_profile, seed)
    if architecture not in ARCHITECTURES:
        raise ValueError(f"Unsupported architecture: {architecture}")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError(f"Output directory is not empty: {root}. Choose a new --output directory.")
    for name in ("config", "clocks_raw", "clk", "pfd", "logs", "results", "analysis", "figures", "tools"):
        (root / name).mkdir(parents=True, exist_ok=True)
    series = clock_series(seed, duration_s, clock_profile)
    sample_count = duration_s // INTERVAL
    for satellite, phases in series.items():
        write_text(root / f"clocks_raw/{satellite}.txt", "# phase_seconds\n" + "".join(f"{phase:.17e}\n" for phase in phases))
    daily_counts = []
    for day_index in range(math.ceil(duration_s / 86400)):
        day = START + timedelta(days=day_index)
        tag = f"{day.year}{day.timetuple().tm_yday:03d}"
        first_step = day_index * (86400 // INTERVAL)
        final_step = min(first_step + 86400 // INTERVAL, sample_count)
        daily_counts.append(final_step - first_step)
        clk_path = root / f"clk/SIM0MGNFIN_{tag}0000_01D_10S_CLK.CLK"
        with clk_path.open("w", encoding="ascii", newline="\n") as stream:
            stream.write("     3.00           C                                       RINEX VERSION / TYPE\n")
            stream.write("GSTAR synthetic getting-started example                      COMMENT\n")
            stream.write(f"{INTERVAL:10.2f}                                                  INTERVAL\n")
            stream.write(f"{len(SATELLITES):6d}                                                      # OF SOLN SATS\n")
            stream.write(" ".join(SATELLITES).ljust(60) + "PRN LIST\n")
            stream.write("     1    AS                                                # / TYPES OF DATA\n")
            stream.write("                                                            END OF HEADER\n")
            for step in range(first_step, final_step):
                epoch = START + timedelta(seconds=step * INTERVAL)
                for satellite in SATELLITES:
                    stream.write(
                        "AS %-4s %04d %02d %02d %02d %02d %9.6f  1   %-20s%-20s\n"
                        % (str(int(satellite)), epoch.year, epoch.month, epoch.day,
                           epoch.hour, epoch.minute, float(epoch.second),
                           gstar_number(series[satellite][step]), gstar_number(1e-12))
                    )
        mjd = (day.date() - date(1858, 11, 17)).days
        for left, right in itertools.combinations(SATELLITES, 2):
            with (root / f"pfd/{left}_{right}_{tag}.txt").open("w", encoding="ascii", newline="\n") as stream:
                for step in range(first_step, final_step):
                    difference = series[left][step] - series[right][step]
                    sod = (step - first_step) * INTERVAL
                    for receiver, sender, value in ((left, right, difference), (right, left, -difference)):
                        stream.write(f" {mjd:5d}{sod:12.5f} {receiver:>4s} {sender:>4s} {value:25.16e}\n")
    session = ["+GNSS satellite", "-GNSS satellite", "", '+LEO used = ""']
    for spec in specs:
        satellite = spec["session_prn"]
        parameters = (f"{{TotalPhase:[{spec['phase_initial_std_s']:.16e},{spec['phase_process_std']:.16e}], "
                      f"Phase:[{spec['phase_initial_std_s']:.16e},{spec['phase_process_std']:.16e}], "
                      f"Frequency:[{spec['frequency_initial_std']:.16e},{spec['frequency_process_std']:.16e}], "
                      f"Drift:[1e-11,0], Link_Noise:{{Default:{spec['link_noise_std_s']:.16e}}}}}")
        if clock_profile == "basic":
            parameters = ("{TotalPhase:[1e-5,1e-20], Phase:[1e-5,1e-20], "
                          "Frequency:[1e-10,1e-26], Drift:[1e-11,0], WPM:1e-20, Link_Noise:{Default:1e-9}}")
        session.append(
            f" 000 {satellite}  {satellite}  FIX FIX NON P    "
            "7.0 30000. 300.  10.0  10.0  10.0   0.10   0.10   0.10 "
            "1.e5 1.e5 1.e5 1.e5 1.e5 1.e5 1.e5 1.e5 1.e5 1.e5 1.e5 1.e5      "
            + parameters
        )
    session.extend(["-LEO used", "", "+GNSS site", "-GNSS site", ""])
    write_text(root / "config/session.obj", "\n".join(session))
    # Fixed-column satellite metadata layout expected by the runtime (PART 2).
    rows = []
    for index, satellite in enumerate(SATELLITES, 1):
        columns = list(" " * 130)
        for offset, value in ((0, satellite), (6, satellite), (12, "LEO"),
                              (19, f"SIM {index}"), (52, "2020 01 01 00 00 00"),
                              (89, "  601.2"), (98, f"SIM{index}")):
            columns[offset:offset + len(value)] = value
        rows.append("".join(columns))
    write_text(root / "config/svinf.dat", "PART 2: PHYSICAL NON-GNSS SATELLITE PARAMETERS\n" + "\n".join(rows) + "\n")
    shutil.copyfile(REPO_ROOT / "config/leap.sec", root / "config/leap.sec")
    write_text(root / "config/pan_info", "* No solar panel model is used in the PFD demo.\n")
    write_text(root / "config/Timescale.cfg", f"""* Synthetic PFD example; research preset, not calibrated clock noise.
 Start time&session length   = 2026 01 01 00 00 00 {duration_s} [GPST]
 Processing interval         = {INTERVAL}
+File Directory
 Project directory           = results
 GNSS Sp3 full name          = unused/-YEARDOY-.SP3
 GNSS Clk full name          = clk/SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK
 LEO Sp3 full name           = unused/-YEARDOY-.SP3
 LEO Clk full name           = clk/SIM0MGNFIN_-YEARDOY-0000_01D_10S_CLK.CLK
 ISL data directory          = unused/isl
 PFD data directory          = pfd
-File Directory
+Timescale Section
 Timescale scope             = satellite
 Clock Trend state num       = 2
 Clock Harmonics state num   = 0
 Rank deficiency remedy      = GREENHALL
 Estimation architecture     = {architecture}
 Distributed output mode     = auto
 SUMZERO constraint sigma    = 1e-14
-Timescale Section
+Orbit and Clock Section
 GNSS Apriori orbit          = spp
 GNSS Apriori clock          = prec
 LEO Apriori orbit           = spp
 LEO Apriori clock           = prec
-Orbit and Clock Section
+Output Section
 Clock state output flag     = 1
 Log level                   = info
-Output Section
""")
    write_text(root / "config/file_table", """+FileTable
 TimescaleCfg config/Timescale.cfg
 object config/session.obj
 satinf config/svinf.dat
 leapsc config/leap.sec
 paninf config/pan_info
-FileTable
""")
    manifest = {"purpose": "synthetic smoke example; no stability-performance claim",
                "start_gpst": START.isoformat(), "duration_s": duration_s,
                "duration_days": duration_s / 86400,
                "interval_s": INTERVAL, "samples_per_clock": sample_count,
                "daily_samples_per_clock": daily_counts,
                "clk_files": len(daily_counts), "pfd_files": len(daily_counts) * 6,
                "satellites": list(SATELLITES), "architecture": architecture, "seed": seed,
                "clock_profile": clock_profile, "clock_specs": specs,
                "clock_model": ("white frequency noise + random-walk frequency noise; exact two-state diffusion"
                                if clock_profile == "csac-mro" else
                                "nonzero phase offset + constant frequency + Gaussian phase noise")}
    if clock_profile == "csac-mro":
        definition = HETEROGENEOUS_PROFILE.read_text(encoding="utf-8")
        write_text(root / "config/clock_profile.json", definition)
        manifest["clock_profile_sha256"] = hashlib.sha256(definition.replace("\r\n", "\n").encode()).hexdigest()
    write_text(root / "config/manifest.json", json.dumps(manifest, indent=2) + "\n")
    write_text(root / "config/satellite_mapping.tsv", "session_prn\tclk_record_prn\tproduct_name\tclock_type\n" +
               "".join(f"{spec['session_prn']}\t{int(spec['session_prn'])}\tSIM{index}\t{spec['clock_type']}\n"
                       for index, spec in enumerate(specs, 1)))
    yaml_clocks = "".join("  - " + "\n    ".join(f"{key}: {json.dumps(value)}" for key, value in spec.items()) + "\n" for spec in specs)
    write_text(root / "config/clock_manifest.yaml", f"start_time_gpst: '{START.isoformat()}'\nduration_s: {duration_s}\nsample_interval_s: {INTERVAL}\nseed: {seed}\nclock_profile: {clock_profile}\nclock_model: {manifest['clock_model']}\nsatellites:\n" + yaml_clocks)
    write_text(root / "README.txt", "GSTAR synthetic quick-start case\n\n"
               "Run the engine from this directory with argument config/file_table.\n"
               "Open report.html after run_demo.py completes. summary.json records validation.\n"
               "phase.csv uses seconds. PFD is receiver phase minus sender phase.\n"
               "ADEV compares four raw clocks and the selected ensemble on common epochs.\n"
               "The synthetic clock model is not a calibrated model of a physical clock.\n")
    write_text(root / "README.md", f"# GSTAR {duration_label(duration_s)} PFD case\n\n"
               f"4 clocks; {sample_count} samples/clock; {INTERVAL} s interval; {architecture}.\n\n"
               "Open report.html for phase and five-series ADEV results.\n"
               "Configuration and clock-noise parameters are recorded in config/.\n"
               "The case uses synthetic clocks rather than calibrated device noise.\n\n"
               "Reproduce from the GSTAR repository root, using a new output directory:\n\n"
               f"```text\npython tools/run_demo.py --clock-profile {clock_profile} --days {duration_s / 86400:.17g} "
               f"--seed {seed} --architecture {architecture} --exe <GstarTimescale.exe> --output <new-run-directory>\n```\n")
    return series


def read_iem(path: Path, duration_s: int = DURATION) -> list[tuple[float, float]]:
    validate_duration(duration_s)
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split()
        if not parts or parts[0].startswith(("%", "#")):
            continue
        if len(parts) < 6 or parts[-2] != "IEM":
            raise ValueError(f"Invalid IEM row at {path}:{line_number}")
        epoch = datetime(int(parts[0]), int(parts[1]), int(parts[2])) + timedelta(seconds=float(parts[3]))
        elapsed = (epoch - START).total_seconds()
        value = float(parts[-1])
        if not all(math.isfinite(float(token)) for token in parts if token != "IEM"):
            raise ValueError(f"Nonfinite value at {path}:{line_number}")
        if elapsed < 0 or elapsed >= duration_s or (rows and elapsed <= rows[-1][0]):
            raise ValueError(f"Unexpected IEM epoch at {path}:{line_number}")
        rows.append((elapsed, value))
    expected_rows = duration_s // INTERVAL - 3
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} IEM records after three warm-up epochs; found {len(rows)} in {path}")
    if rows[0][0] != 3 * INTERVAL or rows[-1][0] != duration_s - INTERVAL:
        raise ValueError(f"IEM does not cover the expected session boundaries: {path}")
    if any(abs(b[0] - a[0] - INTERVAL) > 1e-6 for a, b in zip(rows, rows[1:])):
        raise ValueError(f"IEM output contains gaps: {path}")
    return rows


def check_engine_logs(root: Path) -> None:
    error_marker = re.compile(r"\[(?:error|critical)\]|(?:\*{3}|#{3})\s*error", re.IGNORECASE)
    for relative in ("logs/console.log", "results/gstar.log"):
        path = root / relative
        content = path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            raise ValueError(f"Empty engine log: {path}")
        if error_marker.search(content):
            raise ValueError(f"Engine reported an error; inspect {path}")


def check_analysis_dependencies() -> None:
    try:
        for name in ("numpy", "matplotlib", "pandas", "allantools"):
            importlib.import_module(name)
    except ImportError as exc:
        raise ValueError("ADEV reporting dependencies are missing. Install requirements-demo.txt "
                         "with this Python interpreter; see docs/troubleshooting.md.") from exc


def read_common_origins(selected: Path, iem_rows: list[tuple[float, float]]) -> dict[str, list[float]]:
    """Require identical absolute epochs; never close gaps by independently dropping NaNs."""
    expected_times = [time for time, _ in iem_rows]
    origins = {}
    for index, satellite in enumerate(SATELLITES, 1):
        path = selected.parent / f"SIM{index}.txt"
        values, times = [], []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            parts = line.split()
            if not parts or parts[0].startswith(("#", "%")):
                continue
            if len(parts) != 9:  # Fixed two-state demo: date/SoD, three raw, two estimated.
                raise ValueError(f"Expected two-state clock product at {path}:{number}")
            if not all(math.isfinite(float(value)) for value in parts):
                raise ValueError(f"Nonfinite clock product at {path}:{number}")
            epoch = datetime(int(parts[0]), int(parts[1]), int(parts[2])) + timedelta(seconds=float(parts[3]))
            times.append((epoch - START).total_seconds())
            values.append(float(parts[4]))  # Original phase, not the per-clock residual.
        if times != expected_times:
            raise ValueError(f"ADEV requires identical common epochs for IEM and {path.name}; "
                             "missing, shifted, or duplicated epochs cannot be dropped independently.")
        origins[f"SIM{index}"] = values
    return origins


def build_adev_report(root: Path, selected: Path, rows: list[tuple[float, float]]) -> dict:
    """Execute the existing DataProcess cells; export exact-tau AllanTools statistics."""
    import allantools
    import matplotlib
    import numpy as np

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    origins = read_common_origins(selected, rows)
    series = {**origins, "Ensemble": [value for _, value in rows]}
    provenance = json.loads((SNAPSHOT_ROOT / "provenance.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "config/manifest.json").read_text(encoding="utf-8"))
    heterogeneous = manifest.get("clock_profile", "basic") == "csac-mro"
    series_labels = {f"SIM{index}": f"SIM{index} ({spec['clock_type']})"
                     for index, spec in enumerate(manifest.get("clock_specs", []), 1)} if heterogeneous else {}
    for cell in provenance["cells"].values():
        source = (SNAPSHOT_ROOT / cell["file"]).read_bytes()
        # Git's Windows checkout may translate LF into CRLF.
        digest = hashlib.sha256(source.replace(b"\r\n", b"\n")).hexdigest()
        if digest != cell["export_sha256"]:
            raise ValueError(f"DataProcess snapshot hash mismatch: {cell['file']}")
    for directory in ("analysis", "figures"):
        (root / directory).mkdir(exist_ok=True)
    module_name = "_gstar_demo_dataprocess"
    module = types.ModuleType(module_name)
    module.__file__ = str(SNAPSHOT_ROOT / "helpers.py")
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    namespace = module.__dict__
    saved = {}
    original_show = plt.show
    existing_figures = set(plt.get_fignums())

    def save_show(*_args: object, **_kwargs: object) -> None:
        figure = plt.gcf()
        axis = figure.axes[0]
        labels = [line.get_label() for line in axis.lines]
        expected_labels = {f"SIM{index} - origin" for index in range(1, 5)} | {"Ensemble - estimate"}
        if len(axis.lines) != 5 or set(labels) != expected_labels:
            raise ValueError(f"Expected four original clocks and one ensemble in ADEV figure; got {labels}")
        if heterogeneous:
            for line in axis.lines:
                name = line.get_label().split(" - ")[0]
                if name in series_labels:
                    line.set_label(f"{series_labels[name]} - origin")
            axis.set_title("Stability Comparison: 2 CSAC + 2 mRO vs Ensemble (ADEV)")
            axis.legend()
        saved["curve_labels"] = [line.get_label() for line in axis.lines]
        figure.savefig(root / "figures/adev.svg", bbox_inches="tight")
        figure.savefig(root / "figures/adev.png", dpi=180, bbox_inches="tight")
        figure.savefig(root / "figures/adev.pdf", bbox_inches="tight")
        plt.close(figure)

    try:
        with plt.rc_context(), (root / "logs/adev.log").open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log):
                exec(compile((SNAPSHOT_ROOT / "helpers.py").read_text(encoding="utf-8"), module.__file__, "exec"), namespace)
                plt.rcParams.update({"text.usetex": False, "font.family": "DejaVu Sans",
                                     "font.size": 10, "svg.fonttype": "none"})
                namespace.update({"REPORT_BASE_PATH": str(selected.parent),
                                  "REPORT_ORIGIN_IDS": list(origins),
                                  "REPORT_SCHEMA": namespace["SchemaConfig"](
                                      trend_state=2, num_harmonics=0, rate_hz=1 / INTERVAL, dev_mode="adev")})
                plt.show = save_show
                path = SNAPSHOT_ROOT / "frequency_stability.py"
                exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    finally:
        plt.show = original_show
        for figure_number in set(plt.get_fignums()) - existing_figures:
            plt.close(figure_number)
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
    if "curve_labels" not in saved:
        raise ValueError("DataProcess frequency cell did not produce an ADEV figure")
    plotted = {**namespace["origin_dev_results"], **namespace["ens_dev_results"]}
    if set(plotted) != set(series):
        raise ValueError("Missing original-clock or ensemble ADEV results")
    fields = ["series", "tau_s", "adev", "adev_error", "sample_count", "phase_samples"]
    target_taus = [tau for tau in TARGET_TAUS if (len(rows) - 1) // (tau // INTERVAL) - 1 >= 2]
    if not target_taus:
        raise ValueError("The common time window is too short for the target ADEV statistics")

    def calculate_table(path: Path, taus: object, check_plot: bool = False) -> list[dict]:
        table, reference_tau, reference_count = [], None, None
        for name, phases in series.items():
            tau, adev, errors, counts = allantools.adev(
                np.asarray(phases), rate=1 / INTERVAL, data_type="phase", taus=taus)
            if not len(tau) or not np.all(np.isfinite([tau, adev, errors, counts])) or np.any(adev <= 0) or np.any(counts < 2):
                raise ValueError(f"Invalid or insufficient ADEV results for {name}")
            if reference_tau is None:
                reference_tau, reference_count = tau, counts
            elif not (np.array_equal(tau, reference_tau) and np.array_equal(counts, reference_count)):
                raise ValueError("ADEV tau or sample counts differ across the five common-window series")
            if check_plot:
                for actual, plotted_values in zip((tau, adev, errors), plotted[name]):
                    np.testing.assert_allclose(actual, plotted_values, rtol=1e-12, atol=0)
            elif not np.array_equal(tau, np.asarray(target_taus, dtype=float)):
                raise ValueError("The example cannot support all requested target taus")
            for values in zip(tau, adev, errors, counts):
                table.append(dict(zip(fields, [name, float(values[0]), float(values[1]),
                                               float(values[2]), int(values[3]), len(phases)])))
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(table)
        return table

    curve_table = calculate_table(root / "analysis/adev.tsv", "octave", check_plot=True)
    target_table = calculate_table(root / "analysis/stability_summary.tsv", target_taus)
    metadata = {"method": "allantools.adev", "data_type": "phase", "phase_unit": "s",
                "adev_unit": "dimensionless fractional frequency", "rate_hz": 1 / INTERVAL,
                "series": list(series), "phase_samples": len(rows),
                "first_elapsed_s": rows[0][0], "last_elapsed_s": rows[-1][0],
                "curve_taus_s": [item["tau_s"] for item in curve_table if item["series"] == "Ensemble"],
                "target_taus_s": target_taus, "requested_target_taus_s": list(TARGET_TAUS),
                "target_sample_counts": [item["sample_count"] for item in target_table if item["series"] == "Ensemble"],
                "target_rows": target_table, "curve_labels": saved["curve_labels"],
                "series_labels": series_labels,
                "selected_iem": selected.relative_to(root).as_posix(),
                "source_notebook": provenance["source"], "source_sha256": provenance["notebook_sha256"],
                "definition_cell": 35, "frequency_stability_cell": 43,
                "allantools_version": allantools.__version__,
                "sample_count_definition": "second-difference terms used by non-overlapping ADEV; not independent degrees of freedom",
                "error_definition": "AllanTools returned error estimate (adev / sqrt(sample_count)); not a confidence interval"}
    with (root / "analysis/dataprocess_frequency_cell.tsv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["source_notebook", "source_sha256", "definition_cell", "frequency_cell", "iem_path", "origin_ids", "rate_hz", "phase_samples"])
        writer.writerow([provenance["source"], provenance["notebook_sha256"], 35, 43,
                         selected.relative_to(root).as_posix(), ",".join(origins), 1 / INTERVAL, len(rows)])
    return metadata


def phase_display_indices(values: list[float], max_points: int = 2000) -> list[int]:
    """Preserve extrema and endpoints for display only; analysis always uses every sample."""
    if len(values) <= max_points:
        return list(range(len(values)))
    bucket_size = math.ceil(len(values) / ((max_points - 2) // 2))
    selected = {0, len(values) - 1}
    for first in range(0, len(values), bucket_size):
        last = min(first + bucket_size, len(values))
        selected.add(min(range(first, last), key=values.__getitem__))
        selected.add(max(range(first, last), key=values.__getitem__))
    return sorted(selected)


def write_report(root: Path, architecture: str, *, engine_ran: bool = False) -> dict:
    manifest = json.loads((root / "config/manifest.json").read_text(encoding="utf-8"))
    duration_s = validate_duration(manifest["duration_s"])
    clock_profile = manifest.get("clock_profile", "basic")
    if clock_profile not in CLOCK_PROFILES:
        raise ValueError(f"Unknown saved clock profile: {clock_profile}")
    heterogeneous = clock_profile == "csac-mro"
    specs = manifest.get("clock_specs", [])
    if heterogeneous and ([spec["session_prn"] for spec in specs] != list(SATELLITES)
                          or [spec["clock_type"] for spec in specs] != ["CSAC", "CSAC", "mRO", "mRO"]):
        raise ValueError("Saved heterogeneous manifest must identify all four clock types")
    iem_paths = sorted((root / "results").rglob("IEM.txt"))
    expected = 4 if architecture == "distributed_ci" else 1
    if len(iem_paths) != expected:
        raise ValueError(f"Expected {expected} IEM output files; found {len(iem_paths)}")
    parsed = {path: read_iem(path, duration_s) for path in iem_paths}
    selected = iem_paths[0]
    rows = parsed[selected]
    origins = read_common_origins(selected, rows)
    adev = build_adev_report(root, selected, rows)
    with (root / "phase.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["elapsed_s", *[f"{sat}_phase_s" for sat in SATELLITES], "iem_phase_s"])
        for index, (elapsed, value) in enumerate(rows):
            writer.writerow([elapsed, *[origins[f"SIM{clock}"][index] for clock in range(1, 5)], value])
    summary = {"status": "passed", "architecture": architecture,
               "clock_profile": clock_profile, "clock_specs": specs,
               "duration_s": duration_s, "duration_days": duration_s / 86400,
               "input_epochs": duration_s // INTERVAL, "interval_s": INTERVAL,
               "selected_iem": selected.relative_to(root).as_posix(),
               "outputs": [{"path": p.relative_to(root).as_posix(), "rows": len(data),
                            "first_elapsed_s": data[0][0], "last_elapsed_s": data[-1][0]}
                           for p, data in parsed.items()],
               "execution": {"mode": "engine_run" if engine_ran else "report_refresh_only",
                             "engine_exit_code": 0 if engine_ran else None},
               "checks": (["engine exit code zero"] if engine_ran else []) + ["engine logs contain no error/critical markers", "expected IEM files exist", "all IEM numeric fields finite",
                          "strictly increasing epochs at 10-second intervals", "complete session after exactly three warm-up epochs",
                          "all five phase series share identical epochs", "five ADEV curves from the DataProcess cells",
                          "target taus calculated directly with matching sample counts"],
               "adev": adev,
               "scope": "synthetic phase/ADEV demonstration; not a calibrated physical-clock or architecture-accuracy validation"}
    # Both plots use the same saved clock products; only the phase chart is handwritten SVG.
    curves = [origins[f"SIM{clock}"] for clock in range(1, 5)]
    curves.append([value for _, value in rows])
    # Remove each curve's own first value so microsecond offsets do not hide its changes.
    curves = [[(value - values[0]) * 1e9 for value in values] for values in curves]
    low = min(min(values) for values in curves)
    high = max(max(values) for values in curves)
    span = max(high - low, 1e-6)
    low, high = low - span * 0.08, high + span * 0.08
    colors = ["#2563eb", "#d97706", "#059669", "#9333ea", "#dc2626"]
    elements = ['<rect x="0" y="0" width="1000" height="420" fill="white"/>']
    for index in range(6):
        y = 25 + index * 65
        value = high - index * (high - low) / 5
        elements.append(f'<path d="M130 {y}H970" stroke="#e2e8f0"/><text x="120" y="{y + 5}" text-anchor="end">{value:.2f}</text>')
    time_divisor, time_unit = (86400, "days") if duration_s >= 86400 else (3600, "hours") if duration_s >= 7200 else (60, "minutes")
    for tick in range(6):
        x = 130 + tick / 5 * 840
        value = duration_s / time_divisor * tick / 5
        elements.append(f'<text x="{x}" y="380" text-anchor="middle">{value:g}</text>')
    display_counts = []
    for values, color in zip(curves, colors):
        indices = phase_display_indices(values)
        display_counts.append(len(indices))
        points = " ".join(f"{130 + rows[i][0] / duration_s * 840:.2f},{25 + (high - values[i]) / (high - low) * 325:.2f}" for i in indices)
        elements.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8"/>')
    elements.extend([f'<text x="550" y="412" text-anchor="middle">Elapsed time ({time_unit})</text>',
                     '<text transform="translate(20 210) rotate(-90)" text-anchor="middle">Phase change (ns)</text>'])
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 420" role="img" aria-label="Raw clock and ensemble phase changes">' + "".join(elements) + "</svg>"
    write_text(root / "figures/phase.svg", svg)
    summary["phase_plot"] = {"display_sample_counts": display_counts, "full_sample_count": len(rows),
                             "method": "time buckets preserving min/max and endpoints; display only",
                             "adev_and_csv_use_full_series": True}
    write_text(root / "summary.json", json.dumps(summary, indent=2) + "\n")
    phase_names = [f"{spec['session_prn']} ({spec['clock_type']})" for spec in specs] if heterogeneous else list(SATELLITES)
    legend = " ".join(f'<span style="color:{color};margin-right:20px">● {html.escape(name)}</span>' for name, color in zip([*phase_names, "IEM"], colors))
    output_links = "".join(f'<li><a href="{html.escape(p.relative_to(root).as_posix())}">{html.escape(p.relative_to(root).as_posix())}</a> — {len(data)} rows</li>' for p, data in parsed.items())
    adev_svg = (root / "figures/adev.svg").read_text(encoding="utf-8")
    adev_svg = adev_svg[adev_svg.index("<svg"):]
    lookup = {(row["series"], row["tau_s"]): row for row in adev["target_rows"]}
    adev_table_rows = "".join(
        f'<tr><td>{tau}</td>'
        + "".join(f'<td>{lookup[(name, tau)]["adev"]:.3e}</td>' for name in adev["series"])
        + f'<td>{lookup[("Ensemble", tau)]["sample_count"]}</td></tr>'
        for tau in adev["target_taus_s"])
    longest_tau = adev["target_taus_s"][-1]
    longest_count = adev["target_sample_counts"][-1]
    period_label = duration_label(duration_s)
    case_title = "2 CSAC + 2 mRO 异构时钟" if heterogeneous else "第一次运行"
    model_section = ""
    if heterogeneous:
        model_rows = "".join(f"<tr><td>SIM{index} / {spec['session_prn']}</td><td>{spec['clock_type']}</td>"
                             f"<td>{spec['seed']}</td><td>{spec['phase_process_std']:.5e}</td>"
                             f"<td>{spec['frequency_process_std']:.5e}</td></tr>"
                             for index, spec in enumerate(specs, 1))
        model_section = ("<section><h2>时钟模型与分组</h2><p>SIM1、SIM2 为 CSAC；SIM3、SIM4 为 mRO。"
                         "各钟独立生成白频噪声与频率随机游走，滤波器使用相同的扩散系数。"
                         "本组参数中 mRO 白频噪声较小，CSAC 频率随机游走较小，可观察不同 τ 区间的互补性。</p>"
                         "<p>模型为 dx = y dt + a dW₁，dy = b dW₂；a 的单位为 s/√s，b 的单位为 1/√s。"
                         "以下 a、b 是扩散系数，不是指定 τ 上的 ADEV。</p>"
                         "<div class='table-wrap'><table><thead><tr><th>曲线 / 编号</th><th>类型</th><th>随机种子</th>"
                         f"<th>白频扩散系数 a</th><th>频率游走系数 b</th></tr></thead><tbody>{model_rows}</tbody></table></div>"
                         "<p>参数来自已有研究案例，未作物理设备标定。本例保留二状态模型，不加入固定频率漂移、RRFM 或闪烁噪声；"
                         "PFD 为无附加噪声的钟差，配置中的链路噪声为滤波不确定度下限。"
                         "<a href='config/clock_profile.json'>模型来源</a> / <a href='config/clock_manifest.yaml'>实际参数</a>。</p></section>")
    display_note = (f"相位图为减小页面体积，每条曲线最多显示 {max(display_counts)} 个保留分桶极值和首末值的点；CSV、ADEV 使用全部 {len(rows)} 点。"
                    if len(rows) > max(display_counts) else "相位图、CSV、ADEV 均使用全部有效样本。")
    status_text = ("运行、结果完整性与 ADEV 分析检查通过" if engine_ran
                   else "已有结果完整性与 ADEV 分析检查通过（仅刷新报告）")
    write_text(root / "report.html", f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GSTAR · Quick-start results</title>
<style>body{{max-width:1100px;margin:40px auto;padding:0 24px;color:#172033;background:#f5f7fb;font:16px/1.7 system-ui,sans-serif}}h1{{line-height:1.2}}svg{{width:100%;height:auto;border-radius:12px}}section{{background:white;padding:24px;margin:24px 0;border-radius:12px}}a{{color:#1d4ed8}}code{{background:#e8edf5;padding:2px 6px}}.ok{{color:#047857}}.adev-figure{{max-width:760px;margin:auto}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}}th,td{{padding:8px;border-bottom:1px solid #e2e8f0;text-align:right}}</style>
<h1>GSTAR Timescale · {case_title}</h1><p class="ok">{status_text}</p>
<p>4 个合成钟 · 2026-01-01 GPST · {period_label} · 10 秒采样 · {html.escape(architecture)}</p>
{model_section}
<section><h2>1. 相位随时间的变化</h2><p>每条曲线减去自己的首个有效相位，纵轴单位为纳秒。原始数据及 IEM 的绝对相位仍保存在 CSV 和原始输出中。此图用于认识数据，不证明某种算法更优。</p>
<p>{legend}</p>{svg}<p>IEM 来源：<code>{html.escape(selected.relative_to(root).as_posix())}</code>。有效结果 {len(rows)} 行，时间 {rows[0][0]:g}–{rows[-1][0]:g} 秒；输入边界可能因插值被略去。</p><p>{display_note}</p></section>
<section><h2>2. 五条曲线的 Allan 偏差（ADEV）</h2><p>SIM1–SIM4 对应 0101–0104 的原始钟相位，Ensemble 是上面选定 IEM 的组合时间尺度。五条曲线使用同一段 {len(rows)} 点数据（{rows[0][0]:g}–{rows[-1][0]:g} s），采样率 0.1 Hz；没有分别丢弃缺测或使用单钟残差冒充原始钟。</p>
<div class="adev-figure">{adev_svg}</div><p>横轴 τ 为平均时间（秒），纵轴为无量纲分数频率 ADEV，采用非重叠 <code>allantools.adev</code>。曲线复用 DataProcess 的既有分析与绘图单元，显示默认倍频 τ 网格。</p>
<h3>指定 τ 的数值比较</h3><p>以下各点直接按指定 τ 计算，没有从图中插值。n 是参与 ADEV 计算的二阶差分项数，五条序列相同；不是独立自由度。最长目标 τ={longest_tau:g} s 时 n={longest_count}；长 τ 的统计支持仍需结合 n 判断。</p>
<div class="table-wrap"><table><thead><tr><th>τ (s)</th><th>SIM1</th><th>SIM2</th><th>SIM3</th><th>SIM4</th><th>Ensemble</th><th>n</th></tr></thead><tbody>{adev_table_rows}</tbody></table></div>
<p>这是 {period_label}合成信号的频稳分析，尚不能代表经标定的物理钟性能。<a href="analysis/stability_summary.tsv">下载精确 τ 表</a>（含 AllanTools 返回误差），或导出 <a href="figures/adev.png">PNG</a> / <a href="figures/adev.pdf">PDF</a> / <a href="figures/adev.svg">SVG</a>。</p></section>
<section><h2>文件在哪里</h2><ul><li><a href="phase.csv">phase.csv</a>：原始四钟与一个选定 IEM，数值单位为秒。</li><li><a href="analysis/adev.tsv">analysis/adev.tsv</a>：五条 ADEV 曲线的数值、误差及样本数。</li><li><a href="analysis/dataprocess_frequency_cell.tsv">分析来源记录</a> / <a href="logs/adev.log">ADEV 日志</a>。</li><li><a href="summary.json">summary.json</a>：各输出的检查结果。</li><li><a href="logs/console.log">logs/console.log</a> / <a href="results/gstar.log">results/gstar.log</a>：运行日志。</li>{output_links}</ul></section>
<section><h2>下一步</h2><p>查看仓库 README 和 docs/results.md，了解钟差、组合时间尺度及输出字段。正式研究还需校准噪声模型、完整参数记录及统计检验；本报告沿用既有 DataProcess ADEV 流程。</p></section></html>
""")
    write_text(root / "analysis/validation_report.txt", "GSTAR demonstration validation: PASS\n" +
               f"Duration: {duration_s} s; input samples/clock: {duration_s // INTERVAL}\n" +
               f"Common valid phase samples: {len(rows)}; start: {rows[0][0]} s; end: {rows[-1][0]} s\n" +
               "\n".join(summary["checks"]) + "\n" +
               f"ADEV target taus: {adev['target_taus_s']}\nADEV sample counts: {adev['target_sample_counts']}\n")
    readme = root / "README.md"
    if readme.exists():
        prefix = readme.read_text(encoding="utf-8").split("\n## Latest results\n")[0]
        table = "| tau (s) | SIM1 | SIM2 | SIM3 | SIM4 | Ensemble | n |\n|---:|---:|---:|---:|---:|---:|---:|\n"
        for tau in adev["target_taus_s"]:
            table += f"| {tau} | " + " | ".join(f"{lookup[(name, tau)]['adev']:.6e}" for name in adev["series"])
            table += f" | {lookup[('Ensemble', tau)]['sample_count']} |\n"
        write_text(readme, prefix + f"\n## Latest results\n\nProfile: {clock_profile}. Common samples: {len(rows)}.\n\n" + table)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, help="Path to the compiled GstarTimescale executable")
    parser.add_argument("--output", type=Path, help="New or empty run directory (default depends on clock profile)")
    parser.add_argument("--clock-profile", choices=CLOCK_PROFILES, default=None, help="Default: basic; csac-mro selects two CSAC and two mRO clocks")
    parser.add_argument("--architecture", choices=ARCHITECTURES, default=None, help="Default: centralized; report-only reads the saved manifest")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--days", type=float, default=None, help="Simulation days (default: 10); report-only uses the saved duration if omitted")
    parser.add_argument("--timeout", type=float, default=1800, help="Engine timeout in seconds (default: 1800)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true", help="Generate inputs without running the engine")
    mode.add_argument("--report-only", action="store_true", help="Refresh phase/ADEV reports for an existing demo; preserve inputs and engine results")
    args = parser.parse_args(argv)
    if not args.prepare_only and not args.report_only and args.exe is None:
        parser.error("--exe is required unless --prepare-only or --report-only is used")
    executable = args.exe.resolve() if args.exe else None
    default_output = "Runs/heterogeneous_2csac2mro_10days" if args.clock_profile == "csac-mro" else "Runs/quickstart_10days"
    root = (args.output or Path(default_output)).resolve()
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("--timeout must be positive and finite")
        requested_duration = duration_from_days(args.days) if args.days is not None else None
        if not args.prepare_only:
            check_analysis_dependencies()
        if args.report_only:
            manifest = json.loads((root / "config/manifest.json").read_text(encoding="utf-8"))
            if manifest.get("satellites") != list(SATELLITES) or manifest.get("interval_s") != INTERVAL or manifest.get("start_gpst") != START.isoformat():
                raise ValueError("--report-only requires a matching quick-start demo manifest")
            saved_duration = validate_duration(manifest.get("duration_s"))
            if requested_duration is not None and requested_duration != saved_duration:
                raise ValueError("--days differs from saved duration; create a new run to change the simulation length")
            if args.clock_profile and args.clock_profile != manifest.get("clock_profile", "basic"):
                raise ValueError("--clock-profile differs from saved profile; create a new run to change the clocks")
            architecture = manifest.get("architecture")
            if architecture not in ARCHITECTURES or (args.architecture and args.architecture != architecture):
                raise ValueError("Requested architecture does not match the saved demo manifest")
            check_engine_logs(root)
            write_report(root, architecture)
            print(f"PASS: Refreshed phase and five-series ADEV report: {root / 'report.html'}")
            return 0
        if not args.prepare_only and not executable.is_file():
            raise ValueError(f"Executable not found: {executable}. Install the maintainer runtime with lab.py or use --prepare-only.")
        architecture = args.architecture or "centralized"
        duration_s = requested_duration if requested_duration is not None else DURATION
        prepare_case(root, architecture, args.seed, duration_s, args.clock_profile or "basic")
        print(f"Prepared 4 clocks, {duration_s // INTERVAL} epochs per clock, {math.ceil(duration_s / 86400) * 6} bidirectional PFD files: {root}", flush=True)
        if args.prepare_only:
            print("Inputs ready. Run the engine from this directory with argument config/file_table.")
            return 0
        with (root / "logs/console.log").open("wb") as log:
            process = subprocess.run([str(executable), "config/file_table"], cwd=root,
                                     stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
        if process.returncode != 0:
            raise ValueError(f"Engine exited with code {process.returncode}; inspect {root / 'logs/console.log'}")
        check_engine_logs(root)
        summary = write_report(root, architecture, engine_ran=True)
        print(f"PASS: {len(summary['outputs'])} IEM file(s) validated.")
        print(f"Open in a browser: {root / 'report.html'}")
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
