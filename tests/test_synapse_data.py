from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from tsel.pipeline import TSELPipeline


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "external_data" / "raw"
SYNAPSE_RAW = RAW / "dream_synapse"
CURATED = ROOT / "external_data" / "curated"
CONFIGS = ROOT / "external_data" / "configs"

SYNAPSE_REQUIRED_RAW = [
    SYNAPSE_RAW / "CID_leaderboard.txt",
    SYNAPSE_RAW / "CID_testset.txt",
    SYNAPSE_RAW / "dilution_leaderboard.txt",
    SYNAPSE_RAW / "dilution_testset.txt",
    SYNAPSE_RAW / "LBs1.txt",
    SYNAPSE_RAW / "LBs2.txt",
    SYNAPSE_RAW / "leaderboard_set.txt",
    SYNAPSE_RAW / "molecular_descriptors_data.txt",
    SYNAPSE_RAW / "TrainSet.txt",
]

FULL_MANIFEST_REQUIRED_RAW = [
    RAW / "dream_reports.csv",
    RAW / "gas_sensor_array_drift" / "Dataset" / "batch1.dat",
    RAW / "SC4401E0-PSG.edf",
    RAW / "SC4401EC-Hypnogram.edf",
]

TRAIN_METADATA_COLUMNS = {
    "timestamp",
    "subject_id",
    "compound_id",
    "odor_name",
    "replicate_label",
    "intensity_label",
    "dilution",
}


@pytest.fixture(scope="module", autouse=True)
def prepare_synapse_data() -> None:
    missing = [path for path in SYNAPSE_REQUIRED_RAW if not path.exists()]
    if missing:
        pytest.skip(f"Synapse raw data is missing: {missing}")
    subprocess.run([sys.executable, str(ROOT / "tools" / "import_synapse_dream_data.py")], cwd=ROOT, check=True)


def _count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle, delimiter="\t"))


def _count_non_empty_channel_values(path: Path, *, metadata_columns: set[str]) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            return 0
        channel_columns = [field for field in reader.fieldnames if field not in metadata_columns]
        count = 0
        for row in reader:
            count += sum(1 for field in channel_columns if row.get(field, "") not in {"", None})
        return count


def test_synapse_train_sample_ingests() -> None:
    pipeline = TSELPipeline()
    input_path = CURATED / "dream_synapse_train_sample.tsv"
    collection = pipeline.ingest(input_path, CONFIGS / "source_dream_synapse_train.json")

    assert len(collection.events) == _count_non_empty_channel_values(input_path, metadata_columns=TRAIN_METADATA_COLUMNS)
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "olfaction_perception"
    assert first["source"].startswith("synapse-subject-")
    assert first["contextual_metadata"]["odor_name"]
    assert first["contextual_metadata"]["challenge_partition"] == "train"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "sample"


def test_synapse_leaderboard_individual_sample_ingests() -> None:
    pipeline = TSELPipeline()
    input_path = CURATED / "dream_synapse_leaderboard_individual_sample.tsv"
    collection = pipeline.ingest(input_path, CONFIGS / "source_dream_synapse_individual.json")

    assert len(collection.events) == _count_rows(input_path)
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "olfaction_perception"
    assert first["contextual_metadata"]["challenge_split"] == "leaderboard_set"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "observation"


def test_synapse_lbs1_individual_sample_ingests() -> None:
    pipeline = TSELPipeline()
    input_path = CURATED / "dream_synapse_lbs1_individual_sample.tsv"
    collection = pipeline.ingest(input_path, CONFIGS / "source_dream_synapse_individual.json")

    assert len(collection.events) == _count_rows(input_path)
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["contextual_metadata"]["challenge_split"] == "LBs1"
    assert first["signal_type"] == "INTENSITY/STRENGTH"


def test_synapse_aggregate_sample_ingests() -> None:
    pipeline = TSELPipeline()
    input_path = CURATED / "dream_synapse_lbs2_aggregate_sample.tsv"
    collection = pipeline.ingest(input_path, CONFIGS / "source_dream_synapse_aggregate.json")

    assert len(collection.events) == _count_rows(input_path)
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "olfaction_aggregate"
    assert first["contextual_metadata"]["sigma"]
    assert first["contextual_metadata"]["challenge_split"] == "LBs2"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "observation"


def test_synapse_molecular_sample_ingests() -> None:
    pipeline = TSELPipeline()
    input_path = CURATED / "dream_synapse_molecular_sample.tsv"
    collection = pipeline.ingest(input_path, CONFIGS / "source_dream_synapse_molecular.json")

    assert len(collection.events) == _count_non_empty_channel_values(input_path, metadata_columns={"timestamp", "compound_id"})
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "molecular_descriptor"
    assert first["contextual_metadata"]["challenge_partition"] == "molecular_descriptors"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "sample"
    assert first["contextual_metadata"]["temporal"]["resolution_seconds"] == 1.0


def test_synapse_split_registry_ingests() -> None:
    pipeline = TSELPipeline()
    input_path = CURATED / "dream_synapse_split_registry.tsv"
    collection = pipeline.ingest(input_path, CONFIGS / "source_dream_synapse_split_registry.json")

    assert len(collection.events) == _count_rows(input_path)
    report = collection.validate()
    assert report.is_valid
    first = collection.to_records()[0]
    assert first["modality"] == "olfaction_challenge_split"
    assert first["signal_type"] == "challenge_membership"
    assert first["contextual_metadata"]["temporal"]["event_kind"] == "marker"
    assert {record["value"] for record in collection.to_records()} == {"leaderboard", "test"}


def test_synapse_manifest_validates() -> None:
    pipeline = TSELPipeline()
    jobs = pipeline.load_manifest(CONFIGS / "source_synapse_manifest.json")
    collection = pipeline.ingest_many(jobs)

    report = collection.validate()
    summary = collection.summary()
    assert report.is_valid
    assert {"olfaction_perception", "olfaction_aggregate", "molecular_descriptor", "olfaction_challenge_split"}.issubset(set(summary["modalities"]))
    assert {"sample", "observation", "marker"}.issubset(set(summary["event_kinds"]))
    assert summary["event_count"] >= 10000


def test_full_manifest_validates_with_synapse_and_eeg_dream_sources() -> None:
    missing = [path for path in FULL_MANIFEST_REQUIRED_RAW if not path.exists()]
    if missing:
        pytest.skip(f"full sourced raw data is missing: {missing}")

    subprocess.run([sys.executable, str(ROOT / "tools" / "prepare_sourced_data.py")], cwd=ROOT, check=True)
    pipeline = TSELPipeline()
    jobs = pipeline.load_manifest(CONFIGS / "source_full_manifest.json")
    collection = pipeline.ingest_many(jobs)

    report = collection.validate()
    summary = collection.summary()
    assert report.is_valid
    assert {
        "dream",
        "eeg",
        "sleep_stage",
        "olfaction",
        "olfaction_perception",
        "olfaction_aggregate",
        "olfaction_challenge_split",
        "molecular_descriptor",
    }.issubset(set(summary["modalities"]))
    assert {"sample", "observation", "report", "marker"}.issubset(set(summary["event_kinds"]))
    assert summary["event_count"] >= 13000
