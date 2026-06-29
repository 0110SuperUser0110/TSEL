from __future__ import annotations

from pathlib import Path

from tsel.autorouting import build_auto_ingest_plan
from tsel.pipeline import TSELPipeline


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "external_data"
CANONICAL_TOP_LEVEL_FIELDS = {
    "timestamp",
    "modality",
    "source",
    "signal_type",
    "value",
    "unit",
    "contextual_metadata",
}


def test_supported_sensory_profiles_remain_broader_than_eeg() -> None:
    profiles = set(TSELPipeline().supported_sensory_profiles())

    assert {"generic", "dream", "environment", "multisensory", "olfaction", "eeg"} <= profiles


def test_explicit_dream_ingest_attaches_shared_domain_profile_context() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(
        EXTERNAL / "curated" / "dream_reports_sample.csv",
        EXTERNAL / "configs" / "source_dream_reports.json",
    )

    first = collection.to_records()[0]
    assert set(first.keys()) == CANONICAL_TOP_LEVEL_FIELDS
    assert first["modality"] == "dream"
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "dream_report_profile"
    assert first["contextual_metadata"]["acquisition"]["acquisition_profile"] == "dream"


def test_explicit_environment_ingest_attaches_shared_domain_profile_context() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(
        ROOT / "examples" / "data" / "environment_events.json",
        ROOT / "examples" / "configs" / "environment.json",
    )

    first = collection.to_records()[0]
    assert set(first.keys()) == CANONICAL_TOP_LEVEL_FIELDS
    assert first["modality"] == "environment"
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "environment_observation_profile"
    assert first["contextual_metadata"]["acquisition"]["acquisition_profile"] == "environment"


def test_explicit_multisensory_ingest_attaches_shared_domain_profile_context() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(
        ROOT / "examples" / "data" / "multisensory_matrix.csv",
        ROOT / "examples" / "configs" / "multisensory_matrix.json",
    )

    first = collection.to_records()[0]
    assert set(first.keys()) == CANONICAL_TOP_LEVEL_FIELDS
    assert first["modality"] == "multisensory"
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "multisensory_stream_profile"
    assert first["contextual_metadata"]["acquisition"]["acquisition_profile"] == "multisensory"


def test_auto_multisensory_episode_keeps_non_eeg_profile_identity() -> None:
    plan = build_auto_ingest_plan(ROOT / "examples" / "data" / "vision_episode.json", "multisensory")
    pipeline = TSELPipeline()
    collection = pipeline.ingest_auto(ROOT / "examples" / "data" / "vision_episode.json", "multisensory")

    first = collection.to_records()[0]
    assert plan.adapter == "timeseries_json"
    assert first["modality"] == "multisensory"
    assert first["contextual_metadata"]["domain_profile"]["profile_id"] == "multisensory_stream_profile"
    assert first["contextual_metadata"]["acquisition"]["acquisition_profile"] == "multisensory"


def test_auto_environment_stream_plan_does_not_depend_on_eeg_profile_logic() -> None:
    plan = build_auto_ingest_plan(ROOT / "examples" / "data" / "environment_events.json", "environment")

    assert plan.adapter == "json"
    static_context = plan.config["mapping"]["context"]["static"]
    assert static_context["domain_profile"]["profile_id"] == "environment_observation_profile"
    assert static_context["acquisition"]["acquisition_profile"] == "environment"
