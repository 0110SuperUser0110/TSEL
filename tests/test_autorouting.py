from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tsel.autorouting import build_auto_ingest_plan, looks_like_normalized_tsel
from tsel.pipeline import TSELPipeline
from tsel.serializers import write_events


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "external_data" / "curated"


def test_auto_route_eeg_json_ingests_without_manual_config() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(ROOT / "examples" / "data" / "eeg_direct.json", "eeg")

    assert len(collection.events) == 10
    assert collection.to_records()[0]["modality"] == "eeg"


def test_auto_route_multisensory_csv_ingests_without_manual_config() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(ROOT / "examples" / "data" / "multisensory_matrix.csv", "multisensory")

    assert len(collection.events) == 6
    first = collection.to_records()[0]
    assert first["modality"] == "multisensory"
    assert first["contextual_metadata"]["subject_id"] == "SUB-01"


def test_auto_route_dream_table_uses_report_semantics() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(EXTERNAL / "dream_reports_sample.csv", "dream")

    assert len(collection.events) >= 2
    first = collection.to_records()[0]
    assert first["modality"] == "dream"
    assert first["unit"] == "text"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "report"


def test_auto_route_plan_describes_olfaction_matrix() -> None:
    plan = build_auto_ingest_plan(EXTERNAL / "dream_synapse_train_sample.tsv", "olfaction")

    assert plan.adapter == "timeseries_csv"
    assert plan.config["modality"]["value"] == "olfaction_perception"


def test_pipeline_ingest_file_prefers_normalized_when_present() -> None:
    pipeline = TSELPipeline()
    normalized_path = ROOT / "output" / "demo.bundle.json"

    assert looks_like_normalized_tsel(normalized_path)
    collection = pipeline.ingest_file(normalized_path)

    assert len(collection.events) == 27
def test_cli_auto_ingest_builds_temporal_layer_from_profile() -> None:
    output_path = ROOT / "output" / "pytest-auto-eeg.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tsel.cli",
            "auto-ingest",
            str(ROOT / "examples" / "data" / "eeg_direct.json"),
            "eeg",
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
    assert len(lines) == 10
    first = json.loads(lines[0])
    assert first["modality"] == "eeg"
    assert "Events: 10" in result.stdout


def test_auto_route_multisensory_csv_without_timestamp_uses_sequence_timing() -> None:
    input_path = ROOT / "output" / "pytest-sequence-multisensory.csv"
    input_path.write_text(
        "source,subject_id,sample_rate_hz,vision_signal,auditory_signal\n"
        + "SESSION-02,SUB-09,4,0.1,0.2\n"
        + "SESSION-02,SUB-09,4,0.3,0.4\n",
        encoding="utf-8",
    )

    plan = build_auto_ingest_plan(input_path, "multisensory")

    assert plan.adapter == "timeseries_csv"
    assert plan.config["timestamp"]["column"] == "__tsel_sequence_index"
    assert plan.config["timestamp"]["unit"] == "samples"
    completeness = plan.config["context"]["static"]["completeness"]
    assert completeness["observation_status"] == "partial"
    assert completeness["missing_dimensions"] == ["absolute_time"]

    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(input_path, "multisensory")

    records = collection.to_records()
    assert len(records) == 4
    assert records[0]["timestamp"] == "1970-01-01T00:00:00Z"
    assert records[2]["timestamp"] == "1970-01-01T00:00:00.250000Z"
    assert records[0]["contextual_metadata"]["completeness"]["missing_dimensions"] == ["absolute_time"]
    assert records[0]["contextual_metadata"]["temporal"]["resolution_seconds"] == 0.25