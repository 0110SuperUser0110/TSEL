from __future__ import annotations

import json
import pytest
import subprocess
import sys
import shutil
from pathlib import Path

from tsel.models import TemporalEvent, TemporalEventCollection, TemporalExtent
from tsel.pipeline import TSELPipeline
from tsel.serializers import load_events, write_events
from tsel.standards import TSEL_SPEC_VERSION, evaluate_conformance, infer_sensory_profile, standard_assets, validate_sensory_profile, vocabulary_snapshot, write_standard_assets


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
STANDARDS = ROOT / "standards"


def test_bundle_output_roundtrips() -> None:
    pipeline = TSELPipeline()
    output_path = OUTPUT / "pytest-demo.bundle.json"
    collection = pipeline.ingest_many(pipeline.load_manifest(ROOT / "examples" / "configs" / "demo_manifest.json"))

    write_events(output_path, collection, fmt="bundle")
    loaded = load_events(output_path)

    assert len(loaded.events) == len(collection.events)
    assert loaded.validate().is_valid
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["spec_version"] == TSEL_SPEC_VERSION
    assert payload["event_count"] == len(collection.events)


def test_standard_assets_match_export() -> None:
    tmp_path = OUTPUT / "test-standard-assets"
    shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    written = write_standard_assets(tmp_path)
    assert {path.name for path in written} == set(standard_assets().keys())
    for path in written:
        repo_copy = STANDARDS / path.name
        assert repo_copy.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == json.loads(repo_copy.read_text(encoding="utf-8"))


def test_conformance_report_passes_for_demo_manifest() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest_many(pipeline.load_manifest(ROOT / "examples" / "configs" / "demo_manifest.json"))

    report = evaluate_conformance(collection.to_records(), temporal_validation=collection.validate())

    assert report.is_conformant
    assert report.error_count == 0


def test_interval_materialization_works() -> None:
    events = [
        TemporalEvent(
            timestamp="2026-03-15T14:00:00Z",
            modality="environment",
            source="rig-1",
            signal_type="odor_pulse",
            value="pulse_a",
            unit="event",
            extent=TemporalExtent(
                start="2026-03-15T14:00:00Z",
                end="2026-03-15T14:00:02Z",
                anchor="start",
                time_scale="second",
            ),
            event_kind="episode",
            episode_id="ep-1",
            sync_group="trial-1",
        ),
        TemporalEvent(
            timestamp="2026-03-15T14:00:00Z",
            modality="environment",
            source="rig-1",
            signal_type="ambient_temp_c",
            value=21.2,
            unit="C",
            extent=TemporalExtent.from_timestamp("2026-03-15T14:00:00Z", resolution_seconds=1.0, anchor="start", time_scale="sample"),
            event_kind="sample",
            sequence_index=0,
            sync_group="trial-1",
        ),
        TemporalEvent(
            timestamp="2026-03-15T14:00:01Z",
            modality="environment",
            source="rig-1",
            signal_type="ambient_temp_c",
            value=21.4,
            unit="C",
            extent=TemporalExtent.from_timestamp("2026-03-15T14:00:01Z", resolution_seconds=1.0, anchor="start", time_scale="sample"),
            event_kind="sample",
            sequence_index=1,
            sync_group="trial-1",
        ),
    ]
    collection = TemporalEventCollection(events)
    collection.sort_in_place()

    segments = collection.materialize_intervals()

    assert len(segments) == 1
    assert segments[0].metadata["episode_id"] == "ep-1"
    assert len(segments[0].events) == 3
    assert set(collection.synchronization_groups().keys()) == {"trial-1"}


def test_transition_validation_requires_from_and_to() -> None:
    collection = TemporalEventCollection(
        [
            TemporalEvent(
                timestamp="2026-03-15T14:00:00Z",
                modality="environment",
                source="rig-1",
                signal_type="state_change",
                value="odor_on",
                unit="event",
                event_kind="transition",
                transition_from="baseline",
            )
        ]
    )
    collection.sort_in_place()

    report = collection.validate()

    assert not report.is_valid
    assert any(issue.code == "invalid_transition_event" for issue in report.issues)


def test_cli_conformance_reports_valid_standard() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tsel.cli",
            "conformance",
            str(ROOT / "examples" / "data" / "eeg_direct.json"),
            "--config",
            str(ROOT / "examples" / "configs" / "eeg_direct.json"),
            "--json",
            "--strict",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["is_conformant"] is True
    assert payload["spec_version"] == TSEL_SPEC_VERSION


def test_cli_standard_exports_assets() -> None:
    tmp_dir = OUTPUT / "test-cli-standard-assets"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tsel.cli",
            "standard",
            "--output-dir",
            str(tmp_dir),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["snapshot"]["spec_version"] == TSEL_SPEC_VERSION
    assert {Path(path).name for path in payload["written"]} == {"vocabulary.json", "tsel-event.schema.json", "tsel-bundle.schema.json"}

def test_temporal_semantics_mapping_supports_interval_and_transition_fields() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "temporal_states.csv", ROOT / "examples" / "configs" / "temporal_states.json")

    assert len(collection.events) == 3
    records = collection.to_records()
    assert records[0]["contextual_metadata"]["temporal"]["event_kind"] == "episode"
    assert records[0]["contextual_metadata"]["temporal"]["episode_id"] == "ep-001"
    assert records[0]["contextual_metadata"]["temporal"]["window_id"] == "win-001"
    assert records[0]["contextual_metadata"]["temporal"]["confidence"] == 0.95
    assert records[2]["contextual_metadata"]["temporal"]["event_kind"] == "transition"
    assert records[2]["contextual_metadata"]["temporal"]["transition_from"] == "odor_present"
    assert records[2]["contextual_metadata"]["temporal"]["transition_to"] == "baseline"
    assert collection.validate().is_valid

def test_timeseries_adapters_emit_sync_groups() -> None:
    pipeline = TSELPipeline()

    csv_collection = pipeline.ingest(ROOT / "examples" / "data" / "eeg_timeseries.csv", ROOT / "examples" / "configs" / "eeg_timeseries.json")
    csv_records = csv_collection.to_records()
    csv_sync_groups = {
        record["contextual_metadata"]["temporal"]["sync_group"]
        for record in csv_records
        if record["timestamp"] == "2026-03-15T14:00:00Z"
    }
    assert len(csv_sync_groups) == 1

    json_collection = pipeline.ingest(ROOT / "examples" / "data" / "eeg_direct.json", ROOT / "examples" / "configs" / "eeg_direct.json")
    json_records = [record for record in json_collection.to_records() if record["signal_type"] == "voltage" and record["timestamp"] == "2026-03-15T15:30:00Z"]
    json_sync_groups = {record["contextual_metadata"]["temporal"]["sync_group"] for record in json_records}
    assert len(json_sync_groups) == 1


def test_validation_warns_when_parallel_samples_lack_sync_group() -> None:
    collection = TemporalEventCollection(
        [
            TemporalEvent(
                timestamp="2026-03-15T14:00:00Z",
                modality="eeg",
                source="session-1",
                signal_type="voltage",
                value=1.0,
                unit="uV",
                event_kind="sample",
                sequence_index=0,
                stream_id="eeg::session-1::Fp1::voltage",
                extent=TemporalExtent.from_timestamp("2026-03-15T14:00:00Z", resolution_seconds=1.0, anchor="start", time_scale="sample"),
            ),
            TemporalEvent(
                timestamp="2026-03-15T14:00:00Z",
                modality="eeg",
                source="session-1",
                signal_type="voltage",
                value=2.0,
                unit="uV",
                event_kind="sample",
                sequence_index=0,
                stream_id="eeg::session-1::Fp2::voltage",
                extent=TemporalExtent.from_timestamp("2026-03-15T14:00:00Z", resolution_seconds=1.0, anchor="start", time_scale="sample"),
            ),
        ]
    )
    collection.sort_in_place()

    report = collection.validate()

    assert any(issue.code == "missing_sync_group" for issue in report.issues)
def test_standard_snapshot_exposes_sensory_profiles() -> None:
    snapshot = vocabulary_snapshot()

    assert "sensory_profiles" in snapshot
    assert snapshot["sensory_profiles"]["eeg"]["modalities"] == ["eeg", "sleep_stage"]
    assert "generic" in snapshot["sensory_profiles"]
    assert snapshot["observation_statuses"] == ["observed", "partial", "missing", "inferred", "imputed", "derived"]
    assert snapshot["continuity_states"] == ["continuous", "interrupted", "fragmented", "reconstructed", "unknown"]
    assert snapshot["primary_senses"] == ["vision", "audition", "olfaction", "gustation", "somatosensation"]
    assert snapshot["trajectory_roles"] == ["baseline", "stimulus", "response", "report", "context", "aftereffect"]
    assert snapshot["delivery_states"] == ["prepared", "presented", "active", "maintained", "removed", "residual", "reported", "unknown"]
    assert snapshot["relation_types"] == ["part_of", "precedes", "follows", "overlaps", "caused_by", "evoked_by", "reported_by", "synchronized_with", "measured_by", "belongs_to", "describes"]
    assert snapshot["transform_stages"] == ["raw", "normalized", "segmented", "derived", "inferred", "annotated"]
    assert snapshot["experience_phases"] == ["baseline", "anticipation", "onset", "rise", "peak", "sustain", "decay", "offset", "aftereffect", "report", "recovery"]


def test_sensory_profile_inference_and_validation() -> None:
    config = json.loads((ROOT / "examples" / "configs" / "eeg_direct.json").read_text(encoding="utf-8"))

    assert infer_sensory_profile(config) == "eeg"
    validate_sensory_profile(config, "eeg")
    with pytest.raises(ValueError, match="incompatible"):
        validate_sensory_profile(config, "olfaction")


def test_conformance_warns_on_noncanonical_signal_type_tokens() -> None:
    record = {
        "timestamp": "2026-03-15T14:00:00Z",
        "modality": "environment",
        "source": "rig-1",
        "signal_type": "bad signal!",
        "value": 1,
        "unit": "score",
        "contextual_metadata": {
            "alignment": {"source_id": "rig-1"},
            "temporal": {
                "start": "2026-03-15T14:00:00Z",
                "end": None,
                "anchor": "instant",
                "duration_seconds": None,
                "resolution_seconds": None,
                "uncertainty_seconds": None,
                "time_scale": "second",
                "event_kind": "observation",
                "stream_id": "environment::rig-1::bad_signal",
                "schema_version": TSEL_SPEC_VERSION,
            },
        },
    }

    report = evaluate_conformance([record])

    assert any(issue.code == "noncanonical_signal_type" for issue in report.issues)


def test_temporal_event_preserves_completeness_and_experience_context() -> None:
    event = TemporalEvent(
        timestamp="2026-03-15T14:00:00Z",
        modality="olfaction",
        source="sensor-alpha",
        signal_type="measurement",
        value=0.5,
        unit="a.u.",
        contextual_metadata={
            "completeness": {
                "observation_status": "partial",
                "completeness_score": 0.5,
                "missing_dimensions": ["intensity", "affect"],
                "future_inference_allowed": True,
            },
            "experience": {
                "experience_id": "exp-001",
                "continuity_id": "cont-001",
                "continuity_index": 0,
                "continuity_state": "fragmented",
            },
        },
    )

    record = event.to_record()
    restored = TemporalEvent.from_record(record)

    assert record["contextual_metadata"]["completeness"]["observation_status"] == "partial"
    assert record["contextual_metadata"]["completeness"]["missing_dimensions"] == ["intensity", "affect"]
    assert record["contextual_metadata"]["experience"]["continuity_state"] == "fragmented"
    assert restored.contextual_metadata["completeness"]["future_inference_allowed"] is True
    assert restored.contextual_metadata["experience"]["experience_id"] == "exp-001"


def test_summary_tracks_partial_inference_and_continuity_counts() -> None:
    collection = TemporalEventCollection(
        [
            TemporalEvent(
                timestamp="2026-03-15T14:00:00Z",
                modality="olfaction",
                source="sensor-alpha",
                signal_type="measurement",
                value=0.5,
                unit="a.u.",
                contextual_metadata={
                    "completeness": {
                        "observation_status": "partial",
                        "missing_dimensions": ["intensity"],
                        "future_inference_allowed": True,
                    },
                    "experience": {
                        "experience_id": "exp-001",
                        "continuity_id": "cont-001",
                        "continuity_index": 0,
                    },
                },
            ),
            TemporalEvent(
                timestamp="2026-03-15T14:00:01Z",
                modality="olfaction",
                source="sensor-alpha",
                signal_type="measurement",
                value=0.7,
                unit="a.u.",
                contextual_metadata={
                    "completeness": {
                        "observation_status": "inferred",
                        "inferred_fields": ["intensity"],
                    },
                    "experience": {
                        "experience_id": "exp-001",
                        "continuity_id": "cont-001",
                        "continuity_index": 1,
                        "continuity_state": "reconstructed",
                    },
                },
            ),
        ]
    )
    collection.sort_in_place()

    summary = collection.summary()

    assert summary["observation_statuses"] == ["inferred", "partial"]
    assert summary["missing_dimensions"] == ["intensity"]
    assert summary["partial_event_count"] == 1
    assert summary["inferred_event_count"] == 1
    assert summary["future_inference_ready_count"] == 1
    assert summary["experience_count"] == 1
    assert summary["continuity_count"] == 1


def test_validation_and_conformance_understand_partial_observation_context() -> None:
    collection = TemporalEventCollection(
        [
            TemporalEvent(
                timestamp="2026-03-15T14:00:00Z",
                modality="olfaction",
                source="sensor-alpha",
                signal_type="measurement",
                value=0.5,
                unit="a.u.",
                contextual_metadata={
                    "completeness": {
                        "observation_status": "partial",
                        "future_inference_allowed": True,
                    },
                    "experience": {
                        "continuity_index": 2,
                    },
                },
            )
        ]
    )
    collection.sort_in_place()

    report = collection.validate()
    conformance = evaluate_conformance(collection.to_records(), temporal_validation=report)

    assert any(issue.code == "missing_missing_dimensions" for issue in report.issues)
    assert any(issue.code == "missing_continuity_id" for issue in report.issues)
    assert any(issue.code == "missing_missing_dimensions" for issue in conformance.issues)
    assert any(issue.code == "missing_continuity_id" for issue in conformance.issues)



def test_temporal_event_normalizes_experience_phases() -> None:
    event = TemporalEvent(
        timestamp="2026-03-15T14:00:00Z",
        modality="olfaction",
        source="sensor-alpha",
        signal_type="measurement",
        value=0.5,
        unit="a.u.",
        phase="Waning",
    )

    record = event.to_record()

    assert record["contextual_metadata"]["temporal"]["phase"] == "decay"


def test_conformance_warns_on_noncanonical_phase_tokens() -> None:
    record = {
        "timestamp": "2026-03-15T14:00:00Z",
        "modality": "olfaction",
        "source": "sensor-alpha",
        "signal_type": "measurement",
        "value": 0.5,
        "unit": "a.u.",
        "contextual_metadata": {
            "alignment": {"source_id": "sensor-alpha"},
            "temporal": {
                "start": "2026-03-15T14:00:00Z",
                "end": None,
                "anchor": "instant",
                "duration_seconds": None,
                "resolution_seconds": None,
                "uncertainty_seconds": None,
                "time_scale": "second",
                "event_kind": "observation",
                "stream_id": "olfaction::sensor-alpha::measurement",
                "schema_version": TSEL_SPEC_VERSION,
                "phase": "peak+fade",
            },
        },
    }

    report = evaluate_conformance([record])

    assert any(issue.code == "noncanonical_phase" for issue in report.issues)



def test_temporal_event_preserves_unified_ontology_context_blocks() -> None:
    event = TemporalEvent(
        timestamp="2026-03-15T14:00:00Z",
        modality="olfaction",
        source="sensor-alpha",
        signal_type="measurement",
        value=0.5,
        unit="a.u.",
        contextual_metadata={
            "sensory": {
                "primary_sense": "smell",
                "submodality": "odorant",
                "trajectory_role": "stimulus",
            },
            "acquisition": {
                "acquisition_profile": "olfaction",
                "device_class": "e_nose",
                "sample_rate_hz": 4,
                "transform_stage": "normalised",
            },
            "stimulus": {
                "stimulus_label": "sample_a",
                "presentation_phase": "waning",
                "delivery_state": "off",
                "intensity_estimate": 0.4,
                "intensity_unit": "score",
            },
            "relations": [
                {
                    "relation_type": "partof",
                    "target_id": "experience::olfaction::sensor_alpha::001",
                    "target_type": "experience",
                    "confidence": 0.9,
                }
            ],
        },
    )

    record = event.to_record()
    summary = TemporalEventCollection([TemporalEvent.from_record(record)]).summary()

    assert record["contextual_metadata"]["sensory"]["primary_sense"] == "olfaction"
    assert record["contextual_metadata"]["acquisition"]["transform_stage"] == "normalized"
    assert record["contextual_metadata"]["stimulus"]["presentation_phase"] == "decay"
    assert record["contextual_metadata"]["stimulus"]["delivery_state"] == "removed"
    assert record["contextual_metadata"]["relations"][0]["relation_type"] == "part_of"
    assert summary["primary_senses"] == ["olfaction"]
    assert summary["acquisition_profiles"] == ["olfaction"]
    assert summary["relation_count"] == 1
