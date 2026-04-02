from __future__ import annotations

from tsel.balance_diagnostics import audit_unification_integrity


def test_unification_audit_reports_shared_contract() -> None:
    audit = audit_unification_integrity()

    assert audit["is_unified"] is True
    assert audit["canonical_top_level_fields"] == [
        "timestamp",
        "modality",
        "source",
        "signal_type",
        "value",
        "unit",
        "contextual_metadata",
    ]
    assert audit["fragmentation_risks"]
    assert all(summary["top_level_keys_ok"] for summary in audit["route_summaries"].values())
    assert all(summary["temporal_contract_ok"] for summary in audit["route_summaries"].values())
    assert all(summary["bundle_contract_ok"] for summary in audit["route_summaries"].values())
    assert all(summary["assertion_basis_ok"] for summary in audit["route_summaries"].values())
    assert all(summary["unresolved_ok"] for summary in audit["route_summaries"].values())
    assert all(summary["modality_primary_sense_consistent"] for summary in audit["route_summaries"].values())
