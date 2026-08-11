#!/usr/bin/env python3
"""Deterministic synthetic guard suite for robust DSP fitting."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import tunelib


def make_guard(name, actual, operator, expected):
    comparisons = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
    }
    if operator not in comparisons:
        raise ValueError("unsupported guard operator: %s" % operator)
    return {
        "name": name,
        "passed": bool(comparisons[operator](actual, expected)),
        "actual": actual,
        "operator": operator,
        "expected": expected,
    }


def _frequencies():
    return np.geomspace(100.0, 10000.0, 401)


def _fit_metrics(freqs, deviations, fit_band, bands, mask=None, conf=None):
    """Comparable position outcomes for legacy and robust fitters."""
    deviations = np.atleast_2d(np.asarray(deviations, dtype=float))
    selected = (freqs >= fit_band[0]) & (freqs <= fit_band[1])
    if mask is not None:
        mask_array = np.asarray(mask, dtype=bool)
        if mask_array.ndim == 1:
            selected = selected & mask_array
    weights = np.ones(len(freqs), dtype=float)
    if conf is not None:
        conf_array = np.asarray(conf, dtype=float)
        if conf_array.ndim == 1:
            weights *= np.clip(conf_array, 0.0, 1.0)
    weights = weights[selected]
    cascade = sum((tunelib.peaking_db(freqs, *band) for band in bands),
                  np.zeros_like(freqs))

    def score(trace):
        values = np.asarray(trace)[selected]
        denom = max(float(np.sum(weights)), 1e-12)
        return float(np.sqrt(np.sum(weights * values ** 2) / denom))

    before = [score(trace) for trace in deviations]
    after = [score(trace + cascade) for trace in deviations]
    improvements = np.asarray(before) - np.asarray(after)
    return {
        "median_improvement_db": round(float(np.median(improvements)), 3),
        "worst_position_change_db": round(float(np.min(improvements)), 3),
        "bands_used": len(bands),
        "headroom_cost_db": round(float(sum(max(0.0, band[2]) for band in bands)), 3),
        "refused": not bool(bands),
    }


def _compare_fitters(freqs, deviations, fit_band, n_bands_max, mask=None,
                     conf=None, robust_fitter=tunelib.fit_peq_robust,
                     improve_pct=3.0, max_worst_loss_db=0.25):
    deviations = np.atleast_2d(np.asarray(deviations, dtype=float))
    mean_trace = np.mean(deviations, axis=0)
    legacy_bands, _legacy_report = tunelib.fit_peq(
        freqs, mean_trace, fit_band, n_bands_max=n_bands_max,
        mask=mask, conf=conf, improve_pct=improve_pct)
    robust_bands, robust_report = robust_fitter(
        freqs, deviations, fit_band, n_bands_max=n_bands_max,
        mask=mask, conf=conf, improve_pct=improve_pct,
        max_worst_loss_db=max_worst_loss_db)
    comparison = {
        "legacy": _fit_metrics(
            freqs, deviations, fit_band, legacy_bands, mask=mask, conf=conf),
        "robust": _fit_metrics(
            freqs, deviations, fit_band, robust_bands, mask=mask, conf=conf),
    }
    return legacy_bands, robust_bands, robust_report, comparison


def stable_peaks_case(fitter=tunelib.fit_peq_robust):
    freqs = _frequencies()
    peak = tunelib.peaking_db(freqs, 800.0, 0.8, 4.0)
    deviations = np.vstack([peak, 0.9 * peak, 1.1 * peak])
    _legacy, bands, report, comparison = _compare_fitters(
        freqs, deviations, (200.0, 6000.0), n_bands_max=2,
        robust_fitter=fitter, improve_pct=3.0)
    minimum_improvement = min(
        before - after for before, after in zip(
            report["position_scores_before"], report["position_scores_after"]))
    return {
        "id": "stable_peaks",
        "metrics": {
            "bands": bands,
            "bands_used": report["bands_used"],
            "minimum_position_improvement_db": round(minimum_improvement, 3),
            "legacy_vs_robust": comparison,
        },
        "guards": [
            make_guard("shared peak receives a filter", report["bands_used"], ">=", 1),
            make_guard("every position improves", round(minimum_improvement, 3), ">", 0.0),
            make_guard("shared correction is a cut",
                       max((band[2] for band in bands), default=0.0), "<", 0.0),
        ],
    }


def wandering_nulls_case():
    freqs = _frequencies()
    traces = [tunelib.peaking_db(freqs, center, 5.0, -10.0)
              for center in (700.0, 1800.0, 4200.0)]
    consistency = tunelib.spatial_consistency(
        freqs, traces, alignment_band=(200.0, 6000.0))
    aligned = np.vstack(traces) - np.asarray(
        consistency["level_offsets_db"])[:, None]
    _legacy, bands, report, comparison = _compare_fitters(
        freqs, aligned, (200.0, 6000.0), mask=consistency["mask"],
        conf=consistency["conf"], n_bands_max=2, improve_pct=3.0)
    rejected_fraction = round(float(np.mean(~consistency["mask"])), 3)
    boosts = sum(1 for _f, _q, gain in bands if gain > 0.0)
    return {
        "id": "wandering_nulls",
        "metrics": {
            "bands": bands,
            "bands_used": report["bands_used"],
            "boosts": boosts,
            "spatially_rejected_fraction": rejected_fraction,
            "legacy_vs_robust": comparison,
        },
        "guards": [
            make_guard("wandering nulls lose authority", rejected_fraction, ">=", 0.1),
            make_guard("wandering nulls receive no boost", boosts, "==", 0),
            make_guard("no filter budget spent on wandering nulls",
                       report["bands_used"], "==", 0),
        ],
    }


def level_offsets_case():
    freqs = _frequencies()
    shape = (tunelib.peaking_db(freqs, 300.0, 1.2, -4.0)
             + tunelib.peaking_db(freqs, 2500.0, 1.8, 3.0))
    expected = np.asarray([-2.0, 0.0, 2.0])
    consistency = tunelib.spatial_consistency(
        freqs, [shape - 2.0, shape, shape + 2.0],
        alignment_band=(200.0, 6000.0))
    actual = np.asarray(consistency["level_offsets_db"])
    max_error = round(float(np.max(np.abs(actual - expected))), 3)
    trusted_fraction = round(float(np.mean(consistency["mask"])), 3)
    return {
        "id": "level_offsets",
        "metrics": {
            "level_offsets_db": [round(float(value), 3) for value in actual],
            "maximum_offset_error_db": max_error,
            "trusted_fraction": trusted_fraction,
        },
        "guards": [
            make_guard("level offsets are recovered", max_error, "<=", 0.05),
            make_guard("identical shapes remain authoritative", trusted_fraction, ">=", 0.99),
        ],
    }


def confidence_blocked_lr_matching_case():
    freqs = _frequencies()
    target = np.zeros_like(freqs)
    partner = tunelib.peaking_db(freqs, 3000.0, 8.0, 4.0)
    confidence = np.ones_like(freqs)
    confidence[(freqs >= 2000.0) & (freqs <= 4500.0)] = 0.0
    bands, report = tunelib.fit_peq(
        freqs, target, (200.0, 8000.0), n_bands_max=3,
        partner_target_db=partner, partner_weight=3.0,
        partner_band=(700.0, 5000.0), conf=confidence)
    return {
        "id": "confidence_blocked_lr_matching",
        "metrics": {
            "bands": bands,
            "bands_used": report["bands_used"],
            "partner_mismatch_after": report["partner_mismatch_after"],
        },
        "guards": [
            make_guard("zero-confidence L/R mismatch spends no filter",
                       report["bands_used"], "==", 0),
        ],
    }


def worst_position_harm_case():
    freqs = _frequencies()
    peak = tunelib.peaking_db(freqs, 1000.0, 1.0, 4.0)
    dip = tunelib.peaking_db(freqs, 1000.0, 1.0, -1.0)
    deviations = np.vstack([peak, peak, dip])
    permissive, permissive_report = tunelib.fit_peq_robust(
        freqs, deviations, (200.0, 6000.0), n_bands_max=1,
        improve_pct=3.0, max_worst_loss_db=10.0)
    _legacy, guarded, guarded_report, comparison = _compare_fitters(
        freqs, deviations, (200.0, 6000.0), n_bands_max=1,
        improve_pct=3.0, max_worst_loss_db=0.25)
    candidate_loss = permissive_report["worst_position_loss_db"]
    return {
        "id": "worst_position_harm",
        "metrics": {
            "permissive_bands": permissive,
            "permissive_worst_position_loss_db": candidate_loss,
            "guarded_bands": guarded,
            "rejected_candidate_worst_loss_db":
                guarded_report["rejected_candidate_worst_loss_db"],
            "legacy_vs_robust": comparison,
        },
        "guards": [
            make_guard("fixture exposes a harmful mean-improving candidate",
                       len(permissive), ">=", 1),
            make_guard("candidate exceeds declared worst-position limit",
                       candidate_loss, ">", 0.25),
            make_guard("worst-position guard rejects candidate", len(guarded), "==", 0),
            make_guard("worst-position rejection is reported",
                       guarded_report["rejected_worst_position"], "==", True),
        ],
    }


CASE_RUNNERS = [
    stable_peaks_case,
    wandering_nulls_case,
    level_offsets_case,
    confidence_blocked_lr_matching_case,
    worst_position_harm_case,
]


def run_benchmarks(case_runners=None):
    cases = []
    failures = []
    for runner in case_runners or CASE_RUNNERS:
        case = runner()
        case["passed"] = all(guard["passed"] for guard in case["guards"])
        cases.append(case)
        for guard in case["guards"]:
            if not guard["passed"]:
                failures.append({
                    "case": case["id"],
                    "guard": guard["name"],
                    "actual": guard["actual"],
                    "operator": guard["operator"],
                    "expected": guard["expected"],
                })
    passed = sum(1 for case in cases if case["passed"])
    return {
        "benchmark": "helix-rew-tuner-robust-fitting",
        "deterministic": True,
        "passed": not failures,
        "summary": {"total": len(cases), "passed": passed,
                    "failed": len(cases) - passed},
        "cases": cases,
        "failures": failures,
    }


def main(argv=None, case_runners=None):
    parser = argparse.ArgumentParser(
        description="Run deterministic synthetic guards for robust DSP fitting.")
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args(argv)
    report = run_benchmarks(case_runners=case_runners)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for case in report["cases"]:
            print("[%s] %s" % ("pass" if case["passed"] else "FAIL", case["id"]))
            for guard in case["guards"]:
                print("  [%s] %s: %r %s %r" % (
                    "pass" if guard["passed"] else "FAIL", guard["name"],
                    guard["actual"], guard["operator"], guard["expected"]))
        print("%d/%d cases passed" % (
            report["summary"]["passed"], report["summary"]["total"]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
