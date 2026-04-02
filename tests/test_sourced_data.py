from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tsel.pipeline import TSELPipeline


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "external_data" / "raw"
CURATED = ROOT / "external_data" / "curated"
CONFIGS = ROOT / "external_data" / "configs"


REQUIRED_RAW = [
    RAW / "dream_reports.csv",
    RAW / "gas_sensor_array_drift" / "Dataset" / "batch1.dat",
    RAW / "SC4401E0-PSG.edf",
    RAW / "SC4401EC-Hypnogram.edf",
]


@pytest.fixture(scope="module", autouse=True)
def prepare_sourced_data() -> None:
    missing = [path for path in REQUIRED_RAW if not path.exists()]
    if missing:
        pytest.skip(f"sourced raw data is missing: {missing}")
    subprocess.run([sys.executable, str(ROOT / "tools" / "prepare_sourced_data.py")], cwd=ROOT, check=True)


def test_real_olfactory_source_ingests() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(CURATED / "olfactory_gas_batch1_sample.csv", CONFIGS / "source_olfactory_gas.json")

    assert len(collection.events) == 8 * 128
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "olfaction"
    assert first["contextual_metadata"]["gas_class"] == "ethanol"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "sample"
    assert first["contextual_metadata"]["temporal"]["resolution_seconds"] == 1.0


def test_real_dream_source_ingests() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(CURATED / "dream_reports_sample.csv", CONFIGS / "source_dream_reports.json")

    assert len(collection.events) == 12
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "dream"
    assert first["signal_type"] == "dream_report"
    assert first["unit"] == "text"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "report"
    assert first["contextual_metadata"]["survey_name"]


def test_real_sleep_edf_source_ingests_bounded_window() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(RAW / "SC4401E0-PSG.edf", CONFIGS / "source_sleep_edf.json")

    assert len(collection.events) == 2000
    report = collection.validate()
    assert report.is_valid
    channels = {record["contextual_metadata"]["channel"] for record in collection.to_records()}
    assert channels == {"EEG Fpz-Cz", "EEG Pz-Oz"}
    first = collection.to_records()[0]
    assert first["modality"] == "eeg"
    assert first["contextual_metadata"]["temporal"]["resolution_seconds"] == 0.01


def test_real_sleep_hypnogram_source_ingests_stage_markers() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(RAW / "SC4401EC-Hypnogram.edf", CONFIGS / "source_sleep_hypnogram.json")

    assert len(collection.events) >= 3
    report = collection.validate()
    assert report.is_valid
    assert all(event.event_kind == "marker" for event in collection.events)
    first = collection.to_records()[0]
    assert first["modality"] == "sleep_stage"
    assert first["unit"] == "stage"


def test_real_source_manifest_validates() -> None:
    pipeline = TSELPipeline()
    jobs = pipeline.load_manifest(CONFIGS / "source_manifest.json")
    collection = pipeline.ingest_many(jobs)

    report = collection.validate()
    summary = collection.summary()
    assert report.is_valid
    assert {"olfaction", "dream", "eeg", "sleep_stage"}.issubset(set(summary["modalities"]))
    assert {"sample", "marker", "report"}.issubset(set(summary["event_kinds"]))
    assert summary["event_count"] >= 3036
