#!/usr/bin/env python3
"""Simulated agents for the renal dose-check task.

One configurable agent implementation is run under many configurations:

  * "reference"      - solution/solve.py itself                     -> must PASS
  * "baseline"       - this simulator with no mistakes              -> must PASS
  * legit variants   - defensible numeric choices (88.42 factor,
                       2.2 lb/kg, rounding weight first, ...)       -> must PASS
  * single mistakes  - exactly one trap mistake each                -> must FAIL
  * malformed output - missing file, dropped/duplicate/extra patient,
                       unrounded or string CrCl                      -> must FAIL

Every output is graded by running the real tests/test_outputs.py with pytest.
The script also checks the data design itself:

  * each mistake changes the answer of at least one patient,
  * no patient is affected by mistakes from more than one trap family,
  * every reference CrCl sits >= 2% away from every band edge of the drugs
    that patient is on, so a 1%-accurate CrCl can never change a flag.

Writes authoring/evidence/results/simulation_results.json and .md and exits
non-zero if any expectation is violated.

    uv run --no-project --with pytest==8.3.3 python authoring/evidence/simulate_agents.py
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "environment"
TESTS = ROOT / "tests" / "test_outputs.py"
GT_PATH = ROOT / "tests" / "ground_truth.json"
RESULTS = Path(__file__).resolve().parent / "results"
EDGE_MARGIN = 0.02


@dataclass(frozen=True)
class Config:
    name: str
    family: str  # trap family for mistakes; "none" for passing configs
    expect_pass: bool
    description: str
    opts: dict = field(default_factory=dict)


CONFIGS = [
    Config("baseline", "none", True, "simulator with no mistakes"),
    # Legitimate variants a careful agent might choose; the grader must accept them.
    Config("legit_factor_88_42", "none", True, "µmol/L→mg/dL factor 88.42 instead of 88.4",
           {"umol_factor": 88.42}),
    Config("legit_lb_2_2", "none", True, "lb→kg as ÷2.2", {"lb_factor": 1 / 2.2}),
    Config("legit_lb_2_2046", "none", True, "lb→kg as ÷2.2046", {"lb_factor": 1 / 2.2046}),
    Config("legit_round_inputs", "none", True, "round kg to 0.1 and SCr to 0.01 mg/dL before CG",
           {"round_inputs": True}),
    Config("legit_band_on_rounded", "none", True, "choose band from CrCl rounded to 0.1",
           {"band_on_rounded": True}),
    Config("legit_unsorted_ids", "none", True, "flagged ids emitted in file order, not sorted",
           {"unsorted_ids": True}),
    # Single trap mistakes. Each must fail.
    Config("cr_umol_as_mgdl", "creatinine_unit", False, "ignores creatinine_unit; every value read as mg/dL",
           {"cr_unit": "ignore"}),
    Config("cr_unit_by_magnitude", "creatinine_unit", False,
           "blanket rule: creatinine < 20 is mg/dL, otherwise µmol/L (ignores unit column)",
           {"cr_unit": "magnitude"}),
    Config("weight_lb_as_kg", "weight_unit", False, "ignores weight_unit; every value read as kg",
           {"wt_unit": "ignore"}),
    Config("weight_unit_by_magnitude", "weight_unit", False,
           "blanket rule: weight > 140 must be lb (ignores unit column)", {"wt_unit": "magnitude"}),
    Config("count_discontinued", "order_status", False, "checks discontinued orders as if active",
           {"include_discontinued": True}),
    Config("freq_qNh_as_count", "frequency", False, "reads qNh as N doses per day (q8h -> 8)",
           {"freq_bug": "qNh_as_N"}),
    Config("freq_bd_as_once", "frequency", False, "reads BD as once daily", {"freq_bug": "BD_as_1"}),
    Config("freq_tds_as_twice", "frequency", False, "reads TDS as twice daily", {"freq_bug": "TDS_as_2"}),
    Config("lab_last_row_wins", "latest_lab", False, "uses the last creatinine row in file order, not the latest time",
           {"lab_pick": "last_row"}),
    Config("flag_at_limit", "limit_boundary", False, "flags daily dose >= limit instead of > limit",
           {"flag_ge": True}),
]

# Structurally broken outputs built from the correct baseline answer. Each must FAIL.
MALFORMED = {
    "no_output_file": "output file never written",
    "empty_output": "output file exists but is empty",
    "drop_one_patient": "one patient's line missing",
    "duplicate_patient": "one patient written twice",
    "extra_patient": "a patient id that is not in the chart",
    "crcl_unrounded": "CrCl written with full float precision",
    "crcl_as_string": "CrCl written as a JSON string",
}


def malformed_text(kind: str, rows: list[dict]) -> str | None:
    rows = [dict(r) for r in rows]
    if kind == "no_output_file":
        return None
    if kind == "empty_output":
        rows = []
    elif kind == "drop_one_patient":
        rows = rows[1:]
    elif kind == "duplicate_patient":
        rows = rows + rows[:1]
    elif kind == "extra_patient":
        rows = rows + [{"patient_id": "PT999", "crcl_ml_min": 80.0, "flagged_order_ids": []}]
    elif kind == "crcl_unrounded":
        rows[0]["crcl_ml_min"] += 0.0123
    elif kind == "crcl_as_string":
        rows[0]["crcl_ml_min"] = str(rows[0]["crcl_ml_min"])
    return "".join(json.dumps(r) + "\n" for r in rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def per_day(freq: str, bug: str | None) -> int:
    f = freq.strip().upper()
    table = {"OD": 1, "DAILY": 1, "BD": 2, "TDS": 3, "QDS": 4}
    if bug == "BD_as_1":
        table["BD"] = 1
    if bug == "TDS_as_2":
        table["TDS"] = 2
    if f in table:
        return table[f]
    m = re.fullmatch(r"Q(\d+)H", f)
    if not m:
        raise ValueError(freq)
    n = int(m.group(1))
    return n if bug == "qNh_as_N" else 24 // n


def simulate(opts: dict, data_dir: Path) -> list[dict]:
    rules = json.loads((data_dir / "rules.json").read_text(encoding="utf-8"))["drugs"]
    umol = opts.get("umol_factor", 88.4)
    lbf = opts.get("lb_factor", 0.45359237)

    scr: dict[str, tuple] = {}
    for i, r in enumerate(read_csv(data_dir / "labs.csv")):
        v, unit = float(r["creatinine"]), r["creatinine_unit"]
        mode = opts.get("cr_unit", "column")
        if mode == "ignore":
            unit = "mg/dL"
        elif mode == "magnitude":
            unit = "mg/dL" if v < 20 else "µmol/L"
        mg = v if unit == "mg/dL" else v / umol
        key = i if opts.get("lab_pick") == "last_row" else datetime.fromisoformat(r["collected_at"])
        if r["patient_id"] not in scr or key > scr[r["patient_id"]][0]:
            scr[r["patient_id"]] = (key, mg)

    meds: dict[str, list[dict]] = {}
    for r in read_csv(data_dir / "meds.csv"):
        meds.setdefault(r["patient_id"], []).append(r)

    out = []
    for p in read_csv(data_dir / "patients.csv"):
        pid, w, unit = p["patient_id"], float(p["weight"]), p["weight_unit"]
        mode = opts.get("wt_unit", "column")
        if mode == "ignore":
            unit = "kg"
        elif mode == "magnitude":
            unit = "lb" if w > 140 else "kg"
        kg = w * lbf if unit == "lb" else w
        s = scr[pid][1]
        if opts.get("round_inputs"):
            kg, s = round(kg, 1), round(s, 2)
        crcl = (140 - int(p["age_years"])) * kg / (72 * s) * (0.85 if p["sex"] == "F" else 1.0)
        band_crcl = round(crcl, 1) if opts.get("band_on_rounded") else crcl
        flagged = []
        for o in meds.get(pid, []):
            if o["status"] != "active" and not opts.get("include_discontinued"):
                continue
            daily = float(o["dose_mg"]) * per_day(o["frequency"], opts.get("freq_bug"))
            limit = next(b["max_daily_dose_mg"] for b in rules[o["drug"]]
                         if (b["crcl_min"] is None or band_crcl >= b["crcl_min"])
                         and (b["crcl_max"] is None or band_crcl < b["crcl_max"]))
            if daily >= limit if opts.get("flag_ge") else daily > limit:
                flagged.append(o["order_id"])
        out.append({"patient_id": pid, "crcl_ml_min": round(crcl, 1),
                    "flagged_order_ids": flagged if opts.get("unsorted_ids") else sorted(flagged)})
    return out


def grade(output: Path) -> tuple[bool, int, str]:
    env = {**os.environ, "OUTPUT_PATH": str(output), "GROUND_TRUTH_PATH": str(GT_PATH)}
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(TESTS)],
                          env=env, capture_output=True, text=True, cwd=ROOT)
    tail = proc.stdout.strip().splitlines()[-1]
    bad = sum(int(n) for n in re.findall(r"(\d+) (?:failed|errors?)\b", tail))
    return proc.returncode == 0, bad, tail


def diff_patients(rows: list[dict], gt: dict) -> dict[str, dict]:
    changed = {}
    for r in rows:
        want = gt[r["patient_id"]]
        crcl_bad = abs(r["crcl_ml_min"] - want["crcl_ml_min"]) > 0.01 * want["crcl_ml_min"]
        flags_bad = set(r["flagged_order_ids"]) != set(want["flagged_order_ids"])
        if crcl_bad or flags_bad:
            changed[r["patient_id"]] = {
                "crcl": [want["crcl_ml_min"], r["crcl_ml_min"]] if crcl_bad else None,
                "flags": [want["flagged_order_ids"], sorted(r["flagged_order_ids"])] if flags_bad else None,
            }
    return changed


def edge_margins(gt: dict) -> list[dict]:
    rules = json.loads((ENV / "rules.json").read_text(encoding="utf-8"))["drugs"]
    drugs: dict[str, set] = {}
    for r in read_csv(ENV / "meds.csv"):
        drugs.setdefault(r["patient_id"], set()).add(r["drug"])
    rows = []
    for pid, want in sorted(gt.items()):
        c = want["crcl_ml_min"]
        edges = {e for d in drugs.get(pid, ()) for b in rules[d] for e in (b["crcl_min"], b["crcl_max"]) if e}
        nearest = min(edges, key=lambda e: abs(c - e))
        rows.append({"patient_id": pid, "crcl": c, "nearest_edge": nearest,
                     "margin": round(abs(c - nearest) / nearest, 4)})
    return rows


def main() -> int:
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))["patients"]
    design = {d["patient_id"]: d for d in json.loads((ROOT / "authoring" / "patient_design.json").read_text())}
    problems: list[str] = []
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        ref_out = Path(tmp) / "reference.jsonl"
        subprocess.run([sys.executable, str(ROOT / "solution" / "solve.py"), str(ENV), str(ref_out)], check=True)
        ok, nfail, summary = grade(ref_out)
        results.append({"name": "reference", "family": "none", "description": "solution/solve.py",
                        "expect_pass": True, "passed": ok, "failed_tests": nfail, "pytest": summary,
                        "changed_patients": {}})
        for cfg in CONFIGS:
            rows = simulate(cfg.opts, ENV)
            out = Path(tmp) / f"{cfg.name}.jsonl"
            out.write_text("".join(json.dumps(r) + "\n" for r in rows))
            ok, nfail, summary = grade(out)
            results.append({"name": cfg.name, "family": cfg.family, "description": cfg.description,
                            "expect_pass": cfg.expect_pass, "passed": ok, "failed_tests": nfail,
                            "pytest": summary, "changed_patients": diff_patients(rows, gt)})
        baseline_rows = simulate({}, ENV)
        for kind, desc in MALFORMED.items():
            out = Path(tmp) / f"{kind}.jsonl"
            text = malformed_text(kind, baseline_rows)
            if text is not None:
                out.write_text(text)
            ok, nfail, summary = grade(out)
            results.append({"name": kind, "family": "malformed", "description": desc, "expect_pass": False,
                            "passed": ok, "failed_tests": nfail, "pytest": summary, "changed_patients": None})

    for r in results:
        if r["passed"] != r["expect_pass"]:
            problems.append(f"{r['name']}: expected {'PASS' if r['expect_pass'] else 'FAIL'}, got "
                            f"{'PASS' if r['passed'] else 'FAIL'}")
        if not r["expect_pass"] and r["family"] != "malformed" and not r["changed_patients"]:
            problems.append(f"{r['name']}: mistake changed no patient's answer")

    # Family isolation: a patient may be affected by mistakes of one family only,
    # and only patients designed for that family may be affected.
    families_by_patient: dict[str, set] = {}
    for r in results:
        if r["expect_pass"] or r["family"] == "malformed":
            continue
        for pid in r["changed_patients"]:
            families_by_patient.setdefault(pid, set()).add(r["family"])
            if design[pid]["family"] != r["family"]:
                problems.append(f"{r['name']} changed {pid}, designed for family {design[pid]['family']}")
    for pid, fams in families_by_patient.items():
        if len(fams) > 1:
            problems.append(f"{pid} is affected by more than one trap family: {sorted(fams)}")

    margins = edge_margins(gt)
    for m in margins:
        if m["margin"] < EDGE_MARGIN:
            problems.append(f"{m['patient_id']}: CrCl {m['crcl']} within {EDGE_MARGIN:.0%} of band edge "
                            f"{m['nearest_edge']}")

    report = {"results": results, "families_by_patient": {k: sorted(v) for k, v in sorted(families_by_patient.items())},
              "design": design, "band_edge_margins": margins, "problems": problems}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "simulation_results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (RESULTS / "simulation_results.md").write_text(render_md(report))
    print((RESULTS / "simulation_results.md").read_text())
    return 1 if problems else 0


def render_md(rep: dict) -> str:
    lines = ["# Simulated agents", "",
             "Generated by `authoring/evidence/simulate_agents.py`; every row was graded by running "
             "`tests/test_outputs.py` with pytest.", "",
             "| agent | trap family | expected | result | failed/errored tests | patients changed |",
             "|---|---|---|---|---|---|"]
    for r in rep["results"]:
        verdict = "PASS" if r["passed"] else "FAIL"
        ok = "✅" if r["passed"] == r["expect_pass"] else "❌"
        lines.append(f"| `{r['name']}` | {r['family']} | {'PASS' if r['expect_pass'] else 'FAIL'} | "
                     f"{ok} {verdict} | {r['failed_tests']} | {', '.join(r['changed_patients'] or []) or '—'} |")
    lines += ["", "## What each mistake changed", ""]
    for r in rep["results"]:
        if r["expect_pass"] or r["family"] == "malformed":
            continue
        lines.append(f"**`{r['name']}`** — {r['description']}")
        for pid, d in r["changed_patients"].items():
            parts = []
            if d["crcl"]:
                parts.append(f"CrCl {d['crcl'][0]} → {d['crcl'][1]}")
            if d["flags"]:
                parts.append(f"flags {d['flags'][0]} → {d['flags'][1]}")
            lines.append(f"- {pid} ({rep['design'][pid]['note']}): " + "; ".join(parts))
        lines.append("")
    lines += ["## Trap isolation", "",
              "Patients affected by any mistake, and the trap families that affected them "
              "(must be exactly one each):", ""]
    lines += [f"- {pid}: {', '.join(f)}" for pid, f in rep["families_by_patient"].items()]
    lines += ["", f"## Band-edge margins (reference CrCl vs nearest band edge of that patient's drugs; "
                  f"required ≥ {EDGE_MARGIN:.0%})", "", "| patient | CrCl | nearest edge | margin |", "|---|---|---|---|"]
    lines += [f"| {m['patient_id']} | {m['crcl']} | {m['nearest_edge']} | {m['margin']:.1%} |"
              for m in rep["band_edge_margins"]]
    lines += ["", "## Problems", ""] + ([f"- {p}" for p in rep["problems"]] or ["None."])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
