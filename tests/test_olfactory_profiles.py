from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from tsel.autorouting import AutoRoutingError, build_auto_ingest_plan
from tsel.pipeline import TSELPipeline


CANONICAL_TOP_LEVEL_FIELDS = {
    "timestamp",
    "modality",
    "source",
    "signal_type",
    "value",
    "unit",
    "contextual_metadata",
}


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    base = Path('output') / 'pytest-olfactory-tests'
    base.mkdir(parents=True, exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _mini_synapse_packet(packet_dir: Path) -> Path:
    packet_dir.mkdir(parents=True, exist_ok=True)
    files = {
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
    for name, content in files.items():
        (packet_dir / name).write_text(content, encoding="utf-8")
    return packet_dir


def _sensor_stream_payload(*, include_stimulus_markers: bool, marker_type: str = "stimulus") -> dict:
    payload = {
        "start_time": "2026-03-15T12:00:00Z",
        "sample_rate_hz": 1,
        "source": "sensor-rig-01",
        "metadata": {
            "trial_id": "trial-01",
            "odor_name": "limonene",
            "concentration": "2.0ppm",
        },
        "channels": {
            "gas_sensor_1": [0.10, 0.20, 0.55, 1.00, 0.60, 0.20, 0.12, 0.10],
            "gas_sensor_2": [0.11, 0.18, 0.52, 0.96, 0.58, 0.22, 0.13, 0.10],
        },
    }
    if include_stimulus_markers:
        payload["annotations"] = [
            {"offset_samples": 1, "label": "odor_onset", "marker_type": marker_type},
            {"offset_samples": 5, "label": "odor_offset", "marker_type": marker_type},
        ]
    return payload


def _neural_response_payload() -> dict:
    return {
        "start_time": "2026-03-15T12:00:00Z",
        "sample_rate_hz": 1,
        "source": "rec-olf-01",
        "metadata": {
            "trial_id": "trial-neural-01",
            "odor_name": "limonene",
            "concentration": "2.0ppm",
        },
        "channels": {
            "Fp1": [0.10, 0.20, 0.55, 1.00, 0.60, 0.20, 0.12, 0.10],
            "Fp2": [0.11, 0.18, 0.52, 0.96, 0.58, 0.22, 0.13, 0.10],
        },
        "annotations": [
            {"offset_samples": 1, "label": "odor_onset", "marker_type": "stimulus"},
            {"offset_samples": 5, "label": "odor_offset", "marker_type": "stimulus"},
        ],
    }


def test_olfactory_outputs_keep_shared_seven_field_contract(tmp_path: Path) -> None:
    input_path = _write(
        tmp_path / "olfactory_events.csv",
        "timestamp,sensor_id,odor_name,intensity_ppm,trial_id,temperature_c\n"
        "2026-03-15T12:00:00Z,sensor-a,limonene,1.2,T-001,21.4\n"
        "2026-03-15T12:00:01Z,sensor-a,limonene,1.6,T-001,21.5\n",
    )
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    first = collection.to_records()[0]
    assert set(first.keys()) == CANONICAL_TOP_LEVEL_FIELDS
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "olfactory_event_profile"


def test_olfactory_event_profile_preserves_explicit_concentration_context(tmp_path: Path) -> None:
    input_path = _write(
        tmp_path / "olfactory_event_log.csv",
        "timestamp,sensor_id,odor_name,intensity_ppm,trial_id,humidity_pct\n"
        "2026-03-15T12:00:00Z,sensor-a,limonene,1.2,T-001,45.1\n"
        "2026-03-15T12:00:01Z,sensor-a,limonene,1.8,T-001,45.3\n",
    )
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    first = collection.to_records()[0]
    metadata = first["contextual_metadata"]
    assert first["modality"] == "olfaction"
    assert first["unit"] == "ppm"
    assert first["value"] == 1.2
    assert metadata["odor_name"] == "limonene"
    assert metadata["trial_id"] == "T-001"
    assert metadata["domain_profile"]["profile_id"] == "olfactory_event_profile"
    assert metadata["domain_profile"]["resolution_status"] == "partial"
    assert "stimulus_markers" in metadata["completeness"]["missing_dimensions"]


def test_olfactory_sensor_stream_missing_identity_and_concentration_remain_unresolved(tmp_path: Path) -> None:
    input_path = _write_json(
        tmp_path / "gas_sensor_stream.json",
        {
            "start_time": "2026-03-15T12:00:00Z",
            "sample_rate_hz": 1,
            "source": "sensor-rig-01",
            "metadata": {"trial_id": "trial-01"},
            "channels": {
                "gas_sensor_1": [0.10, 0.20, 0.30, 0.20],
                "gas_sensor_2": [0.11, 0.18, 0.28, 0.19],
            },
        },
    )
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    first = collection.to_records()[0]
    metadata = first["contextual_metadata"]
    missing = set(metadata["completeness"]["missing_dimensions"])
    acquisition = metadata["acquisition"]
    assert metadata["domain_profile"]["profile_id"] == "olfactory_sensor_stream_profile"
    assert {"odor_identity", "odor_concentration"} <= missing
    assert "stimulus" not in metadata
    assert "instrument" not in acquisition
    assert "device_class" not in acquisition


def test_olfactory_generic_behavior_annotations_do_not_invent_stimulus_meaning(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "olfactory_behavior_annotations.json", _sensor_stream_payload(include_stimulus_markers=True, marker_type="behavior"))
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    assert all("stimulus" not in event.contextual_metadata for event in collection.events)


def test_olfactory_sparse_event_log_does_not_invent_continuity(tmp_path: Path) -> None:
    input_path = _write(
        tmp_path / "olfactory_sparse_events.csv",
        "timestamp,sensor_id,odor_name,intensity_ppm,trial_id\n"
        "2026-03-15T12:00:00Z,sensor-a,limonene,1.2,T-001\n"
        "2026-03-15T12:00:10Z,sensor-a,limonene,0.2,T-001\n",
    )
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    assert all("experience" not in event.contextual_metadata for event in collection.events)
    assert collection.summary()["continuity_count"] == 0


def test_olfactory_ambiguous_profile_selection_is_refused(tmp_path: Path) -> None:
    input_path = _write(
        tmp_path / "olfactory_ambiguous.csv",
        "timestamp,source,receptor_id,odor_name,gas_sensor_1,gas_sensor_2\n"
        "2026-03-15T12:00:00Z,mixed-rig,R-01,limonene,0.5,0.7\n",
    )

    with pytest.raises(AutoRoutingError, match="ambiguous olfactory profile evidence"):
        build_auto_ingest_plan(input_path, "olfaction")


def test_olfactory_subjective_report_profile_recovers_report_semantics(tmp_path: Path) -> None:
    input_path = _write(
        tmp_path / "olfactory_subjective_report.csv",
        "timestamp,source,odor_name,trial_id,report_text\n"
        "2026-03-15T12:00:00Z,subject-01,limonene,T-001,bright citrus with sharp edges\n",
    )
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    first = collection.to_records()[0]
    metadata = first["contextual_metadata"]
    assert first["unit"] == "text"
    assert first["signal_type"] == "subjective_report"
    assert metadata["temporal"]["event_kind"] == "report"
    assert metadata["domain_profile"]["profile_id"] == "olfactory_subjective_report_profile"
    assert metadata["sensory"]["primary_sense"] == "olfaction"


def test_olfactory_neural_response_profile_resolves_eeg_route(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "olfactory_neural_response.json", _neural_response_payload())
    plan = build_auto_ingest_plan(input_path, "olfaction")
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    assert plan.adapter == "timeseries_json"
    assert plan.config["modality"] == "eeg"
    first = collection.to_records()[0]
    metadata = first["contextual_metadata"]
    assert first["modality"] == "eeg"
    assert metadata["sensory"]["primary_sense"] == "olfaction"
    assert metadata["acquisition"]["acquisition_profile"] == "eeg"
    assert metadata["domain_profile"]["profile_id"] == "olfactory_neural_response_profile"
    assert {"baseline", "peak", "offset"} <= set(collection.summary()["phases"])


def test_olfactory_sensor_stream_recovers_supported_phase_and_continuity(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "olfactory_sensor_response.json", _sensor_stream_payload(include_stimulus_markers=True))
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "olfaction")

    summary = collection.summary()
    records = collection.to_records()
    marker_records = [record for record in records if record["signal_type"] == "marker"]
    sample_records = [record for record in records if record["signal_type"] != "marker"]
    continuity_states = {
        record["contextual_metadata"]["experience"]["continuity_state"]
        for record in records
        if isinstance(record["contextual_metadata"].get("experience"), dict)
    }
    relation_types = {
        relation["relation_type"]
        for record in sample_records
        for relation in record["contextual_metadata"].get("relations", [])
    }

    assert summary["primary_senses"] == ["olfaction"]
    assert {"baseline", "onset", "rise", "peak", "decay", "offset", "recovery"} <= set(summary["phases"])
    assert continuity_states == {"continuous"}
    assert marker_records and all("stimulus" in record["contextual_metadata"] for record in marker_records)
    assert {"part_of", "belongs_to"} <= relation_types


def test_olfactory_packet_profile_marks_packet_declared_basis_and_exposes_absolute_time_gap(tmp_path: Path) -> None:
    packet_dir = _mini_synapse_packet(tmp_path / "dream_synapse_packet")
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(packet_dir, "olfaction")

    first = collection.to_records()[0]
    metadata = first["contextual_metadata"]
    acquisition = metadata["acquisition"]
    assert metadata["domain_profile"]["profile_id"] == "olfactory_trial_packet_profile"
    assert metadata["assertion_basis"]["domain_profile.profile_id"] == "packet_declared"
    assert "absolute_time" in metadata["completeness"]["missing_dimensions"]
    assert acquisition["acquisition_profile"] == "olfaction"
    assert "instrument" not in acquisition
    assert "device_class" not in acquisition
