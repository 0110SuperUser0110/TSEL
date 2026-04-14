from __future__ import annotations

import json
import shutil
import struct
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from tsel.autorouting import AutoRoutingError, build_auto_ingest_plan
from tsel.packet_profiles import plan_special_packet
from tsel.pipeline import TSELPipeline


ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUT_ROOT = ROOT / "output" / "pytest-eeg-tests"
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
    TEST_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    path = TEST_OUTPUT_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path



def _write_json(path: Path, payload: dict | list) -> Path:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path



def _field(value: str, width: int) -> bytes:
    return f"{value:<{width}}"[:width].encode("ascii")



def _write_synthetic_edf(path: Path, labels: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    signal_count = len(labels)
    samples_per_record = 4
    data_records = 1
    record_duration = 1
    header_bytes = 256 + (signal_count * 256)

    header = bytearray()
    header.extend(_field("0", 8))
    header.extend(_field("TEST PATIENT", 80))
    header.extend(_field("SYNTHETIC RECORD", 80))
    header.extend(_field("15.03.26", 8))
    header.extend(_field("14.00.00", 8))
    header.extend(_field(str(header_bytes), 8))
    header.extend(_field("", 44))
    header.extend(_field(str(data_records), 8))
    header.extend(_field(str(record_duration), 8))
    header.extend(_field(str(signal_count), 4))

    transducers = ["cup" for _ in labels]
    dimensions = ["uV" for _ in labels]
    physical_mins = ["-32768" for _ in labels]
    physical_maxes = ["32767" for _ in labels]
    digital_mins = ["-32768" for _ in labels]
    digital_maxes = ["32767" for _ in labels]
    prefilterings = ["none" for _ in labels]
    sample_counts = [str(samples_per_record) for _ in labels]
    reserved = ["" for _ in labels]

    for values, width in (
        (labels, 16),
        (transducers, 80),
        (dimensions, 8),
        (physical_mins, 8),
        (physical_maxes, 8),
        (digital_mins, 8),
        (digital_maxes, 8),
        (prefilterings, 80),
        (sample_counts, 8),
        (reserved, 32),
    ):
        for value in values:
            header.extend(_field(value, width))

    samples = [struct.pack("<hhhh", 10 + idx, 20 + idx, 30 + idx, 40 + idx) for idx in range(signal_count)]
    path.write_bytes(bytes(header) + b"".join(samples))
    return path



def _direct_stream_payload(*, annotations: list[dict] | None = None, metadata: dict | None = None) -> dict:
    payload = {
        "start_time": "2026-03-15T12:00:00Z",
        "sample_rate_hz": 4,
        "source": "EEG-SESSION-01",
        "metadata": {
            "session_id": "session-01",
            "trial_id": "trial-01",
            "montage": "10-20",
            "reference": "average",
        },
        "channels": {
            "Fp1": [10.0, 10.2, 10.8, 12.4, 14.1, 12.0, 10.7, 10.2],
            "Fp2": [9.8, 10.1, 10.7, 12.0, 13.8, 11.9, 10.6, 10.1],
        },
    }
    if metadata:
        payload["metadata"].update(metadata)
    if annotations is not None:
        payload["annotations"] = annotations
    return payload



def _generic_multichannel_payload() -> dict:
    return {
        "start_time": "2026-03-15T12:00:00Z",
        "sample_rate_hz": 4,
        "source": "RIG-01",
        "channels": {
            "sensor_1": [0.1, 0.2, 0.3, 0.2],
            "sensor_2": [0.1, 0.2, 0.3, 0.2],
        },
    }



def _annotation_log_csv() -> str:
    return (
        "timestamp,session_id,annotation_label\n"
        "2026-03-15T12:00:00Z,session-01,eyes_closed\n"
        "2026-03-15T12:00:10Z,session-01,eyes_open\n"
    )



def _window_log_json() -> list[dict]:
    return [
        {
            "window_start_seconds": 0,
            "window_end_seconds": 30,
            "window_id": "epoch-001",
            "session_id": "sleep-session-01",
            "sleep_stage": "N2",
        },
        {
            "window_start_seconds": 30,
            "window_end_seconds": 60,
            "window_id": "epoch-002",
            "session_id": "sleep-session-01",
            "sleep_stage": "REM",
        },
    ]



def _create_eeg_packet(packet_dir: Path) -> Path:
    packet_dir.mkdir(parents=True, exist_ok=True)
    member_path = packet_dir / "stream.json"
    _write_json(member_path, _direct_stream_payload())
    manifest = {
        "packet_type": "eeg_session",
        "dataset": "synthetic_eeg_packet",
        "session_id": "packet-session-01",
        "trial_id": "packet-trial-01",
        "members": [
            {"path": "stream.json", "profile": "eeg"}
        ],
    }
    _write_json(packet_dir / "packet_manifest.json", manifest)
    return packet_dir



def test_eeg_outputs_keep_shared_seven_field_contract(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "eeg_direct.json", _direct_stream_payload())
    collection = TSELPipeline().ingest_auto(input_path, "eeg")

    first = collection.to_records()[0]
    assert set(first.keys()) == CANONICAL_TOP_LEVEL_FIELDS
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "eeg_direct_stream_profile"



def test_eeg_weak_multichannel_json_refuses_profile_resolution(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "weak_multichannel.json", _generic_multichannel_payload())

    with pytest.raises(AutoRoutingError, match="insufficient EEG profile evidence"):
        build_auto_ingest_plan(input_path, "eeg")



def test_eeg_raw_stream_does_not_invent_cognitive_or_stimulus_meaning(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "plain_eeg.json", _direct_stream_payload())
    collection = TSELPipeline().ingest_auto(input_path, "eeg")

    for record in collection.to_records():
        metadata = record["contextual_metadata"]
        assert "stimulus" not in metadata
        assert "cognitive_state" not in metadata
        assert "emotional_state" not in metadata
        assert "subjective_experience" not in metadata



def test_eeg_generic_annotations_do_not_invent_windows(tmp_path: Path) -> None:
    input_path = _write(tmp_path / "eeg_annotations.csv", _annotation_log_csv())
    collection = TSELPipeline().ingest_auto(input_path, "eeg")

    records = collection.to_records()
    assert records
    assert all(record["contextual_metadata"]["temporal"]["event_kind"] == "marker" for record in records)
    assert all(record["contextual_metadata"]["temporal"].get("end") is None for record in records)
    assert all("window_id" not in record["contextual_metadata"]["temporal"] for record in records)



def test_eeg_sparse_annotation_logs_do_not_invent_continuity(tmp_path: Path) -> None:
    input_path = _write(tmp_path / "eeg_sparse_annotations.csv", _annotation_log_csv())
    collection = TSELPipeline().ingest_auto(input_path, "eeg")

    assert collection.summary()["continuity_count"] == 0
    assert all("experience" not in event.contextual_metadata for event in collection.events)



def test_eeg_edf_without_eeg_signal_labels_is_not_resolved(tmp_path: Path) -> None:
    edf_path = _write_synthetic_edf(tmp_path / "non_eeg.edf", ["EMG", "Resp"])

    with pytest.raises(AutoRoutingError, match="EDF header does not declare deterministic EEG signal labels"):
        build_auto_ingest_plan(edf_path, "eeg")



def test_eeg_direct_stream_recovers_channel_identity_and_sampling_rate(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "eeg_direct.json", _direct_stream_payload())
    collection = TSELPipeline().ingest_auto(input_path, "eeg")

    records = collection.to_records()
    signal_records = [record for record in records if record["signal_type"] == "voltage"]
    first = signal_records[0]
    metadata = first["contextual_metadata"]
    assert {record["contextual_metadata"]["channel"] for record in signal_records} == {"Fp1", "Fp2"}
    assert metadata["sample_rate_hz"] == 4.0
    assert metadata["domain_profile"]["profile_id"] == "eeg_direct_stream_profile"
    assert metadata["acquisition"]["acquisition_profile"] == "eeg"



def test_eeg_event_aligned_windows_preserve_explicit_window_structure(tmp_path: Path) -> None:
    input_path = _write_json(tmp_path / "sleep_windows.json", _window_log_json())
    collection = TSELPipeline().ingest_auto(input_path, "eeg")

    records = collection.to_records()
    first = records[0]
    temporal = first["contextual_metadata"]["temporal"]
    assert first["modality"] == "sleep_stage"
    assert first["signal_type"] == "sleep_stage"
    assert first["unit"] == "stage"
    assert temporal["event_kind"] == "window"
    assert temporal["window_id"] == "epoch-001"
    assert temporal["end"] == "1970-01-01T00:00:30Z"
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "eeg_annotation_log_profile"



def test_eeg_edf_recovers_route_and_header_timing(tmp_path: Path) -> None:
    edf_path = _write_synthetic_edf(tmp_path / "eeg.edf", ["Fz", "Cz"])
    collection = TSELPipeline().ingest_auto(edf_path, "eeg")

    records = collection.to_records()
    first = records[0]
    assert first["modality"] == "eeg"
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "eeg_edf_profile"
    assert first["contextual_metadata"]["acquisition"]["acquisition_profile"] == "eeg"
    assert first["contextual_metadata"]["temporal"]["resolution_seconds"] == 0.25



def test_eeg_packet_profile_marks_packet_declared_basis_without_erasing_member_profile(tmp_path: Path) -> None:
    packet_dir = _create_eeg_packet(tmp_path / "eeg_packet")
    plans = plan_special_packet(packet_dir, "eeg")
    assert plans is not None and len(plans) == 1

    collection = TSELPipeline().ingest_auto(packet_dir, "eeg")
    first = collection.to_records()[0]
    metadata = first["contextual_metadata"]
    assert metadata["domain_profile"]["profile_id"] == "eeg_direct_stream_profile"
    assert metadata["packet_profile"] == "eeg_session"
    assert metadata["packet_profile_id"] == "eeg_packet_profile"
    assert metadata["assertion_basis"]["packet_profile"] == "packet_declared"
    assert metadata["assertion_basis"]["alignment.session_id"] == "packet_declared"
    assert metadata["alignment"]["session_id"] == "packet-session-01"
    assert metadata["alignment"]["trial_id"] == "packet-trial-01"
