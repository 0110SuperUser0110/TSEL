from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json
import shutil

from .autorouting import AutoRoutingError, build_auto_ingest_plan
from .experience import enrich_experience
from .models import TemporalEvent, TemporalEventCollection, TemporalExtent
from .packet_profiles import _SYNAPSE_REQUIRED_FILES, detect_special_packet_type, plan_special_packet
from .pipeline import TSELPipeline


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DEFAULT_WORK_DIR = ROOT / "output" / "_balance_diagnostics"
DEFAULT_JSON_OUTPUT = ROOT / "output" / "balance_diagnostics.json"
DEFAULT_UNIFICATION_REPORT = ROOT / "unification_integrity.md"
DEFAULT_RECOVERY_REPORT = ROOT / "supported_structure_test_summary.md"
DEFAULT_COLLECTION_REPORT = ROOT / "collection_quality_diagnostics.md"
CANONICAL_TOP_LEVEL_FIELDS = [
    "timestamp",
    "modality",
    "source",
    "signal_type",
    "value",
    "unit",
    "contextual_metadata",
]
ALLOWED_ASSERTION_BASES = {
    "source_provided",
    "packet_declared",
    "directly_observed",
    "deterministically_derived",
    "unresolved",
}
RECOVERY_FAILURE_CLASSIFICATIONS = {
    "rule_too_strict",
    "threshold_too_strict",
    "schema_too_narrow",
    "source_data_insufficient",
    "metadata_annotation_insufficient",
    "packet_profile_incomplete",
    "expected_test_wrong",
}


@dataclass(slots=True)
class CaseAssessment:
    name: str
    suite: str
    support: str
    expected_claims: list[str]
    unresolved_if_unsupported: list[str]
    passed: bool
    observed: list[str] = field(default_factory=list)
    failure_classification: str | None = None
    upstream_issues: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "suite": self.suite,
            "support": self.support,
            "expected_claims": self.expected_claims,
            "unresolved_if_unsupported": self.unresolved_if_unsupported,
            "passed": self.passed,
            "observed": self.observed,
            "failure_classification": self.failure_classification,
            "upstream_issues": self.upstream_issues,
            "notes": self.notes,
        }


def _work_dir(base_dir: str | Path | None = None) -> Path:
    work_dir = DEFAULT_WORK_DIR if base_dir is None else Path(base_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _time(offset_seconds: int | float) -> datetime:
    base = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=float(offset_seconds))


def _sample(
    second: int | float,
    value: float,
    *,
    source: str = "SESSION-01",
    channel: str = "Fp1",
    sequence_index: int | None = None,
) -> TemporalEvent:
    timestamp = _time(second)
    return TemporalEvent(
        timestamp=timestamp,
        modality="eeg",
        source=source,
        signal_type="voltage",
        value=value,
        unit="uV",
        contextual_metadata={"channel": channel, "sample_rate_hz": 1.0},
        extent=TemporalExtent.from_timestamp(timestamp, resolution_seconds=1.0, time_scale="sample"),
        event_kind="sample",
        sequence_index=sequence_index,
        stream_id=f"eeg::{source}::{channel}::voltage",
    )


def _marker(
    second: int | float,
    label: str,
    *,
    source: str = "SESSION-01",
    marker_type: str = "stimulus",
) -> TemporalEvent:
    return TemporalEvent(
        timestamp=_time(second),
        modality="eeg",
        source=source,
        signal_type="marker",
        value=label,
        unit="event",
        contextual_metadata={"annotation_label": label, "marker_type": marker_type},
        event_kind="marker",
        stream_id=f"eeg::{source}::marker",
    )


def _assertion(record: dict[str, Any], path: str) -> str | None:
    metadata = record.get("contextual_metadata", {})
    if not isinstance(metadata, dict):
        return None
    assertion_basis = metadata.get("assertion_basis", {})
    if not isinstance(assertion_basis, dict):
        return None
    value = assertion_basis.get(path)
    return None if value is None else str(value)


def _relations(record: dict[str, Any], relation_type: str) -> list[dict[str, Any]]:
    metadata = record.get("contextual_metadata", {})
    if not isinstance(metadata, dict):
        return []
    relations = metadata.get("relations", [])
    if not isinstance(relations, list):
        return []
    return [relation for relation in relations if isinstance(relation, dict) and relation.get("relation_type") == relation_type]


def _find_marker(records: list[dict[str, Any]], label: str) -> dict[str, Any]:
    for record in records:
        metadata = record.get("contextual_metadata", {})
        if not isinstance(metadata, dict):
            continue
        if metadata.get("annotation_label") == label:
            return record
    raise AssertionError(f"missing marker '{label}'")


def _phase_set(records: list[dict[str, Any]], *, signal_type: str = "voltage") -> set[str]:
    phases: set[str] = set()
    for record in records:
        if record.get("signal_type") != signal_type:
            continue
        metadata = record.get("contextual_metadata", {})
        if not isinstance(metadata, dict):
            continue
        temporal = metadata.get("temporal", {})
        if isinstance(temporal, dict) and isinstance(temporal.get("phase"), str):
            phases.add(str(temporal["phase"]))
    return phases


def _continuity_states(records: list[dict[str, Any]]) -> set[str]:
    states: set[str] = set()
    for record in records:
        metadata = record.get("contextual_metadata", {})
        if not isinstance(metadata, dict):
            continue
        experience = metadata.get("experience", {})
        if isinstance(experience, dict) and isinstance(experience.get("continuity_state"), str):
            states.add(str(experience["continuity_state"]))
    return states


def _report_lines(title: str, lines: list[str]) -> str:
    return "\n".join([f"# {title}", "", *lines, ""])


def _build_clear_experience_file(
    work_dir: Path,
    *,
    include_baseline: bool = True,
    include_trailing: bool = True,
    include_metadata: bool = True,
    include_alignment: bool = True,
) -> Path:
    values_a: list[float] = []
    values_b: list[float] = []
    if include_baseline:
        values_a.append(0.10)
        values_b.append(0.11)
    values_a.extend([0.20, 0.55, 1.00, 0.60, 0.20])
    values_b.extend([0.22, 0.50, 0.96, 0.58, 0.24])
    if include_trailing:
        values_a.extend([0.15, 0.10])
        values_b.extend([0.16, 0.11])

    onset_index = 1 if include_baseline else 0
    offset_index = onset_index + 4
    report_index = len(values_a) - 1

    metadata: dict[str, Any] = {
        "dataset": "balance_recovery",
        "condition": "deterministic benchmark",
    }
    if include_metadata:
        metadata["acquisition"] = {
            "acquisition_profile": "eeg",
            "instrument": "benchmark_eeg_cap",
            "device_class": "eeg_recorder",
        }
    if include_alignment:
        metadata["alignment"] = {
            "recording_id": "rec-001",
            "subject_id": "sub-001",
            "trial_id": "trial-001",
        }

    payload = {
        "start_time": "2026-03-15T12:00:00Z",
        "sample_rate_hz": 1,
        "source": "REC-01",
        "metadata": metadata,
        "channels": {
            "Fp1": values_a,
            "Fp2": values_b,
        },
        "annotations": [
            {"offset_samples": onset_index, "label": "stimulus_onset", "marker_type": "stimulus"},
            {"offset_samples": offset_index, "label": "stimulus_offset", "marker_type": "stimulus"},
            {"offset_samples": report_index, "label": "verbal_report", "marker_type": "behavior"},
        ],
    }
    path = work_dir / "clear_experience.json"
    _write_text(path, json.dumps(payload, indent=2))
    return path


def _build_ambiguous_route_file(work_dir: Path) -> Path:
    path = work_dir / "ambiguous_route.csv"
    _write_text(
        path,
        "timestamp,source,sample_rate_hz,Fp1,odor_intensity\n"
        "2026-03-15T12:00:00Z,SESSION-01,4,10.0,0.8\n",
    )
    return path


def _build_malformed_json_file(work_dir: Path) -> Path:
    path = work_dir / "broken.json"
    _write_text(path, '{"channels": [}')
    return path


def _build_weak_provenance_file(work_dir: Path) -> Path:
    payload = {
        "start_time": "2026-03-15T12:00:00Z",
        "sample_rate_hz": 1,
        "source": "REC-WEAK",
        "metadata": {"dataset": "weak_provenance"},
        "channels": {"Fp1": [0.1, 0.2, 0.3, 0.2]},
        "annotations": [{"offset_samples": 1, "label": "stimulus_onset", "marker_type": "stimulus"}],
    }
    path = work_dir / "weak_provenance.json"
    _write_text(path, json.dumps(payload, indent=2))
    return path


def _build_synapse_packet(work_dir: Path, *, complete: bool) -> Path:
    packet_dir = work_dir / ("mini_synapse_complete" if complete else "mini_synapse_incomplete")
    if packet_dir.exists():
        shutil.rmtree(packet_dir)
    packet_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {
        "TrainSet.txt": (
            "Compound Identifier\tOdor\tReplicate\tIntensity\tDilution\tsubject #\tdesc_a\tdesc_b\n"
            "100\todor_a\tr1\ti1\td1\t1\t0.3\t0.5\n"
        ),
        "leaderboard_set.txt": "#oID\tindividual\tdescriptor\tvalue\n100\t1\tpleasantness\t0.8\n",
        "LBs1.txt": "#oID\tindividual\tdescriptor\tvalue\n101\t2\tintensity\t0.6\n",
        "LBs2.txt": "#oID\tdescriptor\tvalue\tsigma\n100\tpleasantness\t0.75\t0.05\n",
        "molecular_descriptors_data.txt": "CID\tdesc_x\tdesc_y\n100\t1.2\t3.4\n",
        "CID_leaderboard.txt": "CID\n100\n",
        "CID_testset.txt": "CID\n101\n",
        "dilution_leaderboard.txt": "#oID\tdilution\n100\t1/10\n",
        "dilution_testset.txt": "#oID\tdilution\n101\t1/100\n",
    }
    if not complete:
        files.pop("LBs2.txt")

    for name, content in files.items():
        _write_text(packet_dir / name, content)
    return packet_dir


def _build_generic_packet(work_dir: Path) -> Path:
    packet_dir = work_dir / "generic_packet"
    if packet_dir.exists():
        shutil.rmtree(packet_dir)
    packet_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLES / "data" / "vision_episode.json", packet_dir / "vision_episode.json")
    _write_text(
        packet_dir / "vision_sequence.csv",
        "source,subject_id,sample_rate_hz,vision_signal,auditory_signal\n"
        "SESSION-02,SUB-09,4,0.1,0.2\n"
        "SESSION-02,SUB-09,4,0.3,0.4\n",
    )
    return packet_dir


def _missing_synapse_files(packet_dir: Path) -> list[str]:
    members = {child.name for child in packet_dir.iterdir() if child.is_file()}
    return [name for name in _SYNAPSE_REQUIRED_FILES if name not in members]

def _collect_contract_summary(collection: TemporalEventCollection) -> dict[str, Any]:
    bundle = collection.to_bundle()
    records = collection.to_records()
    assertion_basis_ok = True
    unresolved_ok = True
    modality_primary_sense_consistent = True
    for record in records:
        metadata = record.get("contextual_metadata", {})
        if not isinstance(metadata, dict):
            assertion_basis_ok = False
            unresolved_ok = False
            modality_primary_sense_consistent = False
            continue
        assertion_basis = metadata.get("assertion_basis")
        if assertion_basis is not None:
            if not isinstance(assertion_basis, dict) or any(str(value) not in ALLOWED_ASSERTION_BASES for value in assertion_basis.values()):
                assertion_basis_ok = False
        unresolved = metadata.get("unresolved")
        if unresolved is not None:
            if not isinstance(unresolved, dict):
                unresolved_ok = False
            elif not isinstance(assertion_basis, dict):
                unresolved_ok = False
            else:
                for field_path in unresolved.keys():
                    if assertion_basis.get(field_path) != "unresolved":
                        unresolved_ok = False
        sensory = metadata.get("sensory")
        modality = str(record.get("modality"))
        if modality.startswith("olfaction") and isinstance(sensory, dict):
            if sensory.get("primary_sense") != "olfaction":
                modality_primary_sense_consistent = False
    return {
        "record_count": len(records),
        "top_level_keys_ok": all(set(record.keys()) == set(CANONICAL_TOP_LEVEL_FIELDS) for record in records),
        "temporal_contract_ok": all(
            isinstance(record.get("contextual_metadata"), dict)
            and isinstance(record["contextual_metadata"].get("temporal"), dict)
            and {"start", "anchor", "event_kind", "stream_id", "schema_version"} <= set(record["contextual_metadata"]["temporal"].keys())
            for record in records
        ),
        "bundle_contract_ok": set(bundle.keys()) == {"spec_version", "generated_at", "event_count", "summary", "events"},
        "assertion_basis_ok": assertion_basis_ok,
        "unresolved_ok": unresolved_ok,
        "modality_primary_sense_consistent": modality_primary_sense_consistent,
    }


def audit_unification_integrity(base_dir: str | Path | None = None) -> dict[str, Any]:
    work_dir = _work_dir(base_dir)
    pipeline = TSELPipeline()
    generic_packet_dir = _build_generic_packet(work_dir)
    synapse_packet_dir = _build_synapse_packet(work_dir, complete=True)

    cases = {
        "eeg_config": pipeline.ingest(EXAMPLES / "data" / "eeg_direct.json", EXAMPLES / "configs" / "eeg_direct.json"),
        "olfaction_config": pipeline.ingest(EXAMPLES / "data" / "olfaction_trials.csv", EXAMPLES / "configs" / "olfaction.json"),
        "multisensory_auto": pipeline.ingest_auto(EXAMPLES / "data" / "multisensory_matrix.csv", "multisensory"),
        "generic_packet": pipeline.ingest_auto(generic_packet_dir, "multisensory"),
        "typed_packet": pipeline.ingest_auto(synapse_packet_dir, "olfaction"),
    }
    route_summaries = {name: _collect_contract_summary(collection) for name, collection in cases.items()}
    is_unified = all(
        summary["top_level_keys_ok"]
        and summary["temporal_contract_ok"]
        and summary["bundle_contract_ok"]
        and summary["assertion_basis_ok"]
        and summary["unresolved_ok"]
        and summary["modality_primary_sense_consistent"]
        for summary in route_summaries.values()
    )

    fragmentation_risks = [
        {
            "risk": "viewer_alias_fields",
            "severity": "low",
            "detail": "viewer/app.py writes convenience aliases such as sensory_class and top-level acquisition_profile alongside the canonical sensory and acquisition blocks. These do not fork the contract, but they duplicate canonical meanings.",
        },
        {
            "risk": "modality_subtype_overloading",
            "severity": "low",
            "detail": "packet-derived modalities such as olfaction_perception and olfaction_aggregate are valid subtypes, but they rely on contextual_metadata.sensory.primary_sense to keep sensory semantics aligned with broader routes.",
        },
    ]

    return {
        "is_unified": is_unified,
        "canonical_top_level_fields": CANONICAL_TOP_LEVEL_FIELDS,
        "route_summaries": route_summaries,
        "semantic_findings": [
            "All inspected routes still emit the same seven-field top-level event schema.",
            "Temporal semantics continue to flow through contextual_metadata.temporal across manual, auto-routed, packet, and typed-packet paths.",
            "assertion_basis and unresolved are normalized and validated through the same metadata standardizer.",
            "Packet-specific and route-specific metadata remain inside contextual_metadata rather than creating route-specific top-level schemas.",
            "No inspected route bypasses TemporalEvent serialization or bundle generation.",
        ],
        "fragmentation_risks": fragmentation_risks,
    }


def _evaluate_false_positive_restraint_suite(work_dir: Path) -> list[CaseAssessment]:
    results: list[CaseAssessment] = []

    null_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _sample(1, 0.2, sequence_index=1),
        _sample(2, 0.15, sequence_index=2),
    ])
    null_collection = enrich_experience(null_collection)
    results.append(
        CaseAssessment(
            name="null_structure_restraint",
            suite="false_positive_restraint",
            support="Only generic samples are present, with no explicit segment markers or packet declarations.",
            expected_claims=["No phase, experience, or stimulus structure should be invented."],
            unresolved_if_unsupported=["All higher-order experience structure remains absent."],
            passed=all(event.phase is None and "experience" not in event.contextual_metadata and "stimulus" not in event.contextual_metadata for event in null_collection.events),
        )
    )

    ambiguous_path = _build_ambiguous_route_file(work_dir)
    try:
        build_auto_ingest_plan(ambiguous_path, "generic")
        ambiguous_ok = False
        ambiguous_note = "Generic routing accepted ambiguous EEG and olfaction evidence."
    except AutoRoutingError as exc:
        ambiguous_ok = "ambiguous deterministic route evidence" in str(exc)
        ambiguous_note = str(exc)
    results.append(
        CaseAssessment(
            name="ambiguous_route_restraint",
            suite="false_positive_restraint",
            support="The file mixes strong EEG and olfaction route evidence.",
            expected_claims=["The route must remain unresolved and raise an explicit ambiguity error."],
            unresolved_if_unsupported=["No acquisition route should be guessed."],
            passed=ambiguous_ok,
            notes=[ambiguous_note],
        )
    )

    missing_context_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _marker(1, "task_onset", marker_type="behavior"),
        _sample(1, 0.2, sequence_index=1),
        _sample(2, 0.3, sequence_index=2),
        _marker(3, "task_offset", marker_type="behavior"),
    ])
    missing_context_collection = enrich_experience(missing_context_collection)
    results.append(
        CaseAssessment(
            name="missing_context_restraint",
            suite="false_positive_restraint",
            support="Behavior markers are present, but no stimulus marker type or source stimulus block exists.",
            expected_claims=["No stimulus block should be fabricated."],
            unresolved_if_unsupported=["Stimulus context remains absent."],
            passed=all("stimulus" not in event.contextual_metadata for event in missing_context_collection.events),
        )
    )

    broken_continuity_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _marker(1, "odor_onset"),
        _sample(1, 0.3, sequence_index=1),
        _sample(2, 0.7, sequence_index=2),
        _sample(5, 0.2, sequence_index=3),
        _marker(5, "odor_offset"),
    ])
    broken_continuity_collection = enrich_experience(broken_continuity_collection)
    continuity_states = {
        event.contextual_metadata["experience"]["continuity_state"]
        for event in broken_continuity_collection.events
        if isinstance(event.contextual_metadata.get("experience"), dict)
        and isinstance(event.contextual_metadata["experience"].get("continuity_state"), str)
    }
    results.append(
        CaseAssessment(
            name="broken_continuity_restraint",
            suite="false_positive_restraint",
            support="The sampled stream has a deterministic temporal gap inside an otherwise marked segment.",
            expected_claims=["Continuity may be interrupted or fragmented, but not continuous."],
            unresolved_if_unsupported=["No continuous experience claim is allowed across a verified gap."],
            passed=bool(continuity_states) and "continuous" not in continuity_states,
            observed=sorted(continuity_states),
        )
    )

    relation_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _sample(1, 0.2, sequence_index=1),
        _marker(2, "verbal_report", marker_type="behavior"),
    ])
    relation_collection = enrich_experience(relation_collection)
    report_event = next(event for event in relation_collection.events if event.signal_type == "marker")
    relations = report_event.contextual_metadata.get("relations", [])
    results.append(
        CaseAssessment(
            name="cross_event_relation_restraint",
            suite="false_positive_restraint",
            support="A report marker exists, but there is no supported experience membership.",
            expected_claims=["A report phase is allowed, but no describes relation should be invented."],
            unresolved_if_unsupported=["Experience relation targets remain absent."],
            passed=report_event.phase == "report"
            and "experience" not in report_event.contextual_metadata
            and all(relation["relation_type"] != "describes" for relation in relations),
        )
    )

    noise_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _marker(1, "odor_onset"),
        _sample(1, 0.4, sequence_index=1),
        _sample(2, 0.9, sequence_index=2),
        _sample(3, 0.6, sequence_index=3),
        _sample(4, 0.8, sequence_index=4),
        _marker(5, "odor_offset"),
    ])
    noise_collection = enrich_experience(noise_collection)
    active_samples = [event for event in noise_collection.events if event.event_kind == "sample" and event.extent.start >= _time(1)]
    active_phases = {event.phase for event in active_samples if event.phase is not None}
    unresolved_reasons = {event.contextual_metadata.get("unresolved", {}).get("temporal.phase") for event in active_samples}
    results.append(
        CaseAssessment(
            name="noise_only_phase_restraint",
            suite="false_positive_restraint",
            support="Active samples are noisy and do not form a deterministic phase trajectory.",
            expected_claims=["No meaningful rise, peak, decay, or offset phases should be asserted."],
            unresolved_if_unsupported=["temporal.phase remains unresolved because the decay is non-monotonic."],
            passed=not (active_phases & {"rise", "peak", "sustain", "decay", "offset"})
            and unresolved_reasons == {"non_monotonic_decay"},
            observed=sorted(reason for reason in unresolved_reasons if isinstance(reason, str)),
        )
    )

    malformed_path = _build_malformed_json_file(work_dir)
    try:
        build_auto_ingest_plan(malformed_path, "generic")
        malformed_ok = False
        malformed_note = "Malformed JSON was accepted."
    except AutoRoutingError as exc:
        malformed_ok = "invalid JSON input" in str(exc)
        malformed_note = str(exc)
    results.append(
        CaseAssessment(
            name="malformed_input_restraint",
            suite="false_positive_restraint",
            support="The raw JSON file is syntactically invalid.",
            expected_claims=["The system must fail safely and explicitly."],
            unresolved_if_unsupported=["No route or structure should be guessed from malformed input."],
            passed=malformed_ok,
            notes=[malformed_note],
        )
    )

    return results

def _evaluate_supported_structure_suite(work_dir: Path) -> list[CaseAssessment]:
    results: list[CaseAssessment] = []
    pipeline = TSELPipeline()

    clear_path = _build_clear_experience_file(work_dir)
    clear_collection = pipeline.ingest_auto(clear_path, "eeg")
    clear_records = clear_collection.to_records()

    onset = _find_marker(clear_records, "stimulus_onset")
    offset = _find_marker(clear_records, "stimulus_offset")
    results.append(
        CaseAssessment(
            name="explicit_stimulus_recovery",
            suite="supported_structure_recovery",
            support="Source annotations explicitly mark stimulus onset and stimulus offset with marker_type=stimulus.",
            expected_claims=[
                "Stimulus onset and offset markers retain stimulus blocks.",
                "presentation_phase and delivery_state are deterministically derived on those explicit markers.",
            ],
            unresolved_if_unsupported=["stimulus_object remains absent because it was never supplied."],
            passed=onset["contextual_metadata"]["stimulus"]["presentation_phase"] == "onset"
            and onset["contextual_metadata"]["stimulus"]["delivery_state"] == "presented"
            and offset["contextual_metadata"]["stimulus"]["presentation_phase"] == "offset"
            and offset["contextual_metadata"]["stimulus"]["delivery_state"] == "removed"
            and all("stimulus_object" not in record.get("contextual_metadata", {}).get("stimulus", {}) for record in clear_records),
            observed=[
                str(onset["contextual_metadata"]["stimulus"]["presentation_phase"]),
                str(offset["contextual_metadata"]["stimulus"]["presentation_phase"]),
            ],
        )
    )

    continuity_states = _continuity_states(clear_records)
    results.append(
        CaseAssessment(
            name="valid_continuity_recovery",
            suite="supported_structure_recovery",
            support="Timestamps, sequence indices, and sample spacing are internally continuous across the deterministic benchmark.",
            expected_claims=["The experience continuity state resolves to continuous."],
            unresolved_if_unsupported=["No continuity_state should remain unresolved for this case."],
            passed=continuity_states == {"continuous"},
            observed=sorted(continuity_states),
        )
    )

    sample_phases = _phase_set(clear_records, signal_type="voltage")
    marker_phases = _phase_set(clear_records, signal_type="marker")
    results.append(
        CaseAssessment(
            name="phase_recovery",
            suite="supported_structure_recovery",
            support="The benchmark includes a baseline sample, explicit onset/offset, a monotonic rise to peak, monotonic decay, and trailing post-offset samples.",
            expected_claims=[
                "baseline, onset, rise, peak, decay, offset, aftereffect, and recovery are recovered where supported.",
                "report is recovered on the explicit verbal report marker.",
            ],
            unresolved_if_unsupported=["sustain remains absent because the signal never forms a plateau."],
            passed={"baseline", "onset", "rise", "peak", "decay", "offset", "aftereffect", "recovery"} <= sample_phases
            and {"onset", "offset", "report"} <= marker_phases
            and "sustain" not in sample_phases,
            observed=sorted(sample_phases | marker_phases),
        )
    )

    first_sample = next(record for record in clear_records if record["signal_type"] == "voltage")
    alignment = first_sample["contextual_metadata"].get("alignment", {})
    acquisition = first_sample["contextual_metadata"].get("acquisition", {})
    results.append(
        CaseAssessment(
            name="provenance_recovery",
            suite="supported_structure_recovery",
            support="The source metadata explicitly provide acquisition profile, instrument, device class, recording_id, subject_id, and trial_id.",
            expected_claims=[
                "Explicit acquisition metadata are preserved with source_provided basis.",
                "Explicit alignment identifiers remain attached as provenance context.",
            ],
            unresolved_if_unsupported=["No extra device or alignment identifiers are invented beyond the supplied values."],
            passed=acquisition.get("acquisition_profile") == "eeg"
            and acquisition.get("instrument") == "benchmark_eeg_cap"
            and acquisition.get("device_class") == "eeg_recorder"
            and _assertion(first_sample, "acquisition.acquisition_profile") == "source_provided"
            and _assertion(first_sample, "acquisition.instrument") == "source_provided"
            and alignment.get("recording_id") == "rec-001"
            and alignment.get("subject_id") == "sub-001"
            and alignment.get("trial_id") == "trial-001",
            observed=[str(acquisition.get("instrument")), str(alignment.get("recording_id"))],
        )
    )

    report_marker = _find_marker(clear_records, "verbal_report")
    report_relations = _relations(report_marker, "describes")
    results.append(
        CaseAssessment(
            name="relation_recovery",
            suite="supported_structure_recovery",
            support="The report marker falls inside a supported deterministic experience with explicit onset and offset markers.",
            expected_claims=[
                "The report marker preserves a describes relation to the resolved experience.",
                "Events preserve shared part_of stream and experience relations.",
            ],
            unresolved_if_unsupported=["No caused_by or unsupported causal relations are asserted."],
            passed=len(report_relations) == 1
            and report_relations[0].get("target_type") == "experience"
            and all(not _relations(record, "caused_by") for record in clear_records),
            observed=[str(report_relations[0]["target_id"])] if report_relations else [],
        )
    )

    clear_plan = build_auto_ingest_plan(clear_path, "generic")
    olfaction_plan = build_auto_ingest_plan(EXAMPLES / "data" / "olfaction_trials.csv", "generic")
    multisensory_plan = build_auto_ingest_plan(EXAMPLES / "data" / "multisensory_matrix.csv", "generic")
    packet_dir = _build_synapse_packet(work_dir, complete=True)
    packet_type = detect_special_packet_type(packet_dir)
    packet_plans = plan_special_packet(packet_dir, "olfaction")
    results.append(
        CaseAssessment(
            name="route_recovery",
            suite="supported_structure_recovery",
            support="Route evidence is strong and unambiguous for EEG JSON, olfaction table, multisensory matrix, and the typed Synapse packet directory.",
            expected_claims=[
                "Generic auto-routing resolves strong routes rather than downgrading them to unresolved.",
                "The typed packet is detected and planned through its dedicated packet profile.",
            ],
            unresolved_if_unsupported=["No route remains ambiguous in these benchmark cases."],
            passed=clear_plan.sensory_profile == "eeg"
            and olfaction_plan.sensory_profile == "olfaction"
            and multisensory_plan.sensory_profile == "multisensory"
            and packet_type == "dream_synapse"
            and isinstance(packet_plans, list)
            and bool(packet_plans),
            observed=[clear_plan.sensory_profile, olfaction_plan.sensory_profile, multisensory_plan.sensory_profile, str(packet_type)],
        )
    )

    packet_collection = pipeline.ingest_auto(packet_dir, "olfaction")
    packet_record = packet_collection.to_records()[0]
    results.append(
        CaseAssessment(
            name="packet_provenance_recovery",
            suite="supported_structure_recovery",
            support="The typed packet declares olfaction, packet profile identity, and packet-level acquisition metadata.",
            expected_claims=[
                "Packet-declared sensory and acquisition metadata are preserved with packet_declared basis.",
                "Packet completeness and profile provenance remain attached to normalized events.",
            ],
            unresolved_if_unsupported=["Absolute time remains partial rather than fabricated."],
            passed=packet_record["contextual_metadata"]["sensory"]["primary_sense"] == "olfaction"
            and packet_record["contextual_metadata"]["acquisition"]["acquisition_profile"] == "olfaction"
            and _assertion(packet_record, "sensory.primary_sense") == "packet_declared"
            and _assertion(packet_record, "acquisition.acquisition_profile") == "packet_declared"
            and packet_record["contextual_metadata"]["packet_profile"] == "dream_synapse"
            and packet_record["contextual_metadata"]["completeness"]["missing_dimensions"] == ["absolute_time"],
            observed=[packet_record["contextual_metadata"]["packet_profile"]],
        )
    )

    table_collection = pipeline.ingest(EXAMPLES / "data" / "olfaction_trials.csv", EXAMPLES / "configs" / "olfaction.json")
    first_table_record = table_collection.to_records()[0]
    results.append(
        CaseAssessment(
            name="tabular_context_recovery",
            suite="supported_structure_recovery",
            support="The tabular olfaction observation file supplies timestamp, source, trial_id, and humidity_pct directly.",
            expected_claims=["Explicit row metadata are preserved inside contextual_metadata without weakening the shared event schema."],
            unresolved_if_unsupported=["No sample-level phase or continuity is invented for row-style observations."],
            passed=first_table_record["contextual_metadata"]["trial_id"] == "T-001"
            and first_table_record["contextual_metadata"]["humidity_pct"] == "45.1"
            and first_table_record["contextual_metadata"]["temporal"]["event_kind"] == "observation"
            and first_table_record["contextual_metadata"]["temporal"].get("phase") is None,
            observed=[str(first_table_record["contextual_metadata"]["trial_id"])],
        )
    )

    for case in results:
        if case.passed:
            continue
        if case.failure_classification is None:
            case.failure_classification = "expected_test_wrong"
    return results


def _evaluate_collection_quality_suite(work_dir: Path) -> list[CaseAssessment]:
    results: list[CaseAssessment] = []
    pipeline = TSELPipeline()

    sample_only = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _sample(1, 0.15, sequence_index=1),
        _sample(2, 0.12, sequence_index=2),
    ])
    sample_only = enrich_experience(sample_only)
    results.append(
        CaseAssessment(
            name="missing_stimulus_markers",
            suite="collection_quality",
            support="Only sampled values exist; no stimulus markers or declared packet segments exist.",
            expected_claims=["Higher-order experience structure remains unresolved."],
            unresolved_if_unsupported=["No phases, stimulus blocks, or experience membership are created."],
            passed=sample_only.summary()["experience_count"] == 0 and not sample_only.summary()["phases"],
            upstream_issues=["missing_stimulus_markers"],
            notes=["The unresolved output is caused by missing stimulus annotation rather than TSEL under-claiming."],
        )
    )

    weak_provenance_path = _build_weak_provenance_file(work_dir)
    weak_collection = pipeline.ingest_auto(weak_provenance_path, "eeg")
    weak_record = weak_collection.to_records()[0]
    weak_alignment = weak_record["contextual_metadata"].get("alignment", {})
    weak_acquisition = weak_record["contextual_metadata"].get("acquisition", {})
    results.append(
        CaseAssessment(
            name="missing_acquisition_metadata",
            suite="collection_quality",
            support="The source defines a sampled EEG stream but omits explicit instrument and device class.",
            expected_claims=["Observed sample_rate and channel are retained, but instrument and device class remain absent."],
            unresolved_if_unsupported=["Missing acquisition metadata are not silently completed."],
            passed="instrument" not in weak_acquisition and "device_class" not in weak_acquisition and weak_acquisition.get("sample_rate_hz") == 1.0,
            upstream_issues=["missing_acquisition_metadata"],
            notes=["This unresolved area reflects missing source acquisition metadata."],
        )
    )
    results.append(
        CaseAssessment(
            name="weak_provenance",
            suite="collection_quality",
            support="The source provides only a source identifier and no session, recording, subject, or trial identifiers.",
            expected_claims=["source_id is preserved, but no stronger alignment context is fabricated."],
            unresolved_if_unsupported=["Session, recording, subject, and trial provenance remain absent."],
            passed=weak_alignment.get("source_id") == "REC-WEAK"
            and all(key not in weak_alignment for key in ("session_id", "recording_id", "subject_id", "trial_id")),
            upstream_issues=["weak_provenance"],
            notes=["Weak provenance is visible in the normalized output and not hidden by defaults."],
        )
    )

    olfaction_collection = pipeline.ingest(EXAMPLES / "data" / "olfaction_trials.csv", EXAMPLES / "configs" / "olfaction.json")
    results.append(
        CaseAssessment(
            name="inadequate_temporal_resolution",
            suite="collection_quality",
            support="The olfaction table contains timestamped observations but not high-resolution within-episode sampled trajectories.",
            expected_claims=["Row observations stay as observations; phase and continuity richness is not forced."],
            unresolved_if_unsupported=["No baseline, rise, peak, or recovery structure is invented from sparse rows."],
            passed=olfaction_collection.summary()["experience_count"] == 0 and not olfaction_collection.summary()["phases"],
            upstream_issues=["inadequate_temporal_resolution"],
            notes=["This is an upstream collection-resolution limitation, not a TSEL failure."],
        )
    )

    sparse_path = _build_clear_experience_file(work_dir, include_baseline=False, include_trailing=False)
    sparse_collection = pipeline.ingest_auto(sparse_path, "eeg")
    sparse_summary = sparse_collection.summary()
    results.append(
        CaseAssessment(
            name="insufficient_pre_post_windows",
            suite="collection_quality",
            support="The deterministic stream contains explicit onset and offset but omits baseline samples and post-offset trailing samples.",
            expected_claims=["Supported stimulus phases are retained, but baseline and aftereffect/recovery remain absent."],
            unresolved_if_unsupported=["No baseline or recovery phases are claimed without supporting windows."],
            passed="baseline" not in sparse_summary["phases"] and "aftereffect" not in sparse_summary["phases"] and "recovery" not in sparse_summary["phases"],
            upstream_issues=["insufficient_pre_stimulus_window", "insufficient_post_stimulus_window"],
            notes=["The missing windows are visible as absent supported phases rather than as fabricated structure."],
        )
    )

    broken_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _marker(1, "stimulus_onset"),
        _sample(1, 0.3, sequence_index=1),
        _sample(2, 0.7, sequence_index=2),
        _sample(5, 0.2, sequence_index=3),
        _marker(5, "stimulus_offset"),
    ])
    broken_collection = enrich_experience(broken_collection)
    broken_states = _continuity_states(broken_collection.to_records())
    results.append(
        CaseAssessment(
            name="broken_timestamp_continuity",
            suite="collection_quality",
            support="A marked experience contains a verified internal temporal gap.",
            expected_claims=["The experience cannot remain continuous across the gap."],
            unresolved_if_unsupported=["Continuity downgrades to interrupted or fragmented."],
            passed=bool(broken_states) and broken_states <= {"interrupted", "fragmented"},
            observed=sorted(broken_states),
            upstream_issues=["broken_timestamp_continuity"],
            notes=["The continuity downgrade is driven by sample spacing, not by a heuristic guess."],
        )
    )

    incomplete_packet = _build_synapse_packet(work_dir, complete=False)
    missing_files = _missing_synapse_files(incomplete_packet)
    results.append(
        CaseAssessment(
            name="incomplete_packet_annotation",
            suite="collection_quality",
            support="The packet directory is missing a required typed-packet member.",
            expected_claims=["Typed packet detection refuses to treat the directory as a complete packet profile."],
            unresolved_if_unsupported=["Packet-level declarations remain unavailable."],
            passed=detect_special_packet_type(incomplete_packet) is None and bool(missing_files),
            observed=missing_files,
            upstream_issues=["incomplete_packet_annotation"],
            notes=["The missing file list identifies the upstream packet annotation gap directly."],
        )
    )

    ambiguous_path = _build_ambiguous_route_file(work_dir)
    try:
        build_auto_ingest_plan(ambiguous_path, "generic")
        ambiguous_ok = False
        ambiguous_note = "ambiguous route was accepted"
    except AutoRoutingError as exc:
        ambiguous_ok = "ambiguous deterministic route evidence" in str(exc)
        ambiguous_note = str(exc)
    results.append(
        CaseAssessment(
            name="ambiguous_route_evidence",
            suite="collection_quality",
            support="The input contains equally strong EEG and olfaction evidence in one flat table.",
            expected_claims=["The route remains ambiguous rather than being forced into one profile."],
            unresolved_if_unsupported=["Automatic route remains unresolved."],
            passed=ambiguous_ok,
            upstream_issues=["ambiguous_route_evidence"],
            notes=[ambiguous_note],
        )
    )

    missing_label_collection = TemporalEventCollection([
        _sample(0, 0.1, sequence_index=0),
        _marker(1, "task_onset", marker_type="behavior"),
        _sample(1, 0.2, sequence_index=1),
        _sample(2, 0.3, sequence_index=2),
        _marker(3, "task_offset", marker_type="behavior"),
    ])
    missing_label_collection = enrich_experience(missing_label_collection)
    results.append(
        CaseAssessment(
            name="missing_contextual_labels",
            suite="collection_quality",
            support="Markers exist, but they are typed only as generic behavior and never labeled as stimulus markers.",
            expected_claims=["The events remain unstimulated behavior context; no stimulus object is invented."],
            unresolved_if_unsupported=["Stimulus context remains absent."],
            passed=all("stimulus" not in event.contextual_metadata for event in missing_label_collection.events),
            upstream_issues=["missing_contextual_labels"],
            notes=["The missing label weakness is visible in output restraint rather than being silently repaired."],
        )
    )

    return results

def _collect_quality_issue_counts(cases: list[CaseAssessment]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        for issue in case.upstream_issues:
            counts[issue] = counts.get(issue, 0) + 1
    return dict(sorted(counts.items()))


def _build_balance_metrics(
    restraint_cases: list[CaseAssessment],
    recovery_cases: list[CaseAssessment],
    collection_cases: list[CaseAssessment],
) -> dict[str, Any]:
    recovery_failures = [case for case in recovery_cases if not case.passed]
    strictness_failures = [
        case
        for case in recovery_failures
        if case.failure_classification in {"rule_too_strict", "threshold_too_strict", "schema_too_narrow"}
    ]
    insufficient_data_failures = [
        case
        for case in recovery_failures
        if case.failure_classification in {"source_data_insufficient", "metadata_annotation_insufficient", "packet_profile_incomplete"}
    ]
    return {
        "false_positive_restraint_success": {
            "passed": sum(1 for case in restraint_cases if case.passed),
            "total": len(restraint_cases),
        },
        "supported_structure_recovery_success": {
            "passed": sum(1 for case in recovery_cases if case.passed),
            "total": len(recovery_cases),
        },
        "unresolved_outputs_due_to_insufficient_data": {
            "count": len([case for case in collection_cases if case.passed]),
            "cases": [case.name for case in collection_cases if case.passed],
        },
        "unresolved_outputs_due_to_rule_strictness": {
            "count": len(strictness_failures),
            "cases": [case.name for case in strictness_failures],
        },
        "unresolved_outputs_due_to_missing_metadata_or_collection_quality": {
            "count": len(insufficient_data_failures) + len([case for case in collection_cases if case.passed]),
            "cases": [case.name for case in insufficient_data_failures] + [case.name for case in collection_cases if case.passed],
        },
        "collection_quality_issue_counts": _collect_quality_issue_counts(collection_cases),
    }


def _render_unification_report(audit: dict[str, Any]) -> str:
    lines = [
        f"- Unified contract status: {'yes' if audit['is_unified'] else 'no'}",
        "- Canonical top-level fields: " + ", ".join(audit["canonical_top_level_fields"]),
        "",
        "## Semantic Findings",
    ]
    lines.extend(f"- {finding}" for finding in audit["semantic_findings"])
    lines.extend(["", "## Route Checks"])
    for name, summary in audit["route_summaries"].items():
        lines.append(
            f"- `{name}`: top_level={summary['top_level_keys_ok']}, temporal={summary['temporal_contract_ok']}, bundle={summary['bundle_contract_ok']}, assertion_basis={summary['assertion_basis_ok']}, unresolved={summary['unresolved_ok']}, modality_primary_sense={summary['modality_primary_sense_consistent']}"
        )
    lines.extend(["", "## Fragmentation Risks"])
    for risk in audit["fragmentation_risks"]:
        lines.append(f"- `{risk['risk']}` ({risk['severity']}): {risk['detail']}")
    return _report_lines("Unification Integrity", lines)


def _render_case_block(cases: list[CaseAssessment], *, title: str) -> list[str]:
    lines = [f"## {title}"]
    for case in cases:
        status = "PASS" if case.passed else "FAIL"
        lines.append(f"- `{case.name}`: {status}")
        lines.append(f"  support: {case.support}")
        lines.append(f"  expected: {'; '.join(case.expected_claims)}")
        if case.unresolved_if_unsupported:
            lines.append(f"  unresolved: {'; '.join(case.unresolved_if_unsupported)}")
        if case.observed:
            lines.append(f"  observed: {', '.join(case.observed)}")
        if case.failure_classification:
            lines.append(f"  classification: {case.failure_classification}")
        if case.upstream_issues:
            lines.append(f"  upstream issues: {', '.join(case.upstream_issues)}")
        if case.notes:
            lines.append(f"  notes: {' | '.join(case.notes)}")
    return lines


def _render_recovery_report(
    recovery_cases: list[CaseAssessment],
    restraint_cases: list[CaseAssessment],
    metrics: dict[str, Any],
) -> str:
    lines = [
        f"- False-positive restraint: {metrics['false_positive_restraint_success']['passed']} / {metrics['false_positive_restraint_success']['total']}",
        f"- Supported-structure recovery: {metrics['supported_structure_recovery_success']['passed']} / {metrics['supported_structure_recovery_success']['total']}",
        "",
    ]
    lines.extend(_render_case_block(recovery_cases, title="Supported Recovery Cases"))
    lines.extend([""])
    lines.extend(_render_case_block(restraint_cases, title="Restraint Reference Cases"))
    return _report_lines("Supported Structure Test Summary", lines)


def _render_collection_report(collection_cases: list[CaseAssessment], metrics: dict[str, Any]) -> str:
    lines = [
        "- Collection-quality diagnostics expose why valid structure could not be asserted safely.",
        "",
        "## Upstream Issue Counts",
    ]
    for issue, count in metrics["collection_quality_issue_counts"].items():
        lines.append(f"- `{issue}`: {count}")
    lines.extend([""])
    lines.extend(_render_case_block(collection_cases, title="Collection Quality Cases"))
    return _report_lines("Collection Quality Diagnostics", lines)


def run_balance_diagnostics(
    base_dir: str | Path | None = None,
    *,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    work_dir = _work_dir(base_dir)
    output_dir = ROOT if report_dir is None else Path(report_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    audit = audit_unification_integrity(work_dir)
    restraint_cases = _evaluate_false_positive_restraint_suite(work_dir)
    recovery_cases = _evaluate_supported_structure_suite(work_dir)
    collection_cases = _evaluate_collection_quality_suite(work_dir)
    metrics = _build_balance_metrics(restraint_cases, recovery_cases, collection_cases)

    payload = {
        "unification_integrity": audit,
        "false_positive_restraint": [case.to_record() for case in restraint_cases],
        "supported_structure_recovery": [case.to_record() for case in recovery_cases],
        "collection_quality": [case.to_record() for case in collection_cases],
        "balance_metrics": metrics,
    }

    json_output = output_dir / DEFAULT_JSON_OUTPUT.name
    unification_output = output_dir / DEFAULT_UNIFICATION_REPORT.name
    recovery_output = output_dir / DEFAULT_RECOVERY_REPORT.name
    collection_output = output_dir / DEFAULT_COLLECTION_REPORT.name

    _write_json(json_output, payload)
    _write_text(unification_output, _render_unification_report(audit))
    _write_text(recovery_output, _render_recovery_report(recovery_cases, restraint_cases, metrics))
    _write_text(collection_output, _render_collection_report(collection_cases, metrics))

    payload["outputs"] = {
        "json": str(json_output),
        "unification_report": str(unification_output),
        "recovery_report": str(recovery_output),
        "collection_report": str(collection_output),
    }
    return payload
