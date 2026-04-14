from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .autorouting import AutoIngestPlan, build_auto_ingest_plan
from .eeg_profiles import resolve_eeg_packet_profile
from .olfactory_profiles import merge_domain_profile_into_config, resolve_olfactory_packet_profile


ROOT = Path(__file__).resolve().parents[1]
PACKET_CACHE_ROOT = ROOT / "output" / "_packet_cache"

_SYNAPSE_REQUIRED_FILES = (
    "CID_leaderboard.txt",
    "CID_testset.txt",
    "dilution_leaderboard.txt",
    "dilution_testset.txt",
    "LBs1.txt",
    "LBs2.txt",
    "leaderboard_set.txt",
    "molecular_descriptors_data.txt",
    "TrainSet.txt",
)
_SYNAPSE_OPTIONAL_FILES = ("train_set.mat",)
_EEG_PACKET_MANIFEST = "packet_manifest.json"


def detect_special_packet_type(input_path: str | Path) -> str | None:
    path = Path(input_path)
    if not path.is_dir():
        return None
    manifest = _load_packet_manifest(path)
    if isinstance(manifest, dict) and str(manifest.get("packet_type") or "").strip() == "eeg_session":
        return "eeg_session"
    members = {child.name for child in path.iterdir() if child.is_file()}
    if all(name in members for name in _SYNAPSE_REQUIRED_FILES):
        return "dream_synapse"
    return None


def describe_special_packet(input_path: str | Path) -> dict[str, Any] | None:
    path = Path(input_path)
    packet_type = detect_special_packet_type(path)
    if packet_type == "eeg_session":
        manifest = _load_packet_manifest(path) or {}
        members = []
        for raw_member in manifest.get("members", []):
            if not isinstance(raw_member, dict):
                continue
            member_path = path / str(raw_member.get("path", ""))
            members.append(
                {
                    "path": str(raw_member.get("path", "")),
                    "profile": str(raw_member.get("profile") or "eeg"),
                    "status": "packet member" if member_path.exists() else "missing packet member",
                    "size_bytes": member_path.stat().st_size if member_path.exists() else None,
                }
            )
        return {
            "format": "packet",
            "packet_type": packet_type,
            "root": str(path.resolve()),
            "file_count": len(members),
            "preview_files": members,
            "session_id": manifest.get("session_id"),
            "trial_id": manifest.get("trial_id"),
        }
    if packet_type != "dream_synapse":
        return None

    files = []
    for name in (*_SYNAPSE_REQUIRED_FILES, *_SYNAPSE_OPTIONAL_FILES):
        member = path / name
        if not member.exists():
            continue
        files.append(
            {
                "path": name,
                "profile": "olfaction",
                "status": "packet member" if name in _SYNAPSE_REQUIRED_FILES else "provenance artifact",
                "size_bytes": member.stat().st_size,
            }
        )

    return {
        "format": "packet",
        "packet_type": packet_type,
        "root": str(path.resolve()),
        "file_count": len(files),
        "preview_files": files,
    }


def plan_special_packet(input_path: str | Path, requested_profile: str) -> list[AutoIngestPlan] | None:
    path = Path(input_path)
    packet_type = detect_special_packet_type(path)
    if packet_type == "eeg_session":
        if requested_profile not in {"generic", "eeg"}:
            raise ValueError("This raw packet is EEG session data. Use the internal EEG acquisition route when ingesting it programmatically.")
        manifest = _load_packet_manifest(path)
        if not isinstance(manifest, dict):
            raise ValueError("EEG packet manifest could not be read.")
        resolution = resolve_eeg_packet_profile(packet_type)
        packet_context = _eeg_packet_context(manifest, resolution)
        plans: list[AutoIngestPlan] = []
        for raw_member in manifest.get("members", []):
            if not isinstance(raw_member, dict):
                continue
            relative_member = str(raw_member.get("path") or "").strip()
            if not relative_member:
                continue
            member_path = (path / relative_member).resolve()
            if not member_path.exists() or not member_path.is_file():
                raise ValueError(f"EEG packet member not found: {relative_member}")
            member_profile = str(raw_member.get("profile") or "eeg").strip() or "eeg"
            base_plan = build_auto_ingest_plan(member_path, member_profile)
            config = _merge_packet_static_context(base_plan.config, packet_context)
            plans.append(
                AutoIngestPlan(
                    input_path=base_plan.input_path,
                    sensory_profile="eeg",
                    adapter=base_plan.adapter,
                    rationale=f"{base_plan.rationale} Member of an explicit EEG session packet.",
                    config=config,
                    detected_format="packet_member",
                )
            )
        if not plans:
            raise ValueError("EEG packet manifest does not declare any usable members.")
        return plans
    if packet_type != "dream_synapse":
        return None
    if requested_profile not in {"generic", "olfaction"}:
        raise ValueError("This raw packet is olfactory challenge data. Select Smell / olfaction.")

    cache_dir = _packet_cache_dir(path, packet_type)
    cache_dir.mkdir(parents=True, exist_ok=True)
    derived_files = _build_synapse_packet_files(path, cache_dir)
    resolution = resolve_olfactory_packet_profile(packet_type)
    config = merge_domain_profile_into_config(_packet_json_config(), resolution)

    return [
        AutoIngestPlan(
            input_path=derived_path,
            sensory_profile="olfaction",
            adapter="json",
            rationale=rationale,
            config=config,
            detected_format="packet_jsonl",
        )
        for derived_path, rationale in derived_files
    ]


def _packet_cache_dir(packet_dir: Path, packet_type: str) -> Path:
    digest = hashlib.sha1(str(packet_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    return PACKET_CACHE_ROOT / packet_type / digest


def _load_packet_manifest(path: Path) -> dict[str, Any] | None:
    manifest_path = path / _EEG_PACKET_MANIFEST
    if not manifest_path.exists() or not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None



def _eeg_packet_context(manifest: dict[str, Any], resolution) -> dict[str, Any]:
    session_id = str(manifest.get("session_id") or "").strip()
    trial_id = str(manifest.get("trial_id") or "").strip()
    dataset = str(manifest.get("dataset") or "").strip()
    context: dict[str, Any] = {
        "ingest_mode": "packet_profile",
        "packet_profile": "eeg_session",
        "packet_profile_id": getattr(resolution, "profile_id", None),
        "packet_resolution_status": getattr(resolution, "resolution_status", None),
        "temporal_layer": "unified",
        "assertion_basis": {
            "packet_profile": "packet_declared",
            "packet_profile_id": "packet_declared",
            "packet_resolution_status": "packet_declared",
        },
    }
    alignment: dict[str, Any] = {}
    if session_id:
        alignment["session_id"] = session_id
        context["assertion_basis"]["alignment.session_id"] = "packet_declared"
    if trial_id:
        alignment["trial_id"] = trial_id
        context["assertion_basis"]["alignment.trial_id"] = "packet_declared"
    if alignment:
        context["alignment"] = alignment
    if dataset:
        context["dataset"] = dataset
        context["assertion_basis"]["dataset"] = "packet_declared"
    return context



def _merge_packet_static_context(config: dict[str, Any], packet_context: dict[str, Any]) -> dict[str, Any]:
    merged = dict(config)
    adapter = str(merged.get("adapter", ""))
    if adapter in {"csv", "json"}:
        mapping = dict(merged.get("mapping", {}))
        context = dict(mapping.get("context", {}))
        static = dict(context.get("static", {}))
        context["static"] = _merge_nested(static, packet_context)
        mapping["context"] = context
        merged["mapping"] = mapping
        return merged
    if adapter == "timeseries_csv":
        context = dict(merged.get("context", {}))
        static = dict(context.get("static", {}))
        context["static"] = _merge_nested(static, packet_context)
        merged["context"] = context
        return merged
    if adapter in {"timeseries_json", "edf"}:
        merged["context"] = _merge_nested(dict(merged.get("context", {})), packet_context)
        return merged
    return merged



def _merge_nested(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _packet_json_config() -> dict[str, Any]:
    return {
        "adapter": "json",
        "mapping": {
            "timestamp": {"column": "timestamp"},
            "modality": {"column": "modality"},
            "source": {"column": "source"},
            "signal_type": {"column": "signal_type"},
            "value": {"column": "value"},
            "unit": {"column": "unit"},
            "context": {
                "capture_remaining": True,
                "static": {
                    "dataset": "DREAM Olfaction Prediction Challenge",
                    "packet_profile": "dream_synapse",
                    "ingest_mode": "packet_profile",
                    "sensory_profile": "olfaction",
                    "temporal_layer": "unified",
                    "alignment": {"session_id": "dream_synapse"},
                    "completeness": {
                        "observation_status": "partial",
                        "missing_dimensions": ["absolute_time"],
                        "future_inference_allowed": True,
                    },
                    "sensory": {"primary_sense": "olfaction"},
                    "acquisition": {
                        "transform_stage": "normalized",
                    },
                },
            },
            "temporal": {
                "event_kind": {"column": "event_kind"},
                "stream_id": {"column": "stream_id"},
                "sequence_index": {"column": "sequence_index", "cast": "int"},
                "time_scale": {"value": "second"},
            },
        },
    }


def _build_synapse_packet_files(raw_dir: Path, cache_dir: Path) -> list[tuple[Path, str]]:
    derived_files: list[tuple[Path, str]] = []

    train_path = cache_dir / "synapse_train_profiles.jsonl"
    _write_jsonl(train_path, _iter_train_records(raw_dir / "TrainSet.txt"))
    derived_files.append((train_path, "Prepared train-set olfactory perception profiles from the raw DREAM Synapse packet."))

    leaderboard_path = cache_dir / "synapse_leaderboard_individual.jsonl"
    _write_jsonl(
        leaderboard_path,
        _iter_individual_records(raw_dir / "leaderboard_set.txt", split_name="leaderboard_set", origin=datetime(2015, 6, 2, tzinfo=timezone.utc)),
    )
    derived_files.append((leaderboard_path, "Prepared leaderboard individual olfactory observations from the raw DREAM Synapse packet."))

    lbs1_path = cache_dir / "synapse_lbs1_individual.jsonl"
    _write_jsonl(
        lbs1_path,
        _iter_individual_records(raw_dir / "LBs1.txt", split_name="LBs1", origin=datetime(2015, 6, 3, tzinfo=timezone.utc)),
    )
    derived_files.append((lbs1_path, "Prepared LBs1 individual olfactory observations from the raw DREAM Synapse packet."))

    aggregate_path = cache_dir / "synapse_lbs2_aggregate.jsonl"
    _write_jsonl(aggregate_path, _iter_aggregate_records(raw_dir / "LBs2.txt"))
    derived_files.append((aggregate_path, "Prepared LBs2 aggregate olfactory observations from the raw DREAM Synapse packet."))

    molecular_path = cache_dir / "synapse_molecular_vectors.jsonl"
    _write_jsonl(molecular_path, _iter_molecular_records(raw_dir / "molecular_descriptors_data.txt"))
    derived_files.append((molecular_path, "Prepared compact molecular descriptor vectors from the raw DREAM Synapse packet."))

    split_path = cache_dir / "synapse_split_registry.jsonl"
    _write_jsonl(
        split_path,
        _iter_split_registry_records(
            raw_dir / "CID_leaderboard.txt",
            raw_dir / "CID_testset.txt",
            raw_dir / "dilution_leaderboard.txt",
            raw_dir / "dilution_testset.txt",
        ),
    )
    derived_files.append((split_path, "Prepared challenge split membership markers from the raw DREAM Synapse packet."))

    return derived_files


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True))
            handle.write("\n")


def _iter_train_records(path: Path) -> list[dict[str, Any]]:
    origin = datetime(2015, 6, 1, tzinfo=timezone.utc)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError("TrainSet.txt does not contain a header row")
        descriptor_columns = [
            field
            for field in reader.fieldnames
            if field not in {"Compound Identifier", "Odor", "Replicate", "Intensity", "Dilution", "subject #"}
        ]
        for sequence_index, row in enumerate(reader):
            profile = {
                column: numeric_value
                for column in descriptor_columns
                if (numeric_value := _clean_numeric_value(row.get(column))) is not None
            }
            subject_id = _clean_text(row.get("subject #")) or "unknown"
            source = f"synapse-subject-{subject_id}"
            records.append(
                {
                    "timestamp": _iso_timestamp(origin, sequence_index),
                    "modality": "olfaction_perception",
                    "source": source,
                    "signal_type": "perception_profile",
                    "value": profile,
                    "unit": "rating_vector",
                    "event_kind": "observation",
                    "sequence_index": sequence_index,
                    "stream_id": source,
                    "source_table": path.name,
                    "challenge_partition": "train",
                    "compound_id": _clean_text(row.get("Compound Identifier")),
                    "odor_name": _clean_text(row.get("Odor")),
                    "replicate_label": _clean_text(row.get("Replicate")),
                    "intensity_label": _clean_text(row.get("Intensity")),
                    "dilution": _clean_text(row.get("Dilution")),
                    "vector_dimensions": len(profile),
                }
            )
    return records


def _iter_individual_records(path: Path, *, split_name: str, origin: datetime) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for sequence_index, row in enumerate(reader):
            compound_key = "#oID" if "#oID" in row else "oID"
            individual = _clean_text(row.get("individual")) or "unknown"
            source = f"synapse-individual-{individual}"
            records.append(
                {
                    "timestamp": _iso_timestamp(origin, sequence_index),
                    "modality": "olfaction_perception",
                    "source": source,
                    "signal_type": _clean_text(row.get("descriptor")) or "descriptor",
                    "value": _clean_numeric_value(row.get("value")),
                    "unit": "rating",
                    "event_kind": "observation",
                    "sequence_index": sequence_index,
                    "stream_id": source,
                    "source_table": path.name,
                    "challenge_split": split_name,
                    "compound_id": _clean_text(row.get(compound_key)),
                }
            )
    return records


def _iter_aggregate_records(path: Path) -> list[dict[str, Any]]:
    origin = datetime(2015, 6, 4, tzinfo=timezone.utc)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for sequence_index, row in enumerate(reader):
            compound_key = "#oID" if "#oID" in row else "oID"
            compound_id = _clean_text(row.get(compound_key)) or "unknown"
            records.append(
                {
                    "timestamp": _iso_timestamp(origin, sequence_index),
                    "modality": "olfaction_aggregate",
                    "source": compound_id,
                    "signal_type": _clean_text(row.get("descriptor")) or "descriptor",
                    "value": _clean_numeric_value(row.get("value")),
                    "unit": "rating",
                    "event_kind": "observation",
                    "sequence_index": sequence_index,
                    "stream_id": compound_id,
                    "source_table": path.name,
                    "challenge_split": "LBs2",
                    "sigma": _clean_numeric_value(row.get("sigma")),
                    "compound_id": compound_id,
                }
            )
    return records


def _iter_molecular_records(path: Path) -> list[dict[str, Any]]:
    origin = datetime(2015, 6, 5, tzinfo=timezone.utc)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        if header is None:
            raise ValueError("molecular_descriptors_data.txt does not contain a header row")
        descriptor_columns = _make_unique_columns(header[1:])
        for sequence_index, row in enumerate(reader):
            compound_id = _clean_text(row[0]) or f"compound-{sequence_index}"
            descriptors = {
                column: numeric_value
                for column, value in zip(descriptor_columns, row[1:])
                if (numeric_value := _clean_numeric_value(value)) is not None
            }
            records.append(
                {
                    "timestamp": _iso_timestamp(origin, sequence_index),
                    "modality": "molecular_descriptor",
                    "source": compound_id,
                    "signal_type": "descriptor_vector",
                    "value": descriptors,
                    "unit": "a.u._vector",
                    "event_kind": "observation",
                    "sequence_index": sequence_index,
                    "stream_id": compound_id,
                    "source_table": path.name,
                    "challenge_partition": "molecular_descriptors",
                    "compound_id": compound_id,
                    "vector_dimensions": len(descriptors),
                    "duplicate_header_resolved": True,
                }
            )
    return records


def _iter_split_registry_records(
    cid_leaderboard_path: Path,
    cid_test_path: Path,
    dilution_leaderboard_path: Path,
    dilution_test_path: Path,
) -> list[dict[str, Any]]:
    origin = datetime(2015, 6, 6, tzinfo=timezone.utc)
    records: list[dict[str, Any]] = []
    for partition, cid_path, dilution_path in (
        ("leaderboard", cid_leaderboard_path, dilution_leaderboard_path),
        ("test", cid_test_path, dilution_test_path),
    ):
        dilution_map = _read_dilution_map(dilution_path)
        for compound_id in _read_id_list(cid_path):
            records.append(
                {
                    "timestamp": _iso_timestamp(origin, len(records)),
                    "modality": "olfaction_challenge_split",
                    "source": compound_id,
                    "signal_type": "challenge_membership",
                    "value": partition,
                    "unit": "label",
                    "event_kind": "marker",
                    "sequence_index": len(records),
                    "stream_id": compound_id,
                    "source_table": cid_path.name,
                    "challenge_partition": partition,
                    "dilution": dilution_map.get(compound_id, ""),
                    "compound_id": compound_id,
                }
            )
    return records


def _read_id_list(path: Path) -> list[str]:
    values: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            value = _clean_text(line)
            if not value or value.lower() in {"oid", "cid", "#oid"}:
                continue
            values.append(value)
    return values


def _read_dilution_map(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        compound_key = "oID" if reader.fieldnames and "oID" in reader.fieldnames else "#oID"
        for row in reader:
            mapping[_clean_text(row.get(compound_key))] = _clean_text(row.get("dilution"))
    return mapping


def _make_unique_columns(columns: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    unique: list[str] = []
    for column in columns:
        name = _clean_text(column) or "unnamed"
        counts[name] = counts.get(name, 0) + 1
        if counts[name] == 1:
            unique.append(name)
        else:
            unique.append(f"{name}__{counts[name]}")
    return unique


def _clean_text(value: object) -> str:
    text = str(value or "").strip()
    text = text.strip('"').strip("'").strip()
    if text in {"NaN", "nan", "None"}:
        return ""
    return text


def _clean_numeric_value(value: object) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    return float(text)


def _iso_timestamp(origin: datetime, offset_seconds: int) -> str:
    return (origin + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")





