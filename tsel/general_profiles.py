from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


PROFILE_DREAM_REPORT = "dream_report_profile"
PROFILE_ENVIRONMENT_OBSERVATION = "environment_observation_profile"
PROFILE_ENVIRONMENT_STREAM = "environment_stream_profile"
PROFILE_MULTISENSORY_STREAM = "multisensory_stream_profile"

PROFILE_VERSION = "1.0.0"

_TIME_COLUMNS = (
    "timestamp",
    "captured_at",
    "dream_timestamp",
    "time",
    "datetime",
    "start_time",
)
_TEXT_COLUMNS = ("dream_text", "report_text", "text", "dream report", "dream text")
_SOURCE_COLUMNS = ("participant_id", "subject_id", "source", "author", "sensor_id", "station", "device_id", "rig_id", "session_id", "recording_id")
_SAMPLE_RATE_COLUMNS = ("sample_rate_hz", "sampling_rate_hz", "sample_rate")
_ENVIRONMENT_COLUMNS = ("measurement", "reading", "temperature", "humidity", "airflow", "weather", "station", "apparatus", "rig", "ambient")
_SENSE_HINTS: dict[str, tuple[str, ...]] = {
    "vision": ("vision", "visual", "light", "pupil", "gaze", "eye"),
    "audition": ("audition", "auditory", "audio", "sound", "tone", "loudness"),
    "olfaction": ("odor", "odour", "olfaction", "olfactory", "compound", "cid", "dilution", "gas", "smell"),
    "gustation": ("taste", "gustation", "gustatory", "flavor", "salivation", "sweet", "salty", "sour", "bitter", "umami"),
    "somatosensation": ("touch", "tactile", "contact", "pressure", "skin", "vibration", "pain", "thermal", "somato"),
}


@dataclass(slots=True)
class GeneralProfileResolution:
    domain: str
    profile_id: str | None = None
    route_profile: str | None = None
    modality: str | None = None
    resolution_status: str = "unresolved"
    rationale: str = ""
    evidence_signatures: list[str] = field(default_factory=list)
    candidate_profiles: list[str] = field(default_factory=list)
    missing_metadata: list[str] = field(default_factory=list)
    assertion_basis: str = "deterministically_derived"

    def unresolved_reason(self) -> str:
        if self.missing_metadata:
            return f"insufficient_{self.domain}_metadata"
        return f"insufficient_{self.domain}_evidence"


def _canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _pick(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {_canonical(name): name for name in fieldnames}
    for candidate in candidates:
        actual = lookup.get(_canonical(candidate))
        if actual is not None:
            return actual
    return None


def _is_numeric(value: Any) -> bool:
    try:
        float(str(value).strip())
    except (TypeError, ValueError):
        return False
    return True


def _numeric_columns(fieldnames: list[str], rows: list[dict[str, Any]], excluded: set[str]) -> list[str]:
    columns: list[str] = []
    for fieldname in fieldnames:
        if fieldname in excluded:
            continue
        values = [row.get(fieldname) for row in rows if row.get(fieldname) not in (None, "")]
        if values and all(_is_numeric(value) for value in values):
            columns.append(fieldname)
    return columns


def _token_has_hint(token: str, hint: str) -> bool:
    return token == hint or token.startswith(f"{hint}_") or token.endswith(f"_{hint}") or f"_{hint}_" in token


def _collect_tokens(fieldnames: list[str], *, path: Path, extra: list[str] | None = None) -> set[str]:
    tokens = {_canonical(path.stem)}
    for fieldname in fieldnames:
        token = _canonical(fieldname)
        if token:
            tokens.add(token)
    for value in extra or []:
        token = _canonical(value)
        if token:
            tokens.add(token)
    return tokens


def _has_environment_hint(tokens: set[str]) -> bool:
    return any(any(_token_has_hint(token, hint) for hint in _ENVIRONMENT_COLUMNS) for token in tokens)


def _sense_families(tokens: set[str]) -> set[str]:
    families: set[str] = set()
    for token in tokens:
        for family, hints in _SENSE_HINTS.items():
            if any(_token_has_hint(token, hint) for hint in hints):
                families.add(family)
    return families


def _build_context(resolution: GeneralProfileResolution) -> dict[str, Any]:
    missing = list(dict.fromkeys(resolution.missing_metadata))
    basis = resolution.assertion_basis
    context: dict[str, Any] = {
        "domain_profile": {
            "domain": resolution.domain,
            "profile_id": resolution.profile_id,
            "profile_version": PROFILE_VERSION,
            "resolution_status": resolution.resolution_status,
            "evidence_signatures": resolution.evidence_signatures,
            "candidate_profiles": resolution.candidate_profiles,
            "missing_metadata": missing,
        },
        "assertion_basis": {
            "domain_profile.domain": basis,
            "domain_profile.profile_version": basis,
            "domain_profile.resolution_status": basis,
        },
    }
    if resolution.profile_id is not None:
        context["assertion_basis"]["domain_profile.profile_id"] = basis
    else:
        context["unresolved"] = {"domain_profile.profile_id": resolution.unresolved_reason()}
        context["assertion_basis"]["domain_profile.profile_id"] = "unresolved"
    if resolution.route_profile is not None:
        context["acquisition"] = {"acquisition_profile": resolution.route_profile}
        context["assertion_basis"]["acquisition.acquisition_profile"] = basis
    if missing:
        context["completeness"] = {
            "observation_status": "partial",
            "missing_dimensions": missing,
            "future_inference_allowed": True,
        }
    return context


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = list(dict.fromkeys([*merged[key], *value]))
        else:
            merged[key] = value
    return merged


def merge_general_domain_profile_into_config(config: dict[str, Any], resolution: GeneralProfileResolution) -> dict[str, Any]:
    domain_context = _build_context(resolution)
    merged = dict(config)
    adapter = str(merged.get("adapter", ""))
    if adapter in {"csv", "json"}:
        mapping = dict(merged["mapping"])
        context = dict(mapping.get("context", {}))
        static = dict(context.get("static", {}))
        context["static"] = _deep_merge(static, domain_context)
        mapping["context"] = context
        merged["mapping"] = mapping
        return merged
    if adapter == "timeseries_csv":
        context = dict(merged.get("context", {}))
        static = dict(context.get("static", {}))
        context["static"] = _deep_merge(static, domain_context)
        merged["context"] = context
        return merged
    if adapter in {"timeseries_json", "edf"}:
        merged["context"] = _deep_merge(dict(merged.get("context", {})), domain_context)
        return merged
    return merged


def resolve_dream_table_profile(path: Path, fieldnames: list[str]) -> GeneralProfileResolution:
    text_field = _pick(fieldnames, _TEXT_COLUMNS)
    source_field = _pick(fieldnames, _SOURCE_COLUMNS)
    timestamp_field = _pick(fieldnames, _TIME_COLUMNS)
    if text_field is None or source_field is None:
        return GeneralProfileResolution(
            domain="dream",
            rationale="Dream rows require explicit report text and source fields.",
            missing_metadata=["report_text", "source_id"],
            assertion_basis="unresolved",
        )
    missing: list[str] = []
    if timestamp_field is None:
        missing.append("absolute_time")
    return GeneralProfileResolution(
        domain="dream",
        profile_id=PROFILE_DREAM_REPORT,
        route_profile="dream",
        modality="dream",
        resolution_status="partial" if missing else "resolved",
        rationale="Resolved the table as dream-report temporal records from explicit text and source fields.",
        evidence_signatures=["text_field", "source_field", *([] if timestamp_field is None else ["timestamp_field"])],
        candidate_profiles=[PROFILE_DREAM_REPORT],
        missing_metadata=missing,
    )


def resolve_dream_json_profile(path: Path, payload: Any) -> GeneralProfileResolution:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return GeneralProfileResolution(
            domain="dream",
            rationale="Dream JSON must be a row-style record collection.",
            missing_metadata=["record_collection"],
            assertion_basis="unresolved",
        )
    return resolve_dream_table_profile(path, list(payload[0].keys()))


def resolve_environment_table_profile(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> GeneralProfileResolution:
    timestamp_field = _pick(fieldnames, _TIME_COLUMNS)
    source_field = _pick(fieldnames, _SOURCE_COLUMNS)
    measurement_field = _pick(fieldnames, ("measurement", "metric", "signal_type", "channel"))
    reading_field = _pick(fieldnames, ("reading", "value", "measurement_value"))
    sample_rate_field = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
    excluded = {name for name in (timestamp_field, source_field, sample_rate_field) if name}
    numeric_columns = _numeric_columns(fieldnames, rows, excluded)
    tokens = _collect_tokens(fieldnames, path=path, extra=numeric_columns)

    if source_field is not None and measurement_field is not None and reading_field is not None:
        missing: list[str] = []
        if timestamp_field is None:
            missing.append("absolute_time")
        return GeneralProfileResolution(
            domain="environment",
            profile_id=PROFILE_ENVIRONMENT_OBSERVATION,
            route_profile="environment",
            modality="environment",
            resolution_status="partial" if missing else "resolved",
            rationale="Resolved the table as environmental observations from explicit source, measurement, and value fields.",
            evidence_signatures=["source_field", "measurement_field", "reading_field", *([] if timestamp_field is None else ["timestamp_field"])],
            candidate_profiles=[PROFILE_ENVIRONMENT_OBSERVATION],
            missing_metadata=missing,
        )

    if source_field is not None and numeric_columns and (_has_environment_hint(tokens) or sample_rate_field is not None):
        missing: list[str] = []
        if timestamp_field is None:
            missing.append("absolute_time")
        if sample_rate_field is None:
            missing.append("sampling_rate")
        return GeneralProfileResolution(
            domain="environment",
            profile_id=PROFILE_ENVIRONMENT_STREAM,
            route_profile="environment",
            modality="environment",
            resolution_status="partial" if missing else "resolved",
            rationale="Resolved the table as an environmental temporal stream from source context and structured numeric channels.",
            evidence_signatures=["source_field", "numeric_channels", *([] if sample_rate_field is None else ["sample_rate_field"])],
            candidate_profiles=[PROFILE_ENVIRONMENT_STREAM],
            missing_metadata=missing,
        )

    return GeneralProfileResolution(
        domain="environment",
        rationale="The input does not contain enough deterministic environmental evidence.",
        missing_metadata=["environment_structure"],
        assertion_basis="unresolved",
    )


def resolve_environment_json_profile(path: Path, payload: Any) -> GeneralProfileResolution:
    if isinstance(payload, dict) and isinstance(payload.get("channels"), dict):
        fieldnames = list(payload.keys())
        source_field = _pick(fieldnames, _SOURCE_COLUMNS)
        sample_rate_field = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
        timestamp_field = _pick(fieldnames, _TIME_COLUMNS)
        channel_names = [str(name) for name in payload["channels"].keys()]
        tokens = _collect_tokens(fieldnames, path=path, extra=channel_names)
        if source_field is not None and channel_names and (_has_environment_hint(tokens) or sample_rate_field is not None):
            missing: list[str] = []
            if timestamp_field is None:
                missing.append("absolute_time")
            if sample_rate_field is None:
                missing.append("sampling_rate")
            return GeneralProfileResolution(
                domain="environment",
                profile_id=PROFILE_ENVIRONMENT_STREAM,
                route_profile="environment",
                modality="environment",
                resolution_status="partial" if missing else "resolved",
                rationale="Resolved the JSON stream as environmental time-series data from source context and structured channels.",
                evidence_signatures=["source_field", "channel_arrays", *([] if sample_rate_field is None else ["sample_rate_field"])],
                candidate_profiles=[PROFILE_ENVIRONMENT_STREAM],
                missing_metadata=missing,
            )
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return resolve_environment_table_profile(path, list(payload[0].keys()), [dict(item) for item in payload[:25]])
    return GeneralProfileResolution(
        domain="environment",
        rationale="Environment JSON must be row records or structured channel arrays.",
        missing_metadata=["environment_structure"],
        assertion_basis="unresolved",
    )


def resolve_multisensory_table_profile(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> GeneralProfileResolution:
    timestamp_field = _pick(fieldnames, _TIME_COLUMNS)
    source_field = _pick(fieldnames, _SOURCE_COLUMNS)
    sample_rate_field = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
    excluded = {name for name in (timestamp_field, source_field, sample_rate_field) if name}
    numeric_columns = _numeric_columns(fieldnames, rows, excluded)
    tokens = _collect_tokens(fieldnames, path=path, extra=numeric_columns)
    families = _sense_families(tokens)
    if source_field is None or not numeric_columns or not families:
        return GeneralProfileResolution(
            domain="multisensory",
            rationale="Multisensory streams require source context plus structured numeric sensory channels.",
            missing_metadata=["multisensory_channel_evidence"],
            assertion_basis="unresolved",
        )
    missing: list[str] = []
    if timestamp_field is None:
        missing.append("absolute_time")
    if sample_rate_field is None:
        missing.append("sampling_rate")
    return GeneralProfileResolution(
        domain="multisensory",
        profile_id=PROFILE_MULTISENSORY_STREAM,
        route_profile="multisensory",
        modality="multisensory",
        resolution_status="partial" if missing else "resolved",
        rationale="Resolved the table as a multisensory temporal stream from explicit mixed sensory channel evidence.",
        evidence_signatures=["source_field", "numeric_channels", "sensory_family_evidence", *([] if sample_rate_field is None else ["sample_rate_field"])],
        candidate_profiles=[PROFILE_MULTISENSORY_STREAM],
        missing_metadata=missing,
    )


def resolve_multisensory_json_profile(path: Path, payload: Any) -> GeneralProfileResolution:
    if isinstance(payload, dict) and isinstance(payload.get("channels"), dict):
        fieldnames = list(payload.keys())
        source_field = _pick(fieldnames, _SOURCE_COLUMNS)
        sample_rate_field = _pick(fieldnames, _SAMPLE_RATE_COLUMNS)
        timestamp_field = _pick(fieldnames, _TIME_COLUMNS)
        channel_names = [str(name) for name in payload["channels"].keys()]
        tokens = _collect_tokens(fieldnames, path=path, extra=channel_names)
        families = _sense_families(tokens)
        if source_field is None or not channel_names or not families:
            return GeneralProfileResolution(
                domain="multisensory",
                rationale="Structured multisensory JSON requires source context and mixed sensory channel evidence.",
                missing_metadata=["multisensory_channel_evidence"],
                assertion_basis="unresolved",
            )
        missing: list[str] = []
        if timestamp_field is None:
            missing.append("absolute_time")
        if sample_rate_field is None:
            missing.append("sampling_rate")
        return GeneralProfileResolution(
            domain="multisensory",
            profile_id=PROFILE_MULTISENSORY_STREAM,
            route_profile="multisensory",
            modality="multisensory",
            resolution_status="partial" if missing else "resolved",
            rationale="Resolved the JSON stream as a multisensory temporal stream from explicit mixed sensory channel evidence.",
            evidence_signatures=["source_field", "channel_arrays", "sensory_family_evidence", *([] if sample_rate_field is None else ["sample_rate_field"])],
            candidate_profiles=[PROFILE_MULTISENSORY_STREAM],
            missing_metadata=missing,
        )

    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return resolve_multisensory_table_profile(path, list(payload[0].keys()), [dict(item) for item in payload[:25]])

    return GeneralProfileResolution(
        domain="multisensory",
        rationale="Multisensory JSON must be a row collection or structured channel array payload.",
        missing_metadata=["multisensory_structure"],
        assertion_basis="unresolved",
    )
