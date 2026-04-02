from __future__ import annotations

from pathlib import Path
import shutil

from tsel.balance_diagnostics import (
    _evaluate_collection_quality_suite,
    _evaluate_false_positive_restraint_suite,
    _evaluate_supported_structure_suite,
    _work_dir,
    run_balance_diagnostics,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "_balance_test_reports"


def test_supported_structure_recovery_cases_all_pass() -> None:
    cases = _evaluate_supported_structure_suite(_work_dir())

    assert cases
    assert all(case.passed for case in cases)
    assert all(case.failure_classification is None for case in cases)


def test_false_positive_restraint_reference_cases_all_pass() -> None:
    cases = _evaluate_false_positive_restraint_suite(_work_dir())

    assert cases
    assert all(case.passed for case in cases)


def test_collection_quality_cases_expose_upstream_limitations_without_guessing() -> None:
    cases = _evaluate_collection_quality_suite(_work_dir())
    issue_names = {issue for case in cases for issue in case.upstream_issues}

    assert cases
    assert all(case.passed for case in cases)
    assert {
        "missing_stimulus_markers",
        "missing_acquisition_metadata",
        "weak_provenance",
        "inadequate_temporal_resolution",
        "insufficient_pre_stimulus_window",
        "insufficient_post_stimulus_window",
        "broken_timestamp_continuity",
        "incomplete_packet_annotation",
        "ambiguous_route_evidence",
        "missing_contextual_labels",
    } <= issue_names


def test_run_balance_diagnostics_writes_reports_and_metrics() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    base_dir = OUTPUT / "work"
    report_dir = OUTPUT / "reports"
    payload = run_balance_diagnostics(base_dir=base_dir, report_dir=report_dir)

    assert payload["unification_integrity"]["is_unified"] is True
    assert payload["balance_metrics"]["false_positive_restraint_success"] == {"passed": 7, "total": 7}
    assert payload["balance_metrics"]["supported_structure_recovery_success"] == {"passed": 8, "total": 8}
    assert payload["balance_metrics"]["unresolved_outputs_due_to_rule_strictness"]["count"] == 0
    assert Path(payload["outputs"]["json"]).exists()
    assert Path(payload["outputs"]["unification_report"]).exists()
    assert Path(payload["outputs"]["recovery_report"]).exists()
    assert Path(payload["outputs"]["collection_report"]).exists()
