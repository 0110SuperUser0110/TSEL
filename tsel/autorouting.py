from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .standards import normalize_sensory_profile


_TABLE_SUFFIXES = {".csv", ".tsv", ".txt"}
_JSON_SUFFIXES = {".json", ".jsonl"}
_TIME_COLUMNS = ("timestamp", "captured_at", "dream_timestamp", "time", "datetime", "start_time")
_SAMPLE_RATE_COLUMNS = ("sample_rate_hz", "sampling_rate_hz", "sample_rate")
_TEXT_COLUMNS = ("dream_text", "report_text", "text", "dream report", "dream text")
_SOURCE_COLUMNS = ("participant_id", "subject_id", "source", "author", "sensor_id", "station", "device_id", "rig_id", "session_id", "recording_id")
_ENVIRONMENT_COLUMNS = ("measurement", "reading", "temperature", "humidity", "airflow", "weather", "station", "apparatus", "rig", "ambient")
_OLFACTION_HINTS = ("odor", "odour", "olfaction", "olfactory", "compound", "cid", "dilution", "gas", "smell")
_SENSE_HINTS: dict[str, tuple[str, ...]] = {
    "vision": ("vision", "visual", "light", "pupil", "gaze", "eye"),
    "audition": ("audition", "auditory", "audio", "sound", "tone", "loudness"),
    "olfaction": _OLFACTION_HINTS,
    "gustation": ("taste", "gustation", "gustatory", "flavor", "salivation", "sweet", "salty", "sour", "bitter", "umami"),
    "somatosensation": ("touch", "tactile", "contact", "pressure", "skin", "vibration", "pain", "thermal", "somato"),
}
_EEG_CHANNEL_PATTERN = re.compile(
    r"^(fp[0-9z]+|af[0-9z]+|f[0-9z]+|fc[0-9z]+|c[0-9z]+|cp[0-9z]+|p[0-9z]+|po[0-9z]+|o[0-9z]+|t[0-9z]+|tp[0-9z]+|ft[0-9z]+|cz|pz|fz|oz)$",
    re.IGNORECASE,
)
_SYNTHETIC_TIME_ORIGIN = "1970-01-01T00:00:00Z"
_INTERNAL_SEQUENCE_COLUMN = "__tsel_sequence_index"


@dataclass(slots=True)
class AutoIngestPlan:
    input_path: Path
    sensory_profile: str
    adapter: str
    rationale: str
    config: dict[str, Any]
    detected_format: str

    def to_record(self) -> dict[str, Any]:
        return {
            "input": str(self.input_path),
            "sensory_profile": self.sensory_profile,
            "adapter": self.adapter,
            "detected_format": self.detected_format,
            "rationale": self.rationale,
            "config": self.config,
        }


@dataclass(slots=True)
class TablePreview:
    delimiter: str
    fieldnames: list[str]
    rows: list[dict[str, Any]]


class AutoRoutingError(ValueError):
    pass


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _pick(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {_norm(name): name for name in fieldnames}
    for candidate in candidates:
        actual = lookup.get(_norm(candidate))
        if actual is not None:
            return actual
    return None


def _read_table(path: Path, max_rows: int = 25) -> TablePreview:
    with path.open("r", encoding="utf-8", newline="") as handle:
        first_line = handle.readline()
        handle.seek(0)
        delimiter = "\t" if "\t" in first_line and path.suffix.lower() in {".tsv", ".txt"} else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        fieldnames = list(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(reader, start=1):
            rows.append(dict(row))
            if index >= max_rows:
                break
    if not fieldnames:
        raise AutoRoutingError(f"unable to read tabular headers from {path.name}")
    return TablePreview(delimiter=delimiter, fieldnames=fieldnames, rows=rows)


def _read_json(path: Path) -> Any:
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise AutoRoutingError("JSON input is empty")
    try:
        if path.suffix.lower() == ".jsonl":
            return [json.loads(line) for line in raw_text.splitlines() if line.strip()]
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AutoRoutingError(f"invalid JSON input: {exc.msg}") from exc


def _json_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return [dict(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return [dict(item) for item in payload["records"] if isinstance(item, dict)]
    raise AutoRoutingError("expected a JSON record collection")


def _is_numeric(value: Any) -> bool:
    try:
        float(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True


def _numeric_cols(fieldnames: list[str], rows: list[dict[str, Any]], excluded: set[str]) -> list[str]:
    columns: list[str] = []
    for fieldname in fieldnames:
        if fieldname in excluded:
            continue
        values = [row.get(fieldname) for row in rows if row.get(fieldname) not in (None, "")]
        if values and all(_is_numeric(value) for value in values):
            columns.append(fieldname)
    return columns


def _unit_for(column: str, profile: str) -> str:
    normalized = _norm(column)
    if profile == "eeg":
        return "uV"
    if normalized.endswith("_c") or "temperature" in normalized:
        return "C"
    if "conductance" in normalized or normalized.startswith("eda"):
        return "uS"
    if "airflow" in normalized or normalized.endswith("speed"):
        return "m/s"
    if "ppm" in normalized:
        return "ppm"
    if "ppb" in normalized:
        return "ppb"
    if "stage" in normalized:
        return "stage"
    if "text" in normalized or "report" in normalized:
        return "text"
    return "a.u."


def _timestamp_spec(fieldnames: list[str], *, allow_row_number: bool = False) -> dict[str, Any] | None:
    timestamp_column = _pick(fieldnames, _TIME_COLUMNS)
    if timestamp_column is not None:
        return {"column": timestamp_column}
    elapsed_ms = _pick(fieldnames, ("elapsed_ms",))
    if elapsed_ms is not None:
        return {"column": elapsed_ms, "origin": _SYNTHETIC_TIME_ORIGIN, "unit": "milliseconds"}
    elapsed_seconds = _pick(fieldnames, ("elapsed_seconds", "elapsed_s"))
    if elapsed_seconds is not None:
        return {"column": elapsed_seconds, "origin": _SYNTHETIC_TIME_ORIGIN, "unit": "seconds"}
    if allow_row_number:
        row_number = _pick(fieldnames, ("row_number", "row", "index"))
        if row_number is not None:
            return {"column": row_number, "origin": _SYNTHETIC_TIME_ORIGIN, "unit": "seconds", "cast": "int"}
    return None


def _synthetic_timestamp_spec(*, unit: str = "seconds") -> dict[str, Any]:
    return {"column": _INTERNAL_SEQUENCE_COLUMN, "origin": _SYNTHETIC_TIME_ORIGIN, "unit": unit, "cast": "int"}


def _relative_time_context() -> dict[str, Any]:
    return {
        "completeness": {
            "observation_status": "partial",
            "missing_dimensions": ["absolute_time"],
            "future_inference_allowed": True,
        }
    }


def _merge_static_context(base: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(base)
    if extra:
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                nested = dict(merged[key])
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value
    return merged


def _sequence_block(fieldnames: list[str], *, fallback_internal: bool = False) -> dict[str, Any]:
    row_number = _pick(fieldnames, ("row_number", "row", "index"))
    if row_number is None:
        if fallback_internal:
            return {"sequence_index": {"column": _INTERNAL_SEQUENCE_COLUMN, "cast": "int"}}
        return {}
    return {"sequence_index": {"column": row_number, "cast": "int"}}


def _is_normalized_event(record: dict[str, Any]) -> bool:
    required = {"timestamp", "modality", "source", "signal_type", "value", "unit", "contextual_metadata"}
    return required.issubset(record.keys())


def looks_like_normalized_tsel(input_path: str | Path) -> bool:
    path = Path(input_path)
    if not path.exists() or path.suffix.lower() not in _JSON_SUFFIXES:
        return False
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001
        return False
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return True
    if isinstance(payload, list) and payload:
        return isinstance(payload[0], dict) and _is_normalized_event(payload[0])
    if isinstance(payload, dict):
        return _is_normalized_event(payload)
    return False



def _collect_tokens(fieldnames: list[str], *, path: Path, extra: list[str] | None = None) -> set[str]:
    tokens = {_norm(path.stem)}
    for fieldname in fieldnames:
        token = _norm(fieldname)
        if token:
            tokens.add(token)
    for value in extra or []:
        token = _norm(value)
        if token:
            tokens.add(token)
    return tokens


def _token_has_hint(token: str, hint: str) -> bool:
    return token == hint or token.startswith(f"{hint}_") or token.endswith(f"_{hint}") or f"_{hint}_" in token



def _sense_families(tokens: set[str]) -> set[str]:
    families: set[str] = set()
    for token in tokens:
        for family, hints in _SENSE_HINTS.items():
            if any(_token_has_hint(token, hint) for hint in hints):
                families.add(family)
    return families



def _has_environment_hint(tokens: set[str]) -> bool:
    return any(any(_token_has_hint(token, hint) for hint in _ENVIRONMENT_COLUMNS) for token in tokens)



def _deterministic_route_candidates(
    *,
    path: Path,
    fieldnames: list[str],
    numeric_columns: list[str],
    channel_names: list[str] | None = None,
) -> dict[str, str]:
    channels = list(channel_names or [])
    tokens = _collect_tokens(fieldnames, path=path, extra=[*numeric_columns, *channels])
    families = _sense_families(tokens)
    timestamp_spec = _timestamp_spec(fieldnames, allow_row_number=True)
    timestamp_present = timestamp_spec is not None
    source_column = _pick(fieldnames, _SOURCE_COLUMNS)
    text_column = _pick(fieldnames, _TEXT_COLUMNS)
    sample_rate_column = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
    measurement_column = _pick(fieldnames, ("measurement", "metric", "signal_type", "channel"))
    reading_column = _pick(fieldnames, ("reading", "value", "measurement_value"))
    explicit_multisensory = any(token in {"multisensory", "cross_modal", "cross_modal_stream"} for token in tokens)
    candidates: dict[str, str] = {}

    if text_column is not None and source_column is not None:
        candidates["dream"] = "explicit text-report fields were detected"

    eeg_channels = [name for name in [*numeric_columns, *channels] if _EEG_CHANNEL_PATTERN.match(_norm(name))]
    if eeg_channels and (sample_rate_column is not None or timestamp_present or len(eeg_channels) >= 2 or path.suffix.lower() == ".edf"):
        candidates["eeg"] = "recognized EEG channel names were detected"

    has_olfaction = "olfaction" in families
    has_environment = _has_environment_hint(tokens)
    other_sense_families = families - {"olfaction"}
    if has_olfaction and not other_sense_families:
        candidates["olfaction"] = "olfaction-specific fields were detected"

    if has_environment and measurement_column is not None and reading_column is not None and not families:
        candidates["environment"] = "environment or apparatus measurement fields were detected"

    if not candidates:
        has_generic_sensor_stream = bool(channels) or bool(numeric_columns)
        if explicit_multisensory or (has_generic_sensor_stream and families and "olfaction" not in candidates):
            candidates["multisensory"] = "structured sensory channels were detected without a more specific acquisition route"

    if has_environment and other_sense_families and (bool(channels) or bool(numeric_columns)) and "eeg" not in candidates and "dream" not in candidates:
        candidates["multisensory"] = "mixed sensory and contextual measurement channels were detected"
    elif len(families) >= 2 and (bool(channels) or bool(numeric_columns)) and "eeg" not in candidates and "dream" not in candidates:
        candidates["multisensory"] = "multiple sensory families were detected in one stream layout"

    return candidates



def _resolve_candidate(candidates: dict[str, str]) -> tuple[str, str]:
    if not candidates:
        raise AutoRoutingError(
            "insufficient deterministic route evidence: the input does not declare a supported acquisition route clearly enough"
        )
    if len(candidates) > 1:
        detail = ", ".join(f"{profile} ({reason})" for profile, reason in sorted(candidates.items()))
        raise AutoRoutingError(f"ambiguous deterministic route evidence: {detail}")
    profile, rationale = next(iter(candidates.items()))
    return profile, rationale



def _infer_profile_from_table(path: Path, preview: TablePreview) -> tuple[str, str]:
    fieldnames = preview.fieldnames
    timestamp_spec = _timestamp_spec(fieldnames, allow_row_number=True)
    timestamp_column = None if timestamp_spec is None else str(timestamp_spec.get("column"))
    source_column = _pick(fieldnames, _SOURCE_COLUMNS)
    sample_rate_column = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
    excluded = {column for column in (timestamp_column, source_column, sample_rate_column, _pick(fieldnames, _TEXT_COLUMNS)) if column}
    numeric_columns = _numeric_cols(fieldnames, preview.rows, excluded)
    return _resolve_candidate(_deterministic_route_candidates(path=path, fieldnames=fieldnames, numeric_columns=numeric_columns))



def _infer_profile_from_json(path: Path, payload: Any) -> tuple[str, str]:
    if isinstance(payload, dict) and isinstance(payload.get("channels"), dict):
        fieldnames = list(payload.keys())
        channel_names = [str(name) for name in payload["channels"].keys()]
        return _resolve_candidate(
            _deterministic_route_candidates(path=path, fieldnames=fieldnames, numeric_columns=[], channel_names=channel_names)
        )

    records = _json_records(payload)
    if not records:
        raise AutoRoutingError("JSON record collection is empty")
    fieldnames = list(records[0].keys())
    source_column = _pick(fieldnames, _SOURCE_COLUMNS)
    timestamp_spec = _timestamp_spec(fieldnames, allow_row_number=True)
    timestamp_column = None if timestamp_spec is None else str(timestamp_spec.get("column"))
    sample_rate_column = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
    excluded = {column for column in (timestamp_column, source_column, sample_rate_column, _pick(fieldnames, _TEXT_COLUMNS)) if column}
    numeric_columns = _numeric_cols(fieldnames, records[:25], excluded)
    return _resolve_candidate(_deterministic_route_candidates(path=path, fieldnames=fieldnames, numeric_columns=numeric_columns))



def infer_acquisition_profile(input_path: str | Path) -> str:
    path = Path(input_path)
    if not path.exists():
        raise AutoRoutingError(f"input file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".edf":
        return "eeg"
    if suffix in _TABLE_SUFFIXES:
        profile, _ = _infer_profile_from_table(path, _read_table(path))
        return profile
    if suffix in _JSON_SUFFIXES:
        profile, _ = _infer_profile_from_json(path, _read_json(path))
        return profile
    raise AutoRoutingError(f"unsupported input format for automatic routing: {path.suffix}")



def build_auto_ingest_plan(input_path: str | Path, sensory_profile: str) -> AutoIngestPlan:
    path = Path(input_path)
    if not path.exists():
        raise AutoRoutingError(f"input file not found: {path}")
    profile = normalize_sensory_profile(sensory_profile)
    if profile == "generic":
        profile = infer_acquisition_profile(path)
    suffix = path.suffix.lower()
    if suffix == ".edf":
        return _plan_edf(path, profile)
    if suffix in _TABLE_SUFFIXES:
        return _plan_table(path, profile, _read_table(path))
    if suffix in _JSON_SUFFIXES:
        return _plan_json(path, profile, _read_json(path))
    raise AutoRoutingError(f"unsupported input format for automatic routing: {path.suffix}")
def _plan_edf(path: Path, profile: str) -> AutoIngestPlan:
    if profile not in {"eeg", "multisensory"}:
        raise AutoRoutingError(f"EDF routing is only supported for eeg or multisensory profiles, not '{profile}'")
    modality = "eeg" if profile == "eeg" else "multisensory"
    config = {
        "adapter": "edf",
        "modality": modality,
        "source_strategy": "file_name",
        "default_signal_type": "voltage",
        "signal_type_strategy": "literal",
        "default_unit": "uV",
        "context": {"ingest_mode": "auto_profile", "sensory_profile": profile, "temporal_layer": "unified"},
        "annotation_signal_type": "marker",
        "annotation_unit": "event",
    }
    return AutoIngestPlan(path, profile, "edf", "EDF input was routed directly into temporal sample ingestion.", config, "edf")


def _plan_table(path: Path, profile: str, preview: TablePreview) -> AutoIngestPlan:
    fieldnames = preview.fieldnames
    if profile == "dream":
        text_column = _pick(fieldnames, _TEXT_COLUMNS)
        source_column = _pick(fieldnames, ("participant_id", "subject_id", "source", "author"))
        timestamp_spec = _timestamp_spec(fieldnames, allow_row_number=True)
        static_context = {"ingest_mode": "auto_profile", "sensory_profile": "dream", "temporal_layer": "unified"}
        if timestamp_spec is None:
            timestamp_spec = _synthetic_timestamp_spec()
            static_context = _merge_static_context(static_context, _relative_time_context())
        if text_column is None or source_column is None or timestamp_spec is None:
            raise AutoRoutingError("dream routing requires text and source columns")
        config = {
            "adapter": "csv",
            "delimiter": preview.delimiter,
            "mapping": {
                "timestamp": timestamp_spec,
                "modality": {"value": "dream"},
                "source": {"column": source_column},
                "signal_type": {"value": "dream_report"},
                "value": {"column": text_column},
                "unit": {"value": "text"},
                "context": {"capture_remaining": True, "static": static_context},
                "temporal": {"event_kind": {"value": "report"}, **_sequence_block(fieldnames, fallback_internal=True)},
            },
        }
        return AutoIngestPlan(path, profile, "csv", "Detected dream-report rows in a table.", config, "table")

    if profile == "environment" and {"measurement", "reading"} & {_norm(name) for name in fieldnames}:
        timestamp_spec = _timestamp_spec(fieldnames)
        source_column = _pick(fieldnames, ("station", "source", "device_id", "rig_id"))
        signal_column = _pick(fieldnames, ("measurement", "metric", "signal_type", "channel"))
        value_column = _pick(fieldnames, ("reading", "value", "measurement_value"))
        unit_column = _pick(fieldnames, ("unit",))
        static_context = {"ingest_mode": "auto_profile", "sensory_profile": profile, "temporal_layer": "unified"}
        if timestamp_spec is None:
            timestamp_spec = _synthetic_timestamp_spec()
            static_context = _merge_static_context(static_context, _relative_time_context())
        if not all((source_column, signal_column, value_column)):
            raise AutoRoutingError("environment routing requires source, signal, and value columns")
        config = {
            "adapter": "csv",
            "delimiter": preview.delimiter,
            "mapping": {
                "timestamp": timestamp_spec,
                "modality": {"value": "environment"},
                "source": {"column": source_column},
                "signal_type": {"column": signal_column},
                "value": {"column": value_column, "cast": "float"},
                "unit": {"column": unit_column} if unit_column else {"value": _unit_for(signal_column, profile)},
                "context": {"capture_remaining": True, "static": static_context},
            },
        }
        return AutoIngestPlan(path, profile, "csv", "Detected row-based environmental observations.", config, "table")

    timestamp_spec = _timestamp_spec(fieldnames)
    timestamp_column = None if timestamp_spec is None else timestamp_spec.get("column")
    sample_rate_column = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
    static_context = {"ingest_mode": "auto_profile", "sensory_profile": profile, "temporal_layer": "unified"}
    uses_sequence_time = timestamp_column is None
    if uses_sequence_time:
        timestamp_spec = _synthetic_timestamp_spec(unit="samples")
        timestamp_column = str(timestamp_spec["column"])
        static_context = _merge_static_context(static_context, _relative_time_context())

    if profile == "eeg":
        source_column = _pick(fieldnames, ("session_id", "source", "recording_id", "participant_id", "subject_id"))
        metadata_columns = [name for name in fieldnames if _norm(name) in {"task", "condition", "subject_id", "trial_id", "session_id", "recording_id"}]
        excluded = {timestamp_column, *(metadata_columns or [])}
        if source_column:
            excluded.add(source_column)
        if sample_rate_column:
            excluded.add(sample_rate_column)
        channel_columns = _numeric_cols(fieldnames, preview.rows, excluded)
        if not channel_columns:
            raise AutoRoutingError("EEG routing could not find numeric channel columns")
        config = {
            "adapter": "timeseries_csv",
            "delimiter": preview.delimiter,
            "timestamp": timestamp_spec,
            "modality": {"value": "eeg"},
            "source": {"column": source_column} if source_column else {"value": path.stem},
            "sample_rate": {"column": sample_rate_column, "cast": "float"} if sample_rate_column else {"value": 1.0, "cast": "float"},
            "context": {"include": metadata_columns, "static": static_context},
            "channels": {column: {"signal_type": "voltage", "unit": "uV"} for column in channel_columns},
        }
        rationale = (
            "Detected EEG channel columns in a table without explicit timestamps; sequence timing will be preserved relatively."
            if uses_sequence_time
            else "Detected EEG channel columns in a table."
        )
        return AutoIngestPlan(path, profile, "timeseries_csv", rationale, config, "table")

    source_candidates = ("rig_id", "source", "device_id", "session_id") if profile in {"multisensory", "environment"} else ("subject_id", "sensor_id", "participant_id", "source")
    source_column = _pick(fieldnames, source_candidates)
    metadata_names = {"subject_id", "trial_id", "session_id", "condition", "task", "device_id", "compound_id", "cid", "odor_name", "replicate_label", "intensity_label", "dilution", "sensor_id", "participant_id"}
    metadata_columns = [name for name in fieldnames if _norm(name) in metadata_names and name != source_column]
    excluded = {timestamp_column, *(metadata_columns or [])}
    if source_column:
        excluded.add(source_column)
    if sample_rate_column:
        excluded.add(sample_rate_column)
    channel_columns = _numeric_cols(fieldnames, preview.rows, excluded)
    if not channel_columns:
        raise AutoRoutingError(f"{profile} routing could not find numeric channel columns")
    modality = "olfaction_perception" if profile == "olfaction" and _pick(fieldnames, ("compound_id", "cid")) is not None else profile
    config = {
        "adapter": "timeseries_csv",
        "delimiter": preview.delimiter,
        "timestamp": timestamp_spec,
        "modality": {"value": modality},
        "source": {"column": source_column} if source_column else {"value": path.stem},
        "sample_rate": {"column": sample_rate_column, "cast": "float"} if sample_rate_column else {"value": 1.0, "cast": "float"},
        "auto_channels": {
            "exclude": sorted(excluded),
            "signal_type_strategy": "channel_name",
            "default_unit": "rating" if profile == "olfaction" else "a.u.",
            "channel_units": {column: _unit_for(column, profile) for column in channel_columns},
            "cast": "float",
        },
        "context": {"include": metadata_columns, "static": static_context},
    }
    rationale = (
        f"Detected sequence-based {profile} channels in a table without explicit timestamps."
        if uses_sequence_time
        else f"Detected timestamped {profile} channels in a table."
    )
    return AutoIngestPlan(path, profile, "timeseries_csv", rationale, config, "table")
def _plan_json(path: Path, profile: str, payload: Any) -> AutoIngestPlan:
    if isinstance(payload, dict) and isinstance(payload.get("channels"), dict):
        source_field = _pick(list(payload.keys()), ("source", "session_id", "recording_id", "rig_id", "device_id"))
        start_time_field = _pick(list(payload.keys()), ("start_time", "timestamp", "recording_start"))
        sample_rate_field = _pick(list(payload.keys()), _SAMPLE_RATE_COLUMNS)
        metadata_field = _pick(list(payload.keys()), ("metadata", "context"))
        annotations_field = _pick(list(payload.keys()), ("annotations", "events", "markers"))
        timestamps_field = _pick(list(payload.keys()), ("timestamps",))
        static_context = {"ingest_mode": "auto_profile", "sensory_profile": profile, "temporal_layer": "unified"}
        default_sample_rate_hz = None
        if timestamps_field is None and start_time_field is None:
            static_context = _merge_static_context(static_context, _relative_time_context())
            if sample_rate_field is None:
                default_sample_rate_hz = 1.0
        config = {
            "adapter": "timeseries_json",
            "modality": "eeg" if profile == "eeg" else profile,
            "source_field": source_field,
            "start_time_field": start_time_field,
            "timestamps_field": timestamps_field,
            "sample_rate_field": sample_rate_field,
            "default_sample_rate_hz": default_sample_rate_hz,
            "metadata_field": metadata_field,
            "channels_field": "channels",
            "annotations_field": annotations_field,
            "default_signal_type": "voltage" if profile == "eeg" else "measurement",
            "signal_type_strategy": "literal" if profile == "eeg" else "channel_name",
            "default_unit": "uV" if profile == "eeg" else "a.u.",
            "channel_units": {name: _unit_for(name, profile) for name in payload["channels"].keys()} if profile != "eeg" else {},
            "context": static_context,
            "annotation_signal_type": "marker",
            "annotation_unit": "event",
        }
        return AutoIngestPlan(path, profile, "timeseries_json", f"Detected multichannel {profile} JSON streams.", config, "json")

    records = _json_records(payload)
    fieldnames = list(records[0].keys()) if records else []
    static_context = {"ingest_mode": "auto_profile", "sensory_profile": profile, "temporal_layer": "unified"}
    if profile == "dream":
        text_column = _pick(fieldnames, _TEXT_COLUMNS)
        source_column = _pick(fieldnames, ("participant_id", "subject_id", "source", "author"))
        timestamp_spec = _timestamp_spec(fieldnames, allow_row_number=True)
        if timestamp_spec is None:
            timestamp_spec = _synthetic_timestamp_spec()
            static_context = _merge_static_context(static_context, _relative_time_context())
        if text_column is None or source_column is None or timestamp_spec is None:
            raise AutoRoutingError("dream routing requires text and source fields")
        signal_spec = {"value": "dream_report"}
        value_spec = {"column": text_column}
        unit_spec = {"value": "text"}
        temporal = {"event_kind": {"value": "report"}, **_sequence_block(fieldnames, fallback_internal=True)}
    else:
        timestamp_spec = _timestamp_spec(fieldnames)
        if timestamp_spec is None:
            timestamp_spec = _synthetic_timestamp_spec()
            static_context = _merge_static_context(static_context, _relative_time_context())
        source_candidates = ("station", "source", "device_id", "rig_id") if profile == "environment" else ("sensor_id", "source", "subject_id", "participant_id")
        source_column = _pick(fieldnames, source_candidates)
        signal_column = _pick(fieldnames, ("measurement", "metric", "signal_type", "channel", "odorant", "odor_name"))
        value_column = _pick(fieldnames, ("reading", "value", "measurement_value", "intensity_ppm", "intensity", "rating"))
        if not all((source_column, signal_column, value_column)):
            raise AutoRoutingError(f"{profile} JSON routing requires source, signal, and value fields")
        signal_spec = {"column": signal_column}
        value_spec = {"column": value_column, "cast": "float"}
        unit_column = _pick(fieldnames, ("unit",))
        unit_spec = {"column": unit_column} if unit_column else {"value": _unit_for(signal_column, profile)}
        temporal = {}
    config = {
        "adapter": "json",
        "mapping": {
            "timestamp": timestamp_spec,
            "modality": {"value": profile},
            "source": {"column": source_column},
            "signal_type": signal_spec,
            "value": value_spec,
            "unit": unit_spec,
            "context": {"capture_remaining": True, "static": static_context},
            **({"temporal": temporal} if temporal else {}),
        },
    }
    return AutoIngestPlan(path, profile, "json", f"Detected row-style {profile} records in JSON.", config, "json")





