from __future__ import annotations

"""Olfactory domain profiles mapped into the shared TSEL contract.

This module does not define a separate olfactory schema. It classifies
olfactory collection classes conservatively and maps them into the existing
seven-field TSEL event envelope through contextual metadata.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


OLFACTORY_PROFILE_VERSION = "1.0.0"

PROFILE_EVENT = "olfactory_event_profile"
PROFILE_SENSOR_STREAM = "olfactory_sensor_stream_profile"
PROFILE_RECEPTOR_SERIES = "olfactory_receptor_series_profile"
PROFILE_NEURAL_RESPONSE = "olfactory_neural_response_profile"
PROFILE_TRIAL_PACKET = "olfactory_trial_packet_profile"
PROFILE_SUBJECTIVE_REPORT = "olfactory_subjective_report_profile"

DOMAIN_RESOLUTION_STATUSES = {"resolved", "partial", "ambiguous", "unresolved"}

_TIME_COLUMNS = ("timestamp", "captured_at", "time", "datetime", "start_time", "elapsed_ms", "elapsed_seconds", "elapsed_s")
_SOURCE_COLUMNS = ("sensor_id", "source", "subject_id", "participant_id", "device_id", "session_id", "recording_id", "trial_source")
_TEXT_COLUMNS = ("report_text", "subjective_report", "text", "description", "notes", "report")
_SAMPLE_RATE_COLUMNS = ("sample_rate_hz", "sampling_rate_hz", "sample_rate")
_ODOR_COLUMNS = ("odor_name", "odorant", "odor", "odor_id", "stimulus_label", "stimulus_id", "compound_id", "cid")
_CONCENTRATION_COLUMNS = ("concentration", "concentration_ppm", "intensity_ppm", "intensity", "ppm", "ppb", "dilution", "dilution_label")
_TRIAL_COLUMNS = ("trial_id", "trial", "replicate", "replicate_label", "block_id", "condition")
_MARKER_COLUMNS = ("event_kind", "marker_type", "annotation_label", "presentation_phase", "delivery_state", "event_label")
_SENSOR_COLUMNS = ("sensor", "sensor_id", "gas", "chemical", "e_nose", "enose", "pid")
_RECEPTOR_COLUMNS = ("receptor", "receptor_id", "orn", "glomerulus", "glomeruli", "orn_id", "cell_id", "gene")
_EEG_CHANNEL_PATTERN = re.compile(
    r"^(fp[0-9z]+|af[0-9z]+|f[0-9z]+|fc[0-9z]+|c[0-9z]+|cp[0-9z]+|p[0-9z]+|po[0-9z]+|o[0-9z]+|t[0-9z]+|tp[0-9z]+|ft[0-9z]+|cz|pz|fz|oz)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class OlfactoryProfileSpec:
    profile_id: str
    class_name: str
    description: str
    expected_temporal_structure: str
    expected_input_structure: str
    minimum_required_metadata: tuple[str, ...]
    optional_metadata: tuple[str, ...]
    supported_claims: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    likely_unresolved_states: tuple[str, ...]


@dataclass(slots=True)
class OlfactoryProfileResolution:
    domain: str = "olfaction"
    profile_id: str | None = None
    route_profile: str | None = None
    modality: str | None = None
    resolution_status: str = "unresolved"
    rationale: str = ""
    evidence_signatures: list[str] = field(default_factory=list)
    candidate_profiles: list[str] = field(default_factory=list)
    missing_metadata: list[str] = field(default_factory=list)
    mapping_hints: dict[str, Any] = field(default_factory=dict)
    assertion_basis: str = "deterministically_derived"

    def unresolved_reason(self) -> str:
        if self.resolution_status == "ambiguous":
            return "ambiguous_olfactory_profile"
        if self.missing_metadata:
            return "insufficient_olfactory_metadata"
        return "insufficient_olfactory_evidence"


OLFACTORY_PROFILE_SPECS: dict[str, OlfactoryProfileSpec] = {
    PROFILE_EVENT: OlfactoryProfileSpec(
        profile_id=PROFILE_EVENT,
        class_name="Olfactory Exposure/Event Logs",
        description="Discrete odor exposure records, odor-event markers, or row-style olfactory observations.",
        expected_temporal_structure="Sparse timestamped observations or markers, sometimes with explicit onset and offset rows.",
        expected_input_structure="Tabular or JSON rows with timestamp/source plus odor identity, concentration, event label, or rating fields.",
        minimum_required_metadata=("timestamp_or_relative_time", "source", "odor_or_measurement_field"),
        optional_metadata=("odor_identity", "concentration", "trial_id", "presentation_phase", "delivery_state"),
        supported_claims=("observation", "marker", "explicit_stimulus_context", "explicit_concentration_context"),
        forbidden_claims=("continuous_sampling_without_samples", "implicit_continuity", "invented_odor_identity"),
        likely_unresolved_states=("missing_odor_identity", "missing_concentration", "missing_onset_offset_markers", "missing_trial_id"),
    ),
    PROFILE_SENSOR_STREAM: OlfactoryProfileSpec(
        profile_id=PROFILE_SENSOR_STREAM,
        class_name="Olfactory Sensor Streams",
        description="Time-series outputs from olfactory sensors or gas-sensing arrays.",
        expected_temporal_structure="Timestamped or sequence-timed numeric samples across one or more sensor channels.",
        expected_input_structure="Multichannel CSV/JSON with timestamps or sample rate plus numeric sensor measurements.",
        minimum_required_metadata=("time_basis", "source", "numeric_channels"),
        optional_metadata=("sampling_rate", "odor_identity", "concentration", "trial_id", "device_metadata"),
        supported_claims=("sample_stream", "deterministic_continuity", "deterministic_phase_structure_when_marked"),
        forbidden_claims=("subjective_report_inference", "invented_device_metadata", "invented_stimulus_identity"),
        likely_unresolved_states=("missing_sampling_rate", "missing_odor_identity", "missing_concentration", "missing_trial_id"),
    ),
    PROFILE_RECEPTOR_SERIES: OlfactoryProfileSpec(
        profile_id=PROFILE_RECEPTOR_SERIES,
        class_name="Olfactory Receptor-Response Series",
        description="Time-series measurements indexed by receptor, receptor class, glomerulus, or related response unit.",
        expected_temporal_structure="Timestamped or sequence-timed numeric series grouped by receptor-aligned channels.",
        expected_input_structure="Tabular or JSON series with receptor identifiers plus numeric response channels.",
        minimum_required_metadata=("time_basis", "source", "receptor_identifier", "numeric_channels"),
        optional_metadata=("sampling_rate", "odor_identity", "concentration", "trial_id"),
        supported_claims=("sample_stream", "receptor_series_identity", "deterministic_continuity"),
        forbidden_claims=("invented_neural_route", "invented_subjective_context", "invented_odor_identity"),
        likely_unresolved_states=("missing_receptor_identifier", "missing_sampling_rate", "missing_odor_identity", "missing_trial_id"),
    ),
    PROFILE_NEURAL_RESPONSE: OlfactoryProfileSpec(
        profile_id=PROFILE_NEURAL_RESPONSE,
        class_name="Olfactory Neural-Response Time Series",
        description="Neural recordings aligned to odor events or explicit olfactory trial metadata.",
        expected_temporal_structure="Sampled neural traces plus explicit odor-event markers or explicit olfactory trial declarations.",
        expected_input_structure="EEG-like multichannel series with odor annotations, odor metadata, or trial declarations.",
        minimum_required_metadata=("neural_channels", "time_basis", "olfactory_marker_or_trial_context"),
        optional_metadata=("sampling_rate", "odor_identity", "concentration", "trial_id", "pre_post_windows"),
        supported_claims=("eeg_route", "sample_stream", "deterministic_continuity", "deterministic_phase_structure_when_marked"),
        forbidden_claims=("implicit_olfactory_domain_without_markers", "invented_stimulus_context", "invented_trial_structure"),
        likely_unresolved_states=("missing_odor_markers", "missing_odor_identity", "missing_concentration", "missing_trial_id"),
    ),
    PROFILE_TRIAL_PACKET: OlfactoryProfileSpec(
        profile_id=PROFILE_TRIAL_PACKET,
        class_name="Olfactory Trial Packets",
        description="Typed packet collections with explicit olfactory trial declarations and packet-level provenance.",
        expected_temporal_structure="Packet-derived observations, sample vectors, or markers normalized from a declared trial bundle.",
        expected_input_structure="Directory packet or typed collection with explicit required members.",
        minimum_required_metadata=("packet_membership", "packet_type"),
        optional_metadata=("absolute_time", "trial_id", "odor_identity", "concentration"),
        supported_claims=("packet_declared_profile", "packet_declared_trial_context", "packet_declared_partition_context"),
        forbidden_claims=("invented_absolute_time", "invented_acquisition_device"),
        likely_unresolved_states=("missing_absolute_time", "incomplete_packet_declaration"),
    ),
    PROFILE_SUBJECTIVE_REPORT: OlfactoryProfileSpec(
        profile_id=PROFILE_SUBJECTIVE_REPORT,
        class_name="Olfactory Subjective Report Streams",
        description="Text or rating reports explicitly about odor experience.",
        expected_temporal_structure="Timestamped or sequence-timed report observations, usually sparse and narrative or rating-driven.",
        expected_input_structure="Rows or JSON records with report text or subjective ratings plus odor-linked context.",
        minimum_required_metadata=("source", "report_field", "odor_or_trial_context"),
        optional_metadata=("timestamp", "odor_identity", "trial_id", "concentration"),
        supported_claims=("report_event", "explicit_report_context", "explicit_odor_context"),
        forbidden_claims=("sample_continuity", "neural_route", "invented_stimulus_window"),
        likely_unresolved_states=("missing_odor_identity", "missing_timestamp", "missing_trial_id"),
    ),
}


def _canonical_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _pick(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lookup = {_canonical_token(name): name for name in fieldnames}
    for candidate in candidates:
        actual = lookup.get(_canonical_token(candidate))
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


def _collect_tokens(fieldnames: list[str], *, path: Path, extra: list[str] | None = None) -> set[str]:
    tokens = {_canonical_token(path.stem)}
    for fieldname in fieldnames:
        token = _canonical_token(fieldname)
        if token:
            tokens.add(token)
    for value in extra or []:
        token = _canonical_token(value)
        if token:
            tokens.add(token)
    return tokens


def _has_hint(tokens: set[str], hints: tuple[str, ...]) -> bool:
    for token in tokens:
        for hint in hints:
            if token == hint or token.startswith(f"{hint}_") or token.endswith(f"_{hint}") or f"_{hint}_" in token:
                return True
    return False


def _timestamp_present(fieldnames: list[str]) -> bool:
    return _pick(fieldnames, _TIME_COLUMNS) is not None


def _sample_rate_present(fieldnames: list[str]) -> bool:
    return _pick(fieldnames, _SAMPLE_RATE_COLUMNS) is not None


def _odor_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _ODOR_COLUMNS)


def _concentration_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _CONCENTRATION_COLUMNS)


def _trial_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _TRIAL_COLUMNS)


def _text_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _TEXT_COLUMNS)


def _source_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _SOURCE_COLUMNS)


def _event_signal_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, ("signal_type", "measurement", "metric", "event_kind", "marker_type", "annotation_label"))


def _event_value_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, ("value", "reading", "measurement_value", "rating", "intensity", "intensity_ppm", "concentration", "ppm", "ppb"))


def _event_unit_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, ("unit", "intensity_unit"))


def _eeg_channels(fieldnames: list[str], numeric_columns: list[str]) -> list[str]:
    candidates = [name for name in numeric_columns if _EEG_CHANNEL_PATTERN.match(_canonical_token(name))]
    if candidates:
        return candidates
    return [name for name in fieldnames if _EEG_CHANNEL_PATTERN.match(_canonical_token(name))]


def _profile_missing_metadata(
    profile_id: str,
    *,
    has_timestamp: bool,
    has_sample_rate: bool,
    has_odor: bool,
    has_concentration: bool,
    has_trial: bool,
    has_explicit_markers: bool,
    has_source: bool,
    has_text: bool,
    has_receptor: bool,
) -> list[str]:
    missing: list[str] = []
    if not has_timestamp:
        missing.append("absolute_time")
    if profile_id in {PROFILE_SENSOR_STREAM, PROFILE_RECEPTOR_SERIES, PROFILE_NEURAL_RESPONSE} and not has_sample_rate:
        missing.append("sampling_rate")
    if not has_odor and profile_id != PROFILE_TRIAL_PACKET:
        missing.append("odor_identity")
    if profile_id in {PROFILE_EVENT, PROFILE_SENSOR_STREAM, PROFILE_NEURAL_RESPONSE} and not has_concentration:
        missing.append("odor_concentration")
    if profile_id in {PROFILE_EVENT, PROFILE_NEURAL_RESPONSE} and not has_explicit_markers:
        missing.append("stimulus_markers")
    if profile_id in {PROFILE_EVENT, PROFILE_SENSOR_STREAM, PROFILE_RECEPTOR_SERIES, PROFILE_NEURAL_RESPONSE, PROFILE_SUBJECTIVE_REPORT} and not has_trial:
        missing.append("trial_id")
    if profile_id == PROFILE_RECEPTOR_SERIES and not has_receptor:
        missing.append("receptor_identifier")
    if profile_id == PROFILE_SUBJECTIVE_REPORT and not has_text:
        missing.append("subjective_report_field")
    if profile_id != PROFILE_TRIAL_PACKET and not has_source:
        missing.append("source_id")
    return missing


def _build_domain_context(resolution: OlfactoryProfileResolution) -> dict[str, Any]:
    completeness_missing = list(dict.fromkeys(resolution.missing_metadata))
    basis = resolution.assertion_basis
    context: dict[str, Any] = {
        "sensory": {"primary_sense": "olfaction"},
        "domain_profile": {
            "domain": resolution.domain,
            "profile_id": resolution.profile_id,
            "profile_version": OLFACTORY_PROFILE_VERSION,
            "resolution_status": resolution.resolution_status,
            "evidence_signatures": resolution.evidence_signatures,
            "candidate_profiles": resolution.candidate_profiles,
            "missing_metadata": completeness_missing,
        },
        "assertion_basis": {
            "sensory.primary_sense": basis,
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
    if completeness_missing:
        context["completeness"] = {
            "observation_status": "partial",
            "missing_dimensions": completeness_missing,
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


def merge_domain_profile_into_config(config: dict[str, Any], resolution: OlfactoryProfileResolution) -> dict[str, Any]:
    """Attach generic domain-profile context to an existing config."""

    domain_context = _build_domain_context(resolution)
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


def resolve_olfactory_packet_profile(packet_type: str) -> OlfactoryProfileResolution:
    if packet_type != "dream_synapse":
        return OlfactoryProfileResolution(
            resolution_status="unresolved",
            rationale="No recognized olfactory packet declaration was detected.",
            candidate_profiles=[],
            missing_metadata=["packet_declaration"],
            assertion_basis="unresolved",
        )
    return OlfactoryProfileResolution(
        profile_id=PROFILE_TRIAL_PACKET,
        route_profile="olfaction",
        modality="olfaction",
        resolution_status="partial",
        rationale="Recognized the DREAM Synapse olfactory challenge packet by required member files.",
        evidence_signatures=["typed_packet_directory", "dream_synapse_required_members"],
        candidate_profiles=[PROFILE_TRIAL_PACKET],
        missing_metadata=["absolute_time"],
        assertion_basis="packet_declared",
    )


def olfactory_profile_specs() -> list[OlfactoryProfileSpec]:
    return list(OLFACTORY_PROFILE_SPECS.values())

def resolve_olfactory_table_profile(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> OlfactoryProfileResolution:
    has_timestamp = _timestamp_present(fieldnames)
    has_sample_rate = _sample_rate_present(fieldnames)
    source_field = _source_field(fieldnames)
    odor_field = _odor_field(fieldnames)
    concentration_field = _concentration_field(fieldnames)
    trial_field = _trial_field(fieldnames)
    text_field = _text_field(fieldnames)
    signal_field = _event_signal_field(fieldnames)
    value_field = _event_value_field(fieldnames)
    marker_field = _pick(fieldnames, _MARKER_COLUMNS)
    excluded = {
        name
        for name in (
            source_field,
            odor_field,
            concentration_field,
            trial_field,
            text_field,
            signal_field,
            value_field,
            marker_field,
            _pick(fieldnames, _SAMPLE_RATE_COLUMNS),
            _pick(fieldnames, _TIME_COLUMNS),
        )
        if name
    }
    numeric_columns = _numeric_columns(fieldnames, rows[:25], excluded)
    sensor_numeric_columns = [name for name in numeric_columns if _has_hint([_canonical_token(name)], _SENSOR_COLUMNS)]
    tokens = _collect_tokens(fieldnames, path=path, extra=[*numeric_columns])
    has_odor_evidence = odor_field is not None or _has_hint(tokens, _ODOR_COLUMNS + ("olfaction", "olfactory", "smell", "odor", "odour"))
    has_explicit_markers = marker_field is not None or _has_hint(tokens, _MARKER_COLUMNS + ("onset", "offset", "stimulus"))
    receptor_field = _pick(fieldnames, _RECEPTOR_COLUMNS)
    eeg_channels = _eeg_channels(fieldnames, numeric_columns)
    has_sensor_evidence = source_field is not None and bool(sensor_numeric_columns)
    has_receptor_evidence = receptor_field is not None or _has_hint(tokens, _RECEPTOR_COLUMNS)
    has_text = text_field is not None
    has_source = source_field is not None
    has_trial = trial_field is not None
    has_concentration = concentration_field is not None
    candidates: list[str] = []

    if has_text and has_source and (has_odor_evidence or has_trial):
        candidates.append(PROFILE_SUBJECTIVE_REPORT)
    if eeg_channels and (has_odor_evidence or has_explicit_markers or has_trial):
        candidates.append(PROFILE_NEURAL_RESPONSE)
    if has_receptor_evidence and numeric_columns:
        candidates.append(PROFILE_RECEPTOR_SERIES)
    if has_sensor_evidence and numeric_columns:
        candidates.append(PROFILE_SENSOR_STREAM)
    if has_source and has_odor_evidence and (signal_field is not None or value_field is not None or has_explicit_markers):
        candidates.append(PROFILE_EVENT)

    if not candidates:
        return OlfactoryProfileResolution(
            resolution_status="unresolved",
            rationale="The table does not contain enough explicit odor-linked evidence to resolve an olfactory collection class safely.",
            evidence_signatures=sorted(token for token in tokens if token),
            candidate_profiles=[],
            missing_metadata=["odor_identity", "collection_class_evidence"],
            mapping_hints={"fieldnames": fieldnames},
            assertion_basis="unresolved",
        )

    priority = [
        PROFILE_SUBJECTIVE_REPORT,
        PROFILE_NEURAL_RESPONSE,
        PROFILE_RECEPTOR_SERIES,
        PROFILE_SENSOR_STREAM,
        PROFILE_EVENT,
    ]
    ranked = [profile for profile in priority if profile in candidates]
    if len(ranked) > 1 and ranked[0] == PROFILE_SENSOR_STREAM and PROFILE_EVENT in ranked and signal_field is not None and value_field is not None:
        ranked = [PROFILE_EVENT]
    if len(ranked) > 1 and ranked[0] == PROFILE_SUBJECTIVE_REPORT and PROFILE_EVENT in ranked:
        ranked = [PROFILE_SUBJECTIVE_REPORT]
    if len(ranked) > 1 and ranked[0] == PROFILE_NEURAL_RESPONSE and PROFILE_EVENT in ranked:
        ranked = [PROFILE_NEURAL_RESPONSE]
    if len(ranked) > 1:
        return OlfactoryProfileResolution(
            resolution_status="ambiguous",
            rationale="The table matches more than one olfactory collection class and does not justify a single deterministic profile.",
            evidence_signatures=sorted(token for token in tokens if token),
            candidate_profiles=ranked,
            missing_metadata=["profile_disambiguation_metadata"],
            mapping_hints={"fieldnames": fieldnames},
            assertion_basis="unresolved",
        )

    profile_id = ranked[0]
    route_profile = "eeg" if profile_id == PROFILE_NEURAL_RESPONSE else "olfaction"
    modality = "eeg" if profile_id == PROFILE_NEURAL_RESPONSE else "olfaction"
    missing_metadata = _profile_missing_metadata(
        profile_id,
        has_timestamp=has_timestamp,
        has_sample_rate=has_sample_rate,
        has_odor=odor_field is not None,
        has_concentration=has_concentration,
        has_trial=has_trial,
        has_explicit_markers=has_explicit_markers,
        has_source=has_source,
        has_text=has_text,
        has_receptor=has_receptor_evidence,
    )
    resolution_status = "partial" if missing_metadata else "resolved"
    evidence_signatures: list[str] = []
    if has_timestamp:
        evidence_signatures.append("timestamp_field")
    if has_sample_rate:
        evidence_signatures.append("sample_rate_field")
    if odor_field is not None:
        evidence_signatures.append("odor_identity_field")
    if concentration_field is not None:
        evidence_signatures.append("concentration_field")
    if trial_field is not None:
        evidence_signatures.append("trial_id_field")
    if text_field is not None:
        evidence_signatures.append("subjective_report_field")
    if marker_field is not None:
        evidence_signatures.append("marker_field")
    if eeg_channels:
        evidence_signatures.append("neural_channel_names")
    if has_receptor_evidence:
        evidence_signatures.append("receptor_identifiers")
    if has_sensor_evidence:
        evidence_signatures.append("sensor_stream_fields")

    return OlfactoryProfileResolution(
        profile_id=profile_id,
        route_profile=route_profile,
        modality=modality,
        resolution_status=resolution_status,
        rationale=f"Resolved the table as {profile_id} from explicit olfactory evidence signatures.",
        evidence_signatures=evidence_signatures,
        candidate_profiles=[profile_id],
        missing_metadata=missing_metadata,
        mapping_hints={
            "timestamp_field": _pick(fieldnames, _TIME_COLUMNS),
            "source_field": source_field,
            "text_field": text_field,
            "odor_field": odor_field,
            "concentration_field": concentration_field,
            "trial_field": trial_field,
            "signal_field": signal_field,
            "value_field": value_field,
            "unit_field": _event_unit_field(fieldnames),
            "sample_rate_field": _pick(fieldnames, _SAMPLE_RATE_COLUMNS),
            "numeric_columns": numeric_columns,
            "sensor_numeric_columns": sensor_numeric_columns,
            "eeg_channels": eeg_channels,
            "receptor_field": receptor_field,
            "marker_field": marker_field,
        },
    )


def resolve_olfactory_json_profile(path: Path, payload: Any) -> OlfactoryProfileResolution:
    if isinstance(payload, dict) and isinstance(payload.get("channels"), dict):
        fieldnames = list(payload.keys())
        channel_names = [str(name) for name in payload["channels"].keys()]
        tokens = _collect_tokens(fieldnames, path=path, extra=channel_names)
        eeg_channels = _eeg_channels(channel_names, channel_names)
        has_odor_evidence = _has_hint(tokens, _ODOR_COLUMNS + ("olfaction", "olfactory", "smell", "odor", "odour"))
        annotations = payload.get("annotations") or payload.get("events") or payload.get("markers")
        has_explicit_markers = isinstance(annotations, list) and any(isinstance(item, dict) and _canonical_token(str(item.get("marker_type", ""))) == "stimulus" for item in annotations)
        has_trial = any(key in {_canonical_token(name) for name in fieldnames} for key in (_canonical_token(name) for name in _TRIAL_COLUMNS))
        has_sample_rate = any(key in payload for key in _SAMPLE_RATE_COLUMNS)
        has_timestamp = "timestamps" in payload or any(key in payload for key in ("start_time", "timestamp", "recording_start"))
        has_source = _source_field(fieldnames) is not None
        has_receptor = _has_hint(tokens, _RECEPTOR_COLUMNS)
        has_concentration = _has_hint(tokens, _CONCENTRATION_COLUMNS)
        if eeg_channels and (has_odor_evidence or has_explicit_markers or has_trial):
            profile_id = PROFILE_NEURAL_RESPONSE
            route_profile = "eeg"
            modality = "eeg"
        elif has_receptor and channel_names:
            profile_id = PROFILE_RECEPTOR_SERIES
            route_profile = "olfaction"
            modality = "olfaction"
        elif (has_odor_evidence or has_concentration or _has_hint(tokens, _SENSOR_COLUMNS)) and channel_names:
            profile_id = PROFILE_SENSOR_STREAM
            route_profile = "olfaction"
            modality = "olfaction"
        else:
            return OlfactoryProfileResolution(
                resolution_status="unresolved",
                rationale="The multichannel JSON stream does not expose enough odor-linked evidence to resolve an olfactory profile safely.",
                evidence_signatures=sorted(token for token in tokens if token),
                candidate_profiles=[],
                missing_metadata=["odor_identity", "collection_class_evidence"],
                assertion_basis="unresolved",
            )
        missing_metadata = _profile_missing_metadata(
            profile_id,
            has_timestamp=has_timestamp,
            has_sample_rate=has_sample_rate,
            has_odor=has_odor_evidence,
            has_concentration=has_concentration,
            has_trial=has_trial,
            has_explicit_markers=has_explicit_markers,
            has_source=has_source,
            has_text=False,
            has_receptor=has_receptor,
        )
        evidence = ["multichannel_json"]
        if has_timestamp:
            evidence.append("timestamp_field")
        if has_sample_rate:
            evidence.append("sample_rate_field")
        if has_explicit_markers:
            evidence.append("stimulus_markers")
        if has_odor_evidence:
            evidence.append("odor_identity_field")
        if has_receptor:
            evidence.append("receptor_identifiers")
        if eeg_channels:
            evidence.append("neural_channel_names")
        return OlfactoryProfileResolution(
            profile_id=profile_id,
            route_profile=route_profile,
            modality=modality,
            resolution_status="partial" if missing_metadata else "resolved",
            rationale=f"Resolved the multichannel JSON stream as {profile_id} from explicit olfactory evidence signatures.",
            evidence_signatures=sorted(set(evidence)),
            candidate_profiles=[profile_id],
            missing_metadata=missing_metadata,
            mapping_hints={"eeg_channels": eeg_channels, "channel_names": channel_names},
        )

    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = [dict(item) for item in payload["records"] if isinstance(item, dict)]
    elif isinstance(payload, list):
        records = [dict(item) for item in payload if isinstance(item, dict)]
    else:
        records = []
    if not records:
        return OlfactoryProfileResolution(
            resolution_status="unresolved",
            rationale="The JSON input does not contain a record collection that can be classified as olfactory data.",
            missing_metadata=["record_collection"],
            assertion_basis="unresolved",
        )
    return resolve_olfactory_table_profile(path, list(records[0].keys()), records[:25])
