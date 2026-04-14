from __future__ import annotations

import json
import pytest
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from tsel.pipeline import TSELPipeline
from tsel.serializers import load_events


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _field(value: str, width: int) -> bytes:
    return f"{value:<{width}}"[:width].encode("ascii")


def _write_synthetic_edf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    signal_count = 2
    samples_per_record = 4
    data_records = 1
    record_duration = 1
    header_bytes = 256 + (signal_count * 256)

    header = bytearray()
    header.extend(_field("0", 8))
    header.extend(_field("TEST PATIENT", 80))
    header.extend(_field("SYNTHETIC EEG", 80))
    header.extend(_field("15.03.26", 8))
    header.extend(_field("14.00.00", 8))
    header.extend(_field(str(header_bytes), 8))
    header.extend(_field("", 44))
    header.extend(_field(str(data_records), 8))
    header.extend(_field(str(record_duration), 8))
    header.extend(_field(str(signal_count), 4))

    labels = ["Fz", "Cz"]
    transducers = ["cup", "cup"]
    dimensions = ["uV", "uV"]
    physical_mins = ["-32768", "-32768"]
    physical_maxes = ["32767", "32767"]
    digital_mins = ["-32768", "-32768"]
    digital_maxes = ["32767", "32767"]
    prefilterings = ["none", "none"]
    sample_counts = [str(samples_per_record), str(samples_per_record)]
    reserved = ["", ""]

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

    signal_1 = struct.pack("<hhhh", 10, 20, 30, 40)
    signal_2 = struct.pack("<hhhh", -10, -20, -30, -40)
    path.write_bytes(bytes(header) + signal_1 + signal_2)


def test_csv_ingest_preserves_schema_and_remaining_fields() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "olfaction_trials.csv", ROOT / "examples" / "configs" / "olfaction.json")

    assert len(collection.events) == 3
    first = collection.to_records()[0]
    assert first["timestamp"] == "2026-03-15T14:00:00Z"
    assert first["modality"] == "olfaction"
    assert first["source"] == "sensor-alpha"
    assert first["signal_type"] == "limonene"
    assert first["value"] == 1.2
    assert first["unit"] == "ppm"
    assert first["contextual_metadata"]["trial_id"] == "T-001"
    assert first["contextual_metadata"]["humidity_pct"] == "45.1"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "observation"


def test_json_ingest_preserves_provenance() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "environment_events.json", ROOT / "examples" / "configs" / "environment.json")

    assert len(collection.events) == 2
    first = collection.to_records()[0]
    assert first["modality"] == "environment"
    assert first["contextual_metadata"]["phase"] == "baseline"
    assert first["contextual_metadata"]["trial_id"] == "ENV-01"
    assert first["contextual_metadata"]["provenance"]["record_index"] == 1


def test_timeseries_ingest_expands_multichannel_rows_with_resolution() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "eeg_timeseries.csv", ROOT / "examples" / "configs" / "eeg_timeseries.json")

    assert len(collection.events) == 6
    first = collection.to_records()[0]
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "sample"
    assert first["contextual_metadata"]["temporal"]["resolution_seconds"] == 1.0
    assert first["contextual_metadata"]["temporal"]["sequence_index"] == 0


def test_timeseries_json_ingest_handles_direct_eeg_stream() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "eeg_direct.json", ROOT / "examples" / "configs" / "eeg_direct.json")

    assert len(collection.events) == 10
    records = collection.to_records()
    signal_events = [record for record in records if record["signal_type"] == "voltage"]
    marker_events = [record for record in records if record["signal_type"] == "marker"]
    assert len(signal_events) == 8
    assert len(marker_events) == 2
    assert {record["contextual_metadata"]["channel"] for record in signal_events} == {"Fp1", "Fp2"}
    assert signal_events[0]["unit"] == "uV"
    assert signal_events[0]["contextual_metadata"]["sample_rate_hz"] == 4.0
    assert signal_events[0]["contextual_metadata"]["temporal"]["event_kind"] == "sample"
    assert marker_events[0]["contextual_metadata"]["temporal"]["event_kind"] == "marker"




def test_pipeline_enriches_continuous_experience_phases() -> None:
    payload = {
        "start_time": "2026-03-15T15:30:00Z",
        "sample_rate_hz": 4,
        "source": "EEG-EPISODE-01",
        "metadata": {"dataset": "synthetic_experience_eeg", "condition": "rose exposure"},
        "channels": {
            "Fp1": [10.0, 11.0, 13.0, 15.0, 13.5, 11.8, 10.6],
            "Fp2": [9.8, 10.7, 12.5, 14.2, 12.9, 11.2, 10.1],
        },
        "annotations": [
            {"offset_samples": 1, "label": "odor_onset", "marker_type": "stimulus"},
            {"offset_samples": 5, "label": "odor_offset", "marker_type": "stimulus"},
            {"offset_samples": 6, "label": "verbal_report", "marker_type": "behavior"},
        ],
    }
    input_path = OUTPUT / "synthetic_experience_episode.json"
    input_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    pipeline = TSELPipeline()
    collection = pipeline.ingest(input_path, ROOT / "examples" / "configs" / "eeg_direct.json")

    records = collection.to_records()
    sample_phases = {
        record["contextual_metadata"]["temporal"].get("phase")
        for record in records
        if record["signal_type"] == "voltage"
    }
    marker_phases = {
        record["contextual_metadata"]["temporal"].get("phase")
        for record in records
        if record["signal_type"] == "marker"
    }
    summary = collection.summary()

    assert {"baseline", "onset", "rise", "peak", "decay", "offset"} <= sample_phases
    assert sample_phases & {"aftereffect", "recovery"}
    assert {"onset", "offset", "report"} <= marker_phases
    assert summary["experience_count"] == 1
    assert summary["continuity_count"] == 1
    assert "peak" in summary["phases"]
    assert all("experience" in record["contextual_metadata"] for record in records)

def test_auto_channel_csv_ingest_handles_generic_multisensory_matrix() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "multisensory_matrix.csv", ROOT / "examples" / "configs" / "multisensory_matrix.json")

    assert len(collection.events) == 6
    records = collection.to_records()
    assert {record["signal_type"] for record in records} == {"odor_intensity", "skin_conductance", "ambient_temp_c"}
    ambient = next(record for record in records if record["signal_type"] == "ambient_temp_c")
    assert ambient["unit"] == "C"
    assert ambient["contextual_metadata"]["subject_id"] == "SUB-01"
    assert ambient["contextual_metadata"]["temporal"]["resolution_seconds"] == 1.0


def test_edf_ingest_reads_direct_eeg_file() -> None:
    pipeline = TSELPipeline()
    edf_path = OUTPUT / "synthetic_eeg.edf"
    _write_synthetic_edf(edf_path)
    collection = pipeline.ingest(edf_path, ROOT / "examples" / "configs" / "eeg_edf.json")

    assert len(collection.events) == 8
    records = collection.to_records()
    assert {record["contextual_metadata"]["channel"] for record in records} == {"Fz", "Cz"}
    assert all(record["modality"] == "eeg" for record in records)
    assert all(record["signal_type"] == "voltage" for record in records)
    assert records[0]["source"] == "SYNTHETIC EEG"
    assert records[0]["contextual_metadata"]["temporal"]["resolution_seconds"] == 0.25


def test_batch_ingest_validates_as_temporal_layer() -> None:
    pipeline = TSELPipeline()
    jobs = pipeline.load_manifest(ROOT / "examples" / "configs" / "demo_manifest.json")
    collection = pipeline.ingest_many(jobs)

    assert len(collection.events) == 27
    records = collection.to_records()
    expected_keys = {
        "timestamp",
        "modality",
        "source",
        "signal_type",
        "value",
        "unit",
        "contextual_metadata",
    }
    assert all(set(record.keys()) == expected_keys for record in records)
    assert records == sorted(
        records,
        key=lambda record: (
            _parse_timestamp(record["timestamp"]),
            record["modality"],
            record["source"],
            record["signal_type"],
        ),
    )
    report = collection.validate()
    assert report.is_valid
    assert report.error_count == 0
    assert report.warning_count == 0
    assert len(report.stream_summaries) >= 6


def test_marker_segmentation_creates_temporal_windows() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / "examples" / "data" / "eeg_direct.json", ROOT / "examples" / "configs" / "eeg_direct.json")

    segments = collection.segment_around_markers(marker_signal_types=["marker"], pre_seconds=0.25, post_seconds=0.25)
    assert len(segments) == 2
    assert segments[0].label == "odor_onset"
    assert segments[0].events
    assert any(event.event_kind == "marker" for event in segments[0].events)
    assert any(event.event_kind == "sample" for event in segments[0].events)


def test_serialized_events_can_be_loaded_back_into_tsel() -> None:
    pipeline = TSELPipeline()
    output_path = OUTPUT / "roundtrip-demo.jsonl"
    batch = pipeline.ingest_many(pipeline.load_manifest(ROOT / "examples" / "configs" / "demo_manifest.json"))
    output_path.write_text("\n".join(json.dumps(record) for record in batch.to_records()) + "\n", encoding="utf-8")

    loaded = load_events(output_path)
    assert len(loaded.events) == 27
    assert loaded.validate().is_valid


def test_cli_batch_writes_jsonl() -> None:
    output_path = ROOT / "output" / "pytest-demo.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tsel.cli",
            "batch",
            str(ROOT / "examples" / "configs" / "demo_manifest.json"),
            str(output_path),
            "--format",
            "jsonl",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 27
    assert "Events: 27" in result.stdout
    first_record = json.loads(lines[0])
    assert first_record["timestamp"] == "2026-03-15T14:00:00Z"


def test_cli_validate_reports_valid_temporal_layer() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tsel.cli",
            "validate",
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
    assert payload["is_valid"] is True
    assert payload["error_count"] == 0


def test_cli_segment_writes_marker_windows() -> None:
    output_path = ROOT / "output" / "marker-segments.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tsel.cli",
            "segment",
            str(ROOT / "examples" / "data" / "eeg_direct.json"),
            str(output_path),
            "--config",
            str(ROOT / "examples" / "configs" / "eeg_direct.json"),
            "--marker-signal",
            "marker",
            "--pre-seconds",
            "0.25",
            "--post-seconds",
            "0.25",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert "Wrote 2 temporal segments" in result.stdout
def test_pipeline_accepts_explicit_sensory_profile_switch() -> None:
    pipeline = TSELPipeline()

    collection = pipeline.ingest(
        ROOT / "examples" / "data" / "eeg_direct.json",
        ROOT / "examples" / "configs" / "eeg_direct.json",
        sensory_profile="eeg",
    )

    assert len(collection.events) == 10


def test_pipeline_rejects_incompatible_sensory_profile_switch() -> None:
    pipeline = TSELPipeline()

    with pytest.raises(ValueError, match="sensory profile 'olfaction'"):
        pipeline.ingest(
            ROOT / "examples" / "data" / "environment_events.json",
            ROOT / "examples" / "configs" / "environment.json",
            sensory_profile="olfaction",
        )


def test_timeseries_json_without_start_time_uses_relative_sequence_fallback() -> None:
    payload = {
        "sample_rate_hz": 2,
        "source": "VISION-REL-01",
        "channels": {
            "vision_signal": [0.2, 0.6, 0.4],
        },
        "annotations": [
            {"offset_samples": 1, "label": "stimulus_onset", "marker_type": "stimulus"},
        ],
    }
    input_path = OUTPUT / "pytest-vision-relative.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "multisensory")
    records = collection.to_records()

    assert records[0]["timestamp"] == "1970-01-01T00:00:00Z"
    assert records[1]["timestamp"] == "1970-01-01T00:00:00.500000Z"
    assert records[0]["contextual_metadata"]["completeness"]["missing_dimensions"] == ["absolute_time"]
    assert records[0]["contextual_metadata"]["temporal"]["resolution_seconds"] == 0.5
    marker = next(record for record in records if record["signal_type"] == "marker")
    assert marker["timestamp"] == "1970-01-01T00:00:00.500000Z"


def test_ingest_auto_directory_merges_packet_inputs() -> None:
    packet_dir = OUTPUT / 'pytest-auto-packet'
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / 'vision_episode.json').write_text((ROOT / 'examples' / 'data' / 'vision_episode.json').read_text(encoding='utf-8'), encoding='utf-8')
    (packet_dir / 'vision_sequence.csv').write_text(
        "source,subject_id,sample_rate_hz,vision_signal,auditory_signal\n"
        + "SESSION-02,SUB-09,4,0.1,0.2\n"
        + "SESSION-02,SUB-09,4,0.3,0.4\n",
        encoding='utf-8',
    )

    pipeline = TSELPipeline()
    plans = pipeline.plan_auto_packet(packet_dir, 'multisensory')
    collection = pipeline.ingest_auto(packet_dir, 'multisensory')
    summary = collection.summary()

    assert len(plans) == 2
    assert len(collection.events) > 4
    assert 'multisensory' in summary['modalities']
    assert summary['experience_count'] >= 1
