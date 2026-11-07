"""Verifier for the renal dose-check task.

Pass criteria, per patient in tests/ground_truth.json:
  * exactly one output line,
  * crcl_ml_min within 1% (relative) of the reference,
  * flagged_order_ids equal to the reference as a set.

OUTPUT_PATH and GROUND_TRUTH_PATH may be overridden through the environment
(used by authoring/evidence to grade simulated agents outside the container).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

OUTPUT_PATH = Path(os.environ.get("OUTPUT_PATH", "/app/output/dose_check.jsonl"))
GROUND_TRUTH_PATH = Path(os.environ.get("GROUND_TRUTH_PATH", Path(__file__).with_name("ground_truth.json")))

GT = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
EXPECTED = GT["patients"]
REL_TOL = GT["crcl_rel_tolerance"]
PATIENT_IDS = sorted(EXPECTED)


def _load_output() -> list[dict]:
    assert OUTPUT_PATH.is_file(), f"missing output file {OUTPUT_PATH}"
    rows = []
    for n, line in enumerate(OUTPUT_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            pytest.fail(f"line {n} is not valid JSON: {e}")
        assert isinstance(obj, dict), f"line {n} is not a JSON object"
        rows.append(obj)
    return rows


@pytest.fixture(scope="module")
def by_patient() -> dict[str, dict]:
    rows = _load_output()
    out: dict[str, dict] = {}
    for r in rows:
        pid = r.get("patient_id")
        assert isinstance(pid, str), f"row without string patient_id: {r}"
        assert pid not in out, f"duplicate line for {pid}"
        out[pid] = r
    return out


def test_exactly_the_expected_patients(by_patient):
    assert sorted(by_patient) == PATIENT_IDS


def test_row_schema(by_patient):
    for pid, r in by_patient.items():
        c = r.get("crcl_ml_min")
        assert isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c), \
            f"{pid}: crcl_ml_min must be a finite number, got {c!r}"
        assert round(c, 1) == c, f"{pid}: crcl_ml_min must be rounded to 0.1, got {c!r}"
        f = r.get("flagged_order_ids")
        assert isinstance(f, list) and all(isinstance(x, str) for x in f), \
            f"{pid}: flagged_order_ids must be a list of strings"
        assert len(f) == len(set(f)), f"{pid}: duplicate order ids in {f}"


@pytest.mark.parametrize("pid", PATIENT_IDS)
def test_clearance_within_one_percent(by_patient, pid):
    assert pid in by_patient, f"no output for {pid}"
    got, want = by_patient[pid].get("crcl_ml_min"), EXPECTED[pid]["crcl_ml_min"]
    assert isinstance(got, (int, float)) and not isinstance(got, bool)
    assert abs(got - want) <= REL_TOL * abs(want), f"{pid}: CrCl {got} vs expected {want} (±{REL_TOL:.0%})"


@pytest.mark.parametrize("pid", PATIENT_IDS)
def test_flagged_orders_exact(by_patient, pid):
    assert pid in by_patient, f"no output for {pid}"
    got = by_patient[pid].get("flagged_order_ids")
    assert isinstance(got, list)
    assert set(got) == set(EXPECTED[pid]["flagged_order_ids"]), \
        f"{pid}: flagged {sorted(got)} vs expected {EXPECTED[pid]['flagged_order_ids']}"
