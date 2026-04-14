from __future__ import annotations

"""EEG domain profiles mapped into the shared TSEL contract.

This module does not define a separate EEG schema. It classifies EEG
collection classes conservatively and maps them into the existing
seven-field TSEL event envelope through contextual metadata.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from .edf import read_edf_header


EEG_PROFILE_VERSION = "1.0.0"

PROFILE_DIRECT_STREAM = "eeg_direct_stream_profile"
PROFILE_TABULAR_SERIES = "eeg_tabular_series_profile"
PROFILE_EDF = "eeg_edf_profile"
PROFILE_EVENT_ALIGNED = "eeg_event_aligned_profile"
PROFILE_PACKET = "eeg_packet_profile"
PROFILE_ANNOTATION_LOG = "eeg_annotation_log_profile"

_TIME_COLUMNS = (
    "timestamp",
    "captured_at",
    "time",
    "datetime",
    "start_time",
    "recording_start",
    "elapsed_ms",
    "elapsed_seconds",
    "elapsed_s",
    "window_start",
    "window_start_ms",
    "window_start_seconds",
)
_SAMPLE_RATE_COLUMNS = ("sample_rate_hz", "sampling_rate_hz", "sample_rate")
_SOURCE_COLUMNS = ("source", "session_id", "recording_id", "participant_id", "subject_id", "device_id")
_SESSION_COLUMNS = ("session_id", "recording_id", "trial_id", "trial", "epoch_id", "block_id")
_MARKER_COLUMNS = ("marker_type", "annotation_label", "event_label", "event_kind", "label", "sleep_stage", "stage")
_SIGNAL_COLUMNS = ("signal_type", "event_type", "marker_type", "event_kind")
_UNIT_COLUMNS = ("unit",)
_WINDOW_ID_COLUMNS = ("window_id", "epoch_id", "window_label")
_WINDOW_END_COLUMNS = ("window_end", "window_end_ms", "window_end_seconds", "end_time", "end_timestamp")
_DURATION_COLUMNS = ("duration_seconds", "duration_s", "duration_ms")
_EEG_METADATA_HINTS = ("eeg", "electrode", "montage", "reference", "impedance", "erp", "brain", "scalp")
_EEG_PART_PATTERN = re.compile(
    r"^(fp[0-9z]+|af[0-9z]+|f[0-9z]+|fc[0-9z]+|c[0-9z]+|cp[0-9z]+|p[0-9z]+|po[0-9z]+|o[0-9z]+|t[0-9z]+|tp[0-9z]+|ft[0-9z]+|a[12]|m[12]|cz|pz|fz|oz)$",
    re.IGNORECASE,
)
_SYNTHETIC_TIME_ORIGIN = "1970-01-01T00:00:00Z"


@dataclass(frozen=True, slots=True)
class EegProfileSpec:
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
class EegProfileResolution:
    domain: str = "eeg"
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
            return "ambiguous_eeg_profile"
        if self.missing_metadata:
            return "insufficient_eeg_metadata"
        return "insufficient_eeg_evidence"


EEG_PROFILE_SPECS: dict[str, EegProfileSpec] = {
    PROFILE_DIRECT_STREAM: EegProfileSpec(
        profile_id=PROFILE_DIRECT_STREAM,
        class_name="EEG Direct Multichannel Sampled Stream",
        description="Multichannel sampled EEG streams expressed directly as per-channel arrays in JSON.",
        expected_temporal_structure="Continuous or sequence-timed samples across explicitly declared EEG channels.",
        expected_input_structure="JSON object with channels plus timestamps or sample-rate-based timing.",
        minimum_required_metadata=("time_basis", "channel_arrays", "strong_eeg_channel_or_metadata_evidence"),
        optional_metadata=("sampling_rate", "montage", "reference", "session_id", "trial_id", "acquisition_metadata"),
        supported_claims=("sample_stream", "channel_identity", "sampling_rate_when_explicit", "deterministic_continuity"),
        forbidden_claims=("cognitive_state", "emotional_state", "subjective_experience", "stimulus_identity_without_linked_metadata"),
        likely_unresolved_states=("missing_sampling_rate", "missing_absolute_time", "missing_session_or_trial_id", "missing_electrode_labels"),
    ),
    PROFILE_TABULAR_SERIES: EegProfileSpec(
        profile_id=PROFILE_TABULAR_SERIES,
        class_name="EEG Tabular Time Series",
        description="Row-based EEG time series with numeric EEG channel columns.",
        expected_temporal_structure="Timestamped or sequence-timed samples across one or more EEG channels.",
        expected_input_structure="CSV, TSV, or TXT table with EEG channel columns and timing fields.",
        minimum_required_metadata=("time_basis", "numeric_channel_columns", "strong_eeg_channel_or_metadata_evidence"),
        optional_metadata=("sampling_rate", "montage", "reference", "session_id", "trial_id", "condition"),
        supported_claims=("sample_stream", "channel_identity", "sampling_rate_when_explicit", "deterministic_continuity"),
        forbidden_claims=("cognitive_state", "emotional_state", "stimulus_meaning_without_linked_metadata"),
        likely_unresolved_states=("missing_sampling_rate", "missing_absolute_time", "missing_session_or_trial_id", "missing_electrode_labels"),
    ),
    PROFILE_EDF: EegProfileSpec(
        profile_id=PROFILE_EDF,
        class_name="EEG EDF File Input",
        description="EDF files carrying EEG signal channels with optional annotation channels.",
        expected_temporal_structure="Sampled EEG records with timing implied by EDF header and optional annotation events.",
        expected_input_structure="EDF container with at least one EEG signal channel.",
        minimum_required_metadata=("edf_container", "eeg_signal_labels"),
        optional_metadata=("annotation_channel", "recording_id", "patient_id", "montage_reference_metadata"),
        supported_claims=("edf_route", "sample_stream", "channel_identity", "sampling_rate_from_header", "annotation_preservation_when_present"),
        forbidden_claims=("cognitive_state", "emotional_state", "stimulus_meaning_without_explicit_annotation", "over_interpretation_of_header_metadata"),
        likely_unresolved_states=("missing_eeg_signal_labels", "missing_montage_reference_metadata", "edf_header_inadequate_for_stronger_claims"),
    ),
    PROFILE_EVENT_ALIGNED: EegProfileSpec(
        profile_id=PROFILE_EVENT_ALIGNED,
        class_name="EEG Event-Aligned Response Windows",
        description="EEG sampled streams with explicit marker or window annotations aligned to the signal.",
        expected_temporal_structure="Sampled EEG traces plus explicit event markers or explicit temporal windows.",
        expected_input_structure="Direct JSON EEG streams with explicit annotations or windows, or other explicitly aligned stream structures.",
        minimum_required_metadata=("sample_stream", "explicit_annotation_or_window_support"),
        optional_metadata=("sampling_rate", "absolute_time", "session_id", "trial_id", "pre_post_window_context"),
        supported_claims=("sample_stream", "marker_preservation", "window_preservation_when_explicit", "deterministic_phase_recovery_when_explicit_markers_support_it"),
        forbidden_claims=("stimulus_identity_without_linked_metadata", "cognitive_state", "emotional_state", "subjective_experience"),
        likely_unresolved_states=("missing_session_or_trial_id", "missing_pre_post_window_context", "missing_sampling_rate"),
    ),
    PROFILE_PACKET: EegProfileSpec(
        profile_id=PROFILE_PACKET,
        class_name="EEG Packetized Trial or Session Records",
        description="Explicit packet declarations grouping one or more EEG raw members into one session or trial packet.",
        expected_temporal_structure="Packet-declared session or trial grouping around one or more raw EEG members.",
        expected_input_structure="Directory with explicit packet manifest declaring EEG session membership.",
        minimum_required_metadata=("explicit_packet_manifest", "packet_type", "member_paths"),
        optional_metadata=("session_id", "dataset", "trial_id", "notes"),
        supported_claims=("packet_declared_profile", "packet_declared_session_context", "packet_declared_member_grouping"),
        forbidden_claims=("invented_member_semantics", "invented_stimulus_identity", "invented_cognitive_interpretation"),
        likely_unresolved_states=("missing_trial_id", "incomplete_packet_manifest"),
    ),
    PROFILE_ANNOTATION_LOG: EegProfileSpec(
        profile_id=PROFILE_ANNOTATION_LOG,
        class_name="Sparse EEG Annotation or Event Logs",
        description="Sparse EEG-aligned marker or window records without raw sample arrays.",
        expected_temporal_structure="Timestamped markers or explicit windows, often sparse and session-aligned.",
        expected_input_structure="CSV or JSON rows with timestamps or relative time plus annotation labels and source context.",
        minimum_required_metadata=("time_basis", "source", "annotation_or_window_field"),
        optional_metadata=("channel", "session_id", "trial_id", "duration", "window_id"),
        supported_claims=("marker_preservation", "window_preservation_when_explicit", "session_or_trial_context_when_explicit"),
        forbidden_claims=("sample_continuity_without_samples", "cognitive_state", "stimulus_meaning_without_explicit_linkage"),
        likely_unresolved_states=("missing_absolute_time", "missing_session_or_trial_id", "missing_channel_identity"),
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


def _is_eeg_channel_label(name: str) -> bool:
    token = _canonical_token(name)
    if token.startswith("eeg_"):
        token = token[4:]
    parts = [part for part in token.split("_") if part and part not in {"lead", "channel", "ref", "reference"}]
    if not parts:
        return False
    return all(_EEG_PART_PATTERN.match(part) for part in parts)


def _eeg_channels(names: list[str]) -> list[str]:
    return [name for name in names if _is_eeg_channel_label(name)]


def _timestamp_present(fieldnames: list[str]) -> bool:
    return _pick(fieldnames, _TIME_COLUMNS) is not None


def _sample_rate_present(fieldnames: list[str]) -> bool:
    return _pick(fieldnames, _SAMPLE_RATE_COLUMNS) is not None


def _source_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _SOURCE_COLUMNS)


def _session_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _SESSION_COLUMNS)


def _annotation_label_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _MARKER_COLUMNS)


def _signal_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _SIGNAL_COLUMNS)


def _unit_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _UNIT_COLUMNS)


def _window_id_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _WINDOW_ID_COLUMNS)


def _window_end_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _WINDOW_END_COLUMNS)


def _duration_field(fieldnames: list[str]) -> str | None:
    return _pick(fieldnames, _DURATION_COLUMNS)


def _has_explicit_eeg_metadata(tokens: set[str]) -> bool:
    return _has_hint(tokens, _EEG_METADATA_HINTS)

def _profile_missing_metadata(
    profile_id: str,
    *,
    has_timestamp: bool,
    has_sample_rate: bool,
    has_source: bool,
    has_session_context: bool,
    has_electrode_labels: bool,
    has_montage_reference: bool,
) -> list[str]:
    missing: list[str] = []
    if not has_timestamp:
        missing.append("absolute_time")
    if profile_id in {PROFILE_DIRECT_STREAM, PROFILE_TABULAR_SERIES, PROFILE_EVENT_ALIGNED} and not has_sample_rate:
        missing.append("sampling_rate")
    if profile_id in {PROFILE_DIRECT_STREAM, PROFILE_TABULAR_SERIES, PROFILE_EDF, PROFILE_EVENT_ALIGNED} and not has_electrode_labels:
        missing.append("electrode_labels")
    if profile_id in {PROFILE_DIRECT_STREAM, PROFILE_TABULAR_SERIES, PROFILE_EDF} and not has_montage_reference:
        missing.append("montage_reference_metadata")
    if profile_id in {PROFILE_DIRECT_STREAM, PROFILE_TABULAR_SERIES, PROFILE_EVENT_ALIGNED, PROFILE_ANNOTATION_LOG} and not has_session_context:
        missing.append("session_or_trial_id")
    if profile_id != PROFILE_PACKET and not has_source:
        missing.append("source_id")
    return missing


def _build_domain_context(resolution: EegProfileResolution) -> dict[str, Any]:
    completeness_missing = list(dict.fromkeys(resolution.missing_metadata))
    basis = resolution.assertion_basis
    context: dict[str, Any] = {
        "domain_profile": {
            "domain": resolution.domain,
            "profile_id": resolution.profile_id,
            "profile_version": EEG_PROFILE_VERSION,
            "resolution_status": resolution.resolution_status,
            "evidence_signatures": resolution.evidence_signatures,
            "candidate_profiles": resolution.candidate_profiles,
            "missing_metadata": completeness_missing,
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


def merge_eeg_domain_profile_into_config(config: dict[str, Any], resolution: EegProfileResolution) -> dict[str, Any]:
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


def eeg_profile_specs() -> list[EegProfileSpec]:
    return list(EEG_PROFILE_SPECS.values())


def resolve_eeg_packet_profile(packet_type: str) -> EegProfileResolution:
    if packet_type != "eeg_session":
        return EegProfileResolution(
            resolution_status="unresolved",
            rationale="No recognized explicit EEG packet declaration was detected.",
            candidate_profiles=[],
            missing_metadata=["packet_declaration"],
            assertion_basis="unresolved",
        )
    return EegProfileResolution(
        profile_id=PROFILE_PACKET,
        route_profile="eeg",
        modality="eeg",
        resolution_status="resolved",
        rationale="Recognized an explicit EEG session packet manifest.",
        evidence_signatures=["explicit_packet_manifest", "packet_type:eeg_session"],
        candidate_profiles=[PROFILE_PACKET],
        missing_metadata=[],
        assertion_basis="packet_declared",
    )

def resolve_eeg_table_profile(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> EegProfileResolution:
    has_timestamp = _timestamp_present(fieldnames)
    has_sample_rate = _sample_rate_present(fieldnames)
    source_field = _source_field(fieldnames)
    session_field = _session_field(fieldnames)
    label_field = _annotation_label_field(fieldnames)
    signal_field = _signal_field(fieldnames)
    unit_field = _unit_field(fieldnames)
    window_id_field = _window_id_field(fieldnames)
    window_end_field = _window_end_field(fieldnames)
    duration_field = _duration_field(fieldnames)
    excluded = {
        name
        for name in (
            source_field,
            session_field,
            label_field,
            signal_field,
            unit_field,
            window_id_field,
            window_end_field,
            duration_field,
            _pick(fieldnames, _SAMPLE_RATE_COLUMNS),
            _pick(fieldnames, _TIME_COLUMNS),
        )
        if name
    }
    numeric_columns = _numeric_columns(fieldnames, rows[:25], excluded)
    tokens = _collect_tokens(fieldnames, path=path, extra=[*numeric_columns])
    eeg_channel_columns = _eeg_channels(numeric_columns)
    has_eeg_metadata = _has_explicit_eeg_metadata(tokens)
    has_channel_evidence = bool(eeg_channel_columns) or (len(numeric_columns) >= 2 and has_eeg_metadata and (has_timestamp or has_sample_rate))
    has_annotation_evidence = any(field is not None for field in (label_field, signal_field, window_id_field, window_end_field, duration_field))
    has_source = source_field is not None
    has_session_context = session_field is not None
    has_electrode_labels = bool(eeg_channel_columns)
    has_montage_reference = _has_hint(tokens, ("montage", "reference", "electrode")) or has_electrode_labels

    if has_channel_evidence:
        missing_metadata = _profile_missing_metadata(
            PROFILE_TABULAR_SERIES,
            has_timestamp=has_timestamp,
            has_sample_rate=has_sample_rate,
            has_source=has_source,
            has_session_context=has_session_context,
            has_electrode_labels=has_electrode_labels,
            has_montage_reference=has_montage_reference,
        )
        evidence = []
        if has_timestamp:
            evidence.append("timestamp_field")
        if has_sample_rate:
            evidence.append("sample_rate_field")
        if eeg_channel_columns:
            evidence.append("eeg_channel_columns")
        if has_eeg_metadata:
            evidence.append("explicit_eeg_metadata")
        if has_session_context:
            evidence.append("session_context")
        return EegProfileResolution(
            profile_id=PROFILE_TABULAR_SERIES,
            route_profile="eeg",
            modality="eeg",
            resolution_status="partial" if missing_metadata else "resolved",
            rationale="Resolved the table as EEG tabular time-series data from explicit EEG channel or metadata evidence.",
            evidence_signatures=evidence,
            candidate_profiles=[PROFILE_TABULAR_SERIES],
            missing_metadata=missing_metadata,
            mapping_hints={
                "timestamp_field": _pick(fieldnames, _TIME_COLUMNS),
                "sample_rate_field": _pick(fieldnames, _SAMPLE_RATE_COLUMNS),
                "source_field": source_field,
                "session_field": session_field,
                "channel_columns": numeric_columns,
                "eeg_channel_columns": eeg_channel_columns,
                "metadata_columns": [
                    name
                    for name in fieldnames
                    if _canonical_token(name) in {
                        "task",
                        "condition",
                        "subject_id",
                        "trial_id",
                        "session_id",
                        "recording_id",
                        "montage",
                        "reference",
                        "device_id",
                        "impedance",
                    }
                ],
            },
        )

    if has_annotation_evidence and (has_timestamp or _pick(fieldnames, ("elapsed_ms", "elapsed_seconds", "elapsed_s", "window_start", "window_start_ms", "window_start_seconds")) is not None) and (has_source or has_session_context):
        modality = "sleep_stage" if _canonical_token(str(label_field or "")) in {"sleep_stage", "stage"} else "eeg"
        missing_metadata = _profile_missing_metadata(
            PROFILE_ANNOTATION_LOG,
            has_timestamp=has_timestamp,
            has_sample_rate=False,
            has_source=has_source,
            has_session_context=has_session_context,
            has_electrode_labels=False,
            has_montage_reference=False,
        )
        evidence = ["annotation_fields"]
        if has_timestamp:
            evidence.append("timestamp_field")
        if window_id_field is not None or window_end_field is not None:
            evidence.append("explicit_window_fields")
        return EegProfileResolution(
            profile_id=PROFILE_ANNOTATION_LOG,
            route_profile="eeg",
            modality=modality,
            resolution_status="partial" if missing_metadata else "resolved",
            rationale="Resolved the table as a sparse EEG annotation log from explicit annotation or window fields.",
            evidence_signatures=evidence,
            candidate_profiles=[PROFILE_ANNOTATION_LOG],
            missing_metadata=missing_metadata,
            mapping_hints={
                "timestamp_field": _pick(fieldnames, _TIME_COLUMNS),
                "source_field": source_field or session_field,
                "session_field": session_field,
                "label_field": label_field,
                "signal_field": signal_field,
                "unit_field": unit_field,
                "window_id_field": window_id_field,
                "window_end_field": window_end_field,
                "duration_field": duration_field,
            },
        )

    return EegProfileResolution(
        resolution_status="unresolved",
        rationale="The input table does not contain enough deterministic EEG evidence to resolve an EEG collection class safely.",
        evidence_signatures=sorted(token for token in tokens if token),
        candidate_profiles=[],
        missing_metadata=["eeg_channel_or_annotation_evidence"],
        mapping_hints={"fieldnames": fieldnames},
        assertion_basis="unresolved",
    )

def resolve_eeg_json_profile(path: Path, payload: Any) -> EegProfileResolution:
    if isinstance(payload, dict) and isinstance(payload.get("channels"), dict):
        fieldnames = list(payload.keys())
        channel_names = [str(name) for name in payload["channels"].keys()]
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        metadata_keys = list(metadata.keys()) if isinstance(metadata, dict) else []
        tokens = _collect_tokens(fieldnames, path=path, extra=[*channel_names, *metadata_keys])
        eeg_channel_names = _eeg_channels(channel_names)
        has_eeg_metadata = _has_explicit_eeg_metadata(tokens)
        has_source = _source_field(fieldnames) is not None or _source_field(metadata_keys) is not None
        has_session_context = _session_field(fieldnames) is not None or _session_field(metadata_keys) is not None
        has_timestamp = "timestamps" in payload or any(key in payload for key in ("start_time", "timestamp", "recording_start"))
        has_sample_rate = any(key in payload for key in _SAMPLE_RATE_COLUMNS)
        has_montage_reference = _has_hint(tokens, ("montage", "reference", "electrode")) or bool(eeg_channel_names)
        annotations = payload.get("annotations") or payload.get("events") or payload.get("markers")
        has_explicit_annotations = isinstance(annotations, list) and any(isinstance(item, dict) for item in annotations)
        has_channel_evidence = bool(eeg_channel_names) or (len(channel_names) >= 2 and has_eeg_metadata and (has_timestamp or has_sample_rate))
        if not has_channel_evidence:
            return EegProfileResolution(
                resolution_status="unresolved",
                rationale="The multichannel JSON stream does not expose enough deterministic EEG evidence to resolve an EEG profile safely.",
                evidence_signatures=sorted(token for token in tokens if token),
                candidate_profiles=[],
                missing_metadata=["eeg_channel_or_metadata_evidence"],
                assertion_basis="unresolved",
            )
        profile_id = PROFILE_EVENT_ALIGNED if has_explicit_annotations else PROFILE_DIRECT_STREAM
        missing_metadata = _profile_missing_metadata(
            profile_id,
            has_timestamp=has_timestamp,
            has_sample_rate=has_sample_rate,
            has_source=has_source,
            has_session_context=has_session_context,
            has_electrode_labels=bool(eeg_channel_names),
            has_montage_reference=has_montage_reference,
        )
        evidence = ["multichannel_json"]
        if eeg_channel_names:
            evidence.append("eeg_channel_names")
        if has_eeg_metadata:
            evidence.append("explicit_eeg_metadata")
        if has_timestamp:
            evidence.append("timestamp_field")
        if has_sample_rate:
            evidence.append("sample_rate_field")
        if has_explicit_annotations:
            evidence.append("explicit_annotations")
        if has_session_context:
            evidence.append("session_context")
        return EegProfileResolution(
            profile_id=profile_id,
            route_profile="eeg",
            modality="eeg",
            resolution_status="partial" if missing_metadata else "resolved",
            rationale=f"Resolved the multichannel JSON stream as {profile_id} from deterministic EEG evidence.",
            evidence_signatures=evidence,
            candidate_profiles=[profile_id],
            missing_metadata=missing_metadata,
            mapping_hints={
                "channel_names": channel_names,
                "eeg_channel_names": eeg_channel_names,
                "source_field": _source_field(fieldnames),
                "metadata_field": "metadata" if isinstance(metadata, dict) else None,
                "sample_rate_field": _pick(fieldnames, _SAMPLE_RATE_COLUMNS),
                "timestamp_field": _pick(fieldnames, _TIME_COLUMNS),
            },
        )

    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        records = [dict(item) for item in payload["records"] if isinstance(item, dict)]
    elif isinstance(payload, list):
        records = [dict(item) for item in payload if isinstance(item, dict)]
    else:
        records = []
    if not records:
        return EegProfileResolution(
            resolution_status="unresolved",
            rationale="The JSON input does not contain a record collection that can be classified as EEG data.",
            missing_metadata=["record_collection"],
            assertion_basis="unresolved",
        )

    fieldnames = list(records[0].keys())
    label_field = _annotation_label_field(fieldnames)
    signal_field = _signal_field(fieldnames)
    window_id_field = _window_id_field(fieldnames)
    window_end_field = _window_end_field(fieldnames)
    duration_field = _duration_field(fieldnames)
    source_field = _source_field(fieldnames)
    session_field = _session_field(fieldnames)
    has_timestamp = _timestamp_present(fieldnames)
    has_source = source_field is not None
    has_session_context = session_field is not None
    has_annotation_evidence = any(field is not None for field in (label_field, signal_field, window_id_field, window_end_field, duration_field))
    tokens = _collect_tokens(fieldnames, path=path)
    if has_annotation_evidence and (has_timestamp or _pick(fieldnames, ("elapsed_ms", "elapsed_seconds", "elapsed_s", "window_start", "window_start_ms", "window_start_seconds")) is not None) and (has_source or has_session_context or _has_explicit_eeg_metadata(tokens)):
        modality = "sleep_stage" if _canonical_token(str(label_field or "")) in {"sleep_stage", "stage"} else "eeg"
        missing_metadata = _profile_missing_metadata(
            PROFILE_ANNOTATION_LOG,
            has_timestamp=has_timestamp,
            has_sample_rate=False,
            has_source=has_source,
            has_session_context=has_session_context,
            has_electrode_labels=False,
            has_montage_reference=False,
        )
        evidence = ["json_annotation_records"]
        if has_timestamp:
            evidence.append("timestamp_field")
        if window_id_field is not None or window_end_field is not None:
            evidence.append("explicit_window_fields")
        if _has_explicit_eeg_metadata(tokens):
            evidence.append("explicit_eeg_metadata")
        return EegProfileResolution(
            profile_id=PROFILE_ANNOTATION_LOG,
            route_profile="eeg",
            modality=modality,
            resolution_status="partial" if missing_metadata else "resolved",
            rationale="Resolved the JSON records as a sparse EEG annotation log from explicit annotation or window fields.",
            evidence_signatures=evidence,
            candidate_profiles=[PROFILE_ANNOTATION_LOG],
            missing_metadata=missing_metadata,
            mapping_hints={
                "timestamp_field": _pick(fieldnames, _TIME_COLUMNS),
                "source_field": source_field or session_field,
                "session_field": session_field,
                "label_field": label_field,
                "signal_field": signal_field,
                "unit_field": _unit_field(fieldnames),
                "window_id_field": window_id_field,
                "window_end_field": window_end_field,
                "duration_field": duration_field,
            },
        )

    return EegProfileResolution(
        resolution_status="unresolved",
        rationale="The JSON input does not contain enough deterministic EEG evidence to resolve an EEG collection class safely.",
        evidence_signatures=sorted(token for token in tokens if token),
        candidate_profiles=[],
        missing_metadata=["eeg_annotation_or_channel_evidence"],
        assertion_basis="unresolved",
    )

def resolve_eeg_edf_profile(path: Path) -> EegProfileResolution:
    header = read_edf_header(path)
    signal_labels = [signal.label for signal in header.signals if not signal.is_annotation]
    eeg_signal_labels = [label for label in signal_labels if _is_eeg_channel_label(label) or _canonical_token(label).startswith("eeg_")]
    has_annotation_channel = any(signal.is_annotation for signal in header.signals)
    has_source = bool(str(header.recording_id).strip())
    has_session_context = bool(str(header.recording_id).strip()) or bool(str(header.patient_id).strip())
    has_montage_reference = any(
        len([part for part in _canonical_token(label).split("_") if part and part != "eeg"]) > 1
        for label in eeg_signal_labels
    )
    if not eeg_signal_labels:
        return EegProfileResolution(
            resolution_status="unresolved",
            rationale="The EDF header does not declare deterministic EEG signal labels.",
            evidence_signatures=["edf_container"],
            candidate_profiles=[],
            missing_metadata=["eeg_signal_labels"],
            assertion_basis="unresolved",
        )
    missing_metadata = _profile_missing_metadata(
        PROFILE_EDF,
        has_timestamp=True,
        has_sample_rate=True,
        has_source=has_source,
        has_session_context=has_session_context,
        has_electrode_labels=True,
        has_montage_reference=has_montage_reference,
    )
    evidence = ["edf_container", "eeg_signal_labels", "edf_header_timing"]
    if has_annotation_channel:
        evidence.append("annotation_channel_declared")
    return EegProfileResolution(
        profile_id=PROFILE_EDF,
        route_profile="eeg",
        modality="eeg",
        resolution_status="partial" if missing_metadata else "resolved",
        rationale="Resolved the EDF input as EEG from deterministic EEG signal labels in the EDF header.",
        evidence_signatures=evidence,
        candidate_profiles=[PROFILE_EDF],
        missing_metadata=missing_metadata,
        mapping_hints={
            "eeg_signal_labels": eeg_signal_labels,
            "annotation_channel_declared": has_annotation_channel,
            "recording_id": header.recording_id,
            "patient_id": header.patient_id,
        },
    )
