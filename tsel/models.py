from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

JSONPrimitive = str | int | float | bool | None
JSONValue = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]

_UNIT_TO_SECONDS = {
    "seconds": 1.0,
    "milliseconds": 0.001,
    "microseconds": 0.000001,
    "minutes": 60.0,
}

_VALID_ANCHORS = {"instant", "start", "end", "center"}
_VALID_OBSERVATION_STATUSES = {"observed", "partial", "missing", "inferred", "imputed", "derived"}
_VALID_CONTINUITY_STATES = {"continuous", "interrupted", "fragmented", "reconstructed", "unknown"}
_VALID_ASSERTION_BASES = {"source_provided", "packet_declared", "directly_observed", "deterministically_derived", "unresolved"}


def _canonical_token(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _is_json_compatible(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_compatible(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_compatible(item) for key, item in value.items())
    return False


def _normalized_alignment_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        normalized = str(value).strip()
        return normalized or None
    raise TypeError("alignment values must be primitive")


def _normalized_string_list(values: Any, field_name: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise TypeError(f"{field_name} must be a list of strings")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"{field_name} must contain non-empty strings")
        token = _canonical_token(value)
        if token and token not in seen:
            normalized.append(token)
            seen.add(token)
    return normalized


def _standardize_string_mapping(
    raw_context: Any,
    field_name: str,
    *,
    allowed_values: set[str] | None = None,
    normalize_values: bool = True,
) -> dict[str, JSONValue] | None:
    if raw_context is None:
        return None
    if not isinstance(raw_context, dict):
        raise TypeError(f"{field_name} must be a dictionary")

    normalized: dict[str, JSONValue] = {}
    for raw_key, raw_value in raw_context.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise TypeError(f"{field_name} keys must be non-empty strings")
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise TypeError(f"{field_name} values must be non-empty strings")
        normalized_key = raw_key.strip()
        normalized_value = _canonical_token(raw_value) if normalize_values else raw_value.strip()
        if allowed_values is not None and normalized_value not in allowed_values:
            raise ValueError(f"unsupported {field_name} value: {raw_value}")
        normalized[normalized_key] = normalized_value

    return normalized or None

def _standardize_completeness_context(raw_context: Any) -> dict[str, JSONValue] | None:
    if raw_context is None:
        return None
    if not isinstance(raw_context, dict):
        raise TypeError("contextual_metadata.completeness must be a dictionary")

    normalized: dict[str, JSONValue] = {}
    observation_status = raw_context.get("observation_status")
    if observation_status is not None:
        normalized_status = _canonical_token(str(observation_status))
        if normalized_status not in _VALID_OBSERVATION_STATUSES:
            raise ValueError(f"unsupported observation_status: {observation_status}")
        normalized["observation_status"] = normalized_status

    completeness_score = raw_context.get("completeness_score")
    if completeness_score is not None:
        score = float(completeness_score)
        if not 0.0 <= score <= 1.0:
            raise ValueError("completeness_score must be between 0.0 and 1.0")
        normalized["completeness_score"] = score

    missing_dimensions = _normalized_string_list(raw_context.get("missing_dimensions"), "contextual_metadata.completeness.missing_dimensions")
    if missing_dimensions:
        normalized["missing_dimensions"] = missing_dimensions

    inferred_fields = _normalized_string_list(raw_context.get("inferred_fields"), "contextual_metadata.completeness.inferred_fields")
    if inferred_fields:
        normalized["inferred_fields"] = inferred_fields

    future_inference_allowed = raw_context.get("future_inference_allowed")
    if future_inference_allowed is not None:
        if not isinstance(future_inference_allowed, bool):
            raise TypeError("contextual_metadata.completeness.future_inference_allowed must be a boolean")
        normalized["future_inference_allowed"] = future_inference_allowed

    if normalized:
        normalized.setdefault("observation_status", "observed")
    return normalized or None


def _standardize_experience_context(raw_context: Any) -> dict[str, JSONValue] | None:
    if raw_context is None:
        return None
    if not isinstance(raw_context, dict):
        raise TypeError("contextual_metadata.experience must be a dictionary")

    normalized: dict[str, JSONValue] = {}
    for key in ("experience_id", "continuity_id"):
        value = raw_context.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"contextual_metadata.experience.{key} must be a non-empty string when provided")
        normalized[key] = value.strip()

    continuity_index = raw_context.get("continuity_index")
    if continuity_index is not None:
        continuity_index = int(continuity_index)
        if continuity_index < 0:
            raise ValueError("contextual_metadata.experience.continuity_index must be non-negative")
        normalized["continuity_index"] = continuity_index

    continuity_state = raw_context.get("continuity_state")
    if continuity_state is not None:
        normalized_state = _canonical_token(str(continuity_state))
        if normalized_state not in _VALID_CONTINUITY_STATES:
            raise ValueError(f"unsupported continuity_state: {continuity_state}")
        normalized["continuity_state"] = normalized_state

    return normalized or None


def _standardize_sensory_context(raw_context: Any, metadata: dict[str, JSONValue]) -> dict[str, JSONValue] | None:
    from .standards import CORE_LATERALITY, CORE_PRIMARY_SENSES, CORE_TRAJECTORY_ROLES, normalize_laterality, normalize_primary_sense, normalize_trajectory_role

    if raw_context is not None and not isinstance(raw_context, dict):
        raise TypeError("contextual_metadata.sensory must be a dictionary")
    source_context = {} if raw_context is None else dict(raw_context)

    normalized: dict[str, JSONValue] = {}
    primary_sense = source_context.get("primary_sense", metadata.get("primary_sense", metadata.get("sensory_class")))
    if primary_sense is not None:
        normalized_primary_sense = normalize_primary_sense(str(primary_sense))
        if normalized_primary_sense not in CORE_PRIMARY_SENSES:
            raise ValueError(f"unsupported primary_sense: {primary_sense}")
        normalized["primary_sense"] = normalized_primary_sense

    for field_name in ("submodality", "body_site", "receptor_pathway"):
        value = source_context.get(field_name, metadata.get(field_name))
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"contextual_metadata.sensory.{field_name} must be a non-empty string when provided")
        normalized[field_name] = _canonical_token(value)

    laterality = source_context.get("laterality", metadata.get("laterality"))
    if laterality is not None:
        normalized_laterality = normalize_laterality(str(laterality))
        if normalized_laterality not in CORE_LATERALITY:
            raise ValueError(f"unsupported laterality: {laterality}")
        normalized["laterality"] = normalized_laterality

    trajectory_role = source_context.get("trajectory_role", metadata.get("trajectory_role"))
    if trajectory_role is not None:
        normalized_trajectory_role = normalize_trajectory_role(str(trajectory_role))
        if normalized_trajectory_role not in CORE_TRAJECTORY_ROLES:
            raise ValueError(f"unsupported trajectory_role: {trajectory_role}")
        normalized["trajectory_role"] = normalized_trajectory_role

    return normalized or None


def _standardize_acquisition_context(raw_context: Any, metadata: dict[str, JSONValue]) -> dict[str, JSONValue] | None:
    from .standards import CORE_TRANSFORM_STAGES, normalize_transform_stage

    if raw_context is not None and not isinstance(raw_context, dict):
        raise TypeError("contextual_metadata.acquisition must be a dictionary")
    source_context = {} if raw_context is None else dict(raw_context)

    normalized: dict[str, JSONValue] = {}
    acquisition_profile = source_context.get("acquisition_profile", metadata.get("acquisition_profile", metadata.get("sensory_profile")))
    if acquisition_profile is not None:
        normalized["acquisition_profile"] = _canonical_token(str(acquisition_profile))

    for field_name in ("device_class", "instrument", "channel"):
        value = source_context.get(field_name, metadata.get(field_name))
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"contextual_metadata.acquisition.{field_name} must be a non-empty string when provided")
        normalized[field_name] = _canonical_token(value) if field_name == "device_class" else value.strip()

    sample_rate_hz = source_context.get("sample_rate_hz", metadata.get("sample_rate_hz"))
    if sample_rate_hz is not None:
        sample_rate = float(sample_rate_hz)
        if sample_rate <= 0:
            raise ValueError("contextual_metadata.acquisition.sample_rate_hz must be positive")
        normalized["sample_rate_hz"] = sample_rate

    transform_stage = source_context.get("transform_stage", metadata.get("transform_stage", "normalized" if normalized else None))
    if transform_stage is not None:
        normalized_stage = normalize_transform_stage(str(transform_stage))
        if normalized_stage not in CORE_TRANSFORM_STAGES:
            raise ValueError(f"unsupported transform_stage: {transform_stage}")
        normalized["transform_stage"] = normalized_stage

    return normalized or None


def _standardize_stimulus_context(raw_context: Any, metadata: dict[str, JSONValue]) -> dict[str, JSONValue] | None:
    from .standards import CORE_DELIVERY_STATES, CORE_EXPERIENCE_PHASES, is_extension_token, normalize_delivery_state, normalize_phase

    if raw_context is None:
        return None
    if not isinstance(raw_context, dict):
        raise TypeError("contextual_metadata.stimulus must be a dictionary")
    source_context = dict(raw_context)

    normalized: dict[str, JSONValue] = {}
    stimulus_id = source_context.get("stimulus_id")
    if stimulus_id is not None:
        if not isinstance(stimulus_id, str) or not stimulus_id.strip():
            raise TypeError("contextual_metadata.stimulus.stimulus_id must be a non-empty string when provided")
        normalized["stimulus_id"] = stimulus_id.strip()

    stimulus_label = source_context.get("stimulus_label", metadata.get("annotation_label"))
    if stimulus_label is not None:
        if not isinstance(stimulus_label, str) or not stimulus_label.strip():
            raise TypeError("contextual_metadata.stimulus.stimulus_label must be a non-empty string when provided")
        normalized["stimulus_label"] = stimulus_label.strip()

    stimulus_object = source_context.get("stimulus_object")
    if stimulus_object is not None:
        if not isinstance(stimulus_object, str) or not stimulus_object.strip():
            raise TypeError("contextual_metadata.stimulus.stimulus_object must be a non-empty string when provided")
        normalized["stimulus_object"] = _canonical_token(stimulus_object)

    presentation_phase = source_context.get("presentation_phase", metadata.get("presentation_phase"))
    if presentation_phase is not None:
        normalized_phase = normalize_phase(str(presentation_phase))
        if normalized_phase not in CORE_EXPERIENCE_PHASES and not is_extension_token(normalized_phase):
            raise ValueError(f"unsupported presentation_phase: {presentation_phase}")
        normalized["presentation_phase"] = normalized_phase

    delivery_state = source_context.get("delivery_state")
    if delivery_state is not None:
        normalized_delivery_state = normalize_delivery_state(str(delivery_state))
        if normalized_delivery_state not in CORE_DELIVERY_STATES:
            raise ValueError(f"unsupported delivery_state: {delivery_state}")
        normalized["delivery_state"] = normalized_delivery_state

    intensity_estimate = source_context.get("intensity_estimate")
    if intensity_estimate is not None:
        normalized["intensity_estimate"] = float(intensity_estimate)

    intensity_unit = source_context.get("intensity_unit")
    if intensity_unit is not None:
        if not isinstance(intensity_unit, str) or not intensity_unit.strip():
            raise TypeError("contextual_metadata.stimulus.intensity_unit must be a non-empty string when provided")
        normalized["intensity_unit"] = intensity_unit.strip()

    return normalized or None


def _standardize_relations_context(raw_context: Any) -> list[JSONValue] | None:
    from .standards import normalize_relation_type

    if raw_context is None:
        return None
    if not isinstance(raw_context, list):
        raise TypeError("contextual_metadata.relations must be a list")

    normalized_relations: list[JSONValue] = []
    seen: set[tuple[str, str, str | None]] = set()
    for relation in raw_context:
        if not isinstance(relation, dict):
            raise TypeError("contextual_metadata.relations must contain dictionaries")
        relation_type = relation.get("relation_type")
        target_id = relation.get("target_id")
        if not isinstance(relation_type, str) or not relation_type.strip():
            raise TypeError("relation_type must be a non-empty string")
        if not isinstance(target_id, str) or not target_id.strip():
            raise TypeError("target_id must be a non-empty string")
        normalized_relation: dict[str, JSONValue] = {
            "relation_type": normalize_relation_type(relation_type),
            "target_id": target_id.strip(),
        }
        target_type = relation.get("target_type")
        if target_type is not None:
            if not isinstance(target_type, str) or not target_type.strip():
                raise TypeError("target_type must be a non-empty string when provided")
            normalized_relation["target_type"] = _canonical_token(target_type)
        description = relation.get("description")
        if description is not None:
            if not isinstance(description, str) or not description.strip():
                raise TypeError("description must be a non-empty string when provided")
            normalized_relation["description"] = description.strip()
        confidence = relation.get("confidence")
        if confidence is not None:
            normalized_confidence = float(confidence)
            if not 0.0 <= normalized_confidence <= 1.0:
                raise ValueError("relation confidence must be between 0.0 and 1.0")
            normalized_relation["confidence"] = normalized_confidence
        dedupe_key = (
            str(normalized_relation["relation_type"]),
            str(normalized_relation["target_id"]),
            None if normalized_relation.get("target_type") is None else str(normalized_relation["target_type"]),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_relations.append(normalized_relation)

    return normalized_relations or None


def _standardize_contextual_metadata(contextual_metadata: dict[str, JSONValue], source: str) -> dict[str, JSONValue]:
    from .standards import CORE_ALIGNMENT_KEYS

    normalized = dict(contextual_metadata)
    raw_alignment = normalized.get("alignment")
    alignment: dict[str, str] = {}
    if raw_alignment is None:
        alignment = {}
    elif isinstance(raw_alignment, dict):
        for key, value in raw_alignment.items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            normalized_value = _normalized_alignment_value(value)
            if normalized_value is not None:
                alignment[normalized_key] = normalized_value
    else:
        raise TypeError("contextual_metadata.alignment must be a dictionary")

    canonical_alignment = dict(alignment)
    canonical_alignment["source_id"] = source.strip()
    for key in CORE_ALIGNMENT_KEYS:
        if key == "source_id":
            continue
        raw_value = alignment.get(key, normalized.get(key))
        normalized_value = _normalized_alignment_value(raw_value)
        if normalized_value is not None:
            canonical_alignment[key] = normalized_value

    normalized["alignment"] = canonical_alignment

    completeness = _standardize_completeness_context(normalized.get("completeness"))
    if completeness is not None:
        normalized["completeness"] = completeness
    else:
        normalized.pop("completeness", None)

    experience = _standardize_experience_context(normalized.get("experience"))
    if experience is not None:
        normalized["experience"] = experience
    else:
        normalized.pop("experience", None)

    sensory = _standardize_sensory_context(normalized.get("sensory"), normalized)
    if sensory is not None:
        normalized["sensory"] = sensory
    else:
        normalized.pop("sensory", None)

    acquisition = _standardize_acquisition_context(normalized.get("acquisition"), normalized)
    if acquisition is not None:
        normalized["acquisition"] = acquisition
    else:
        normalized.pop("acquisition", None)

    stimulus = _standardize_stimulus_context(normalized.get("stimulus"), normalized)
    if stimulus is not None:
        normalized["stimulus"] = stimulus
    else:
        normalized.pop("stimulus", None)

    relations = _standardize_relations_context(normalized.get("relations"))
    if relations is not None:
        normalized["relations"] = relations
    else:
        normalized.pop("relations", None)

    assertion_basis = _standardize_string_mapping(
        normalized.get("assertion_basis"),
        "contextual_metadata.assertion_basis",
        allowed_values=_VALID_ASSERTION_BASES,
    )
    if assertion_basis is not None:
        normalized["assertion_basis"] = assertion_basis
    else:
        normalized.pop("assertion_basis", None)

    unresolved = _standardize_string_mapping(
        normalized.get("unresolved"),
        "contextual_metadata.unresolved",
        normalize_values=True,
    )
    if unresolved is not None:
        normalized["unresolved"] = unresolved
    else:
        normalized.pop("unresolved", None)

    return normalized


def _assertion_basis_map(contextual_metadata: dict[str, JSONValue]) -> dict[str, str]:
    raw = contextual_metadata.get("assertion_basis")
    return dict(raw) if isinstance(raw, dict) else {}



def _unresolved_map(contextual_metadata: dict[str, JSONValue]) -> dict[str, str]:
    raw = contextual_metadata.get("unresolved")
    return dict(raw) if isinstance(raw, dict) else {}



def _context_path_present(contextual_metadata: dict[str, JSONValue], field_path: str) -> bool:
    current: Any = contextual_metadata
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current is not None

def coerce_timestamp(value: Any, *, origin: str | None = None, unit: str = "seconds") -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, (int, float)):
        timestamp = _from_numeric_timestamp(float(value), origin=origin, unit=unit)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("timestamp cannot be empty")
        if origin is not None:
            try:
                numeric_value = float(stripped)
            except ValueError:
                timestamp = _parse_iso_timestamp(stripped)
            else:
                timestamp = _from_numeric_timestamp(numeric_value, origin=origin, unit=unit)
        else:
            timestamp = _parse_iso_timestamp(stripped)
    else:
        raise TypeError(f"unsupported timestamp type: {type(value)!r}")

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _from_numeric_timestamp(value: float, *, origin: str | None, unit: str) -> datetime:
    if origin is None:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    base = _parse_iso_timestamp(origin)
    scale = _UNIT_TO_SECONDS.get(unit)
    if scale is None:
        raise ValueError(f"unsupported time unit: {unit}")
    return base + timedelta(seconds=value * scale)


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def serialize_timestamp(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class TemporalExtent:
    start: datetime
    end: datetime | None = None
    anchor: str = "instant"
    resolution_seconds: float | None = None
    uncertainty_seconds: float | None = None
    time_scale: str | None = None

    def __post_init__(self) -> None:
        self.start = coerce_timestamp(self.start)
        if self.end is not None:
            self.end = coerce_timestamp(self.end)
            if self.end < self.start:
                raise ValueError("temporal extent end must be on or after start")
        if self.anchor not in _VALID_ANCHORS:
            raise ValueError(f"unsupported temporal anchor: {self.anchor}")
        if self.resolution_seconds is not None and self.resolution_seconds <= 0:
            raise ValueError("resolution_seconds must be positive")
        if self.uncertainty_seconds is not None:
            self.uncertainty_seconds = float(self.uncertainty_seconds)
            if self.uncertainty_seconds < 0:
                raise ValueError("uncertainty_seconds must be non-negative")
        if self.time_scale is not None:
            if not isinstance(self.time_scale, str) or not self.time_scale.strip():
                raise ValueError("time_scale must be a non-empty string when provided")
            self.time_scale = _canonical_token(self.time_scale)

    @classmethod
    def from_timestamp(
        cls,
        timestamp: datetime | str,
        *,
        resolution_seconds: float | None = None,
        anchor: str | None = None,
        uncertainty_seconds: float | None = None,
        time_scale: str | None = None,
    ) -> "TemporalExtent":
        start = coerce_timestamp(timestamp)
        if resolution_seconds is None:
            return cls(
                start=start,
                anchor=anchor or "instant",
                uncertainty_seconds=uncertainty_seconds,
                time_scale=time_scale,
            )
        return cls(
            start=start,
            end=start + timedelta(seconds=resolution_seconds),
            anchor=anchor or "start",
            resolution_seconds=resolution_seconds,
            uncertainty_seconds=uncertainty_seconds,
            time_scale=time_scale,
        )

    @property
    def timestamp(self) -> datetime:
        if self.anchor == "end" and self.end is not None:
            return self.end
        if self.anchor == "center" and self.end is not None:
            return self.start + (self.end - self.start) / 2
        return self.start

    @property
    def duration_seconds(self) -> float | None:
        if self.end is None:
            return None
        return (self.end - self.start).total_seconds()

    def to_metadata(self) -> dict[str, JSONValue]:
        return {
            "start": serialize_timestamp(self.start),
            "end": None if self.end is None else serialize_timestamp(self.end),
            "anchor": self.anchor,
            "duration_seconds": self.duration_seconds,
            "resolution_seconds": self.resolution_seconds,
            "uncertainty_seconds": self.uncertainty_seconds,
            "time_scale": self.time_scale,
        }

    @classmethod
    def from_metadata(cls, timestamp: datetime | str, metadata: dict[str, Any] | None) -> "TemporalExtent":
        if not metadata:
            return cls.from_timestamp(timestamp)
        start = metadata.get("start", timestamp)
        end = metadata.get("end")
        anchor = str(metadata.get("anchor", "instant"))
        resolution = metadata.get("resolution_seconds")
        uncertainty = metadata.get("uncertainty_seconds")
        time_scale = metadata.get("time_scale")
        if resolution is not None:
            resolution = float(resolution)
        if uncertainty is not None:
            uncertainty = float(uncertainty)
        return cls(
            start=coerce_timestamp(start),
            end=None if end is None else coerce_timestamp(end),
            anchor=anchor,
            resolution_seconds=resolution,
            uncertainty_seconds=uncertainty,
            time_scale=None if time_scale is None else str(time_scale),
        )


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    event_index: int | None = None
    stream_id: str | None = None

    def to_record(self) -> dict[str, JSONValue]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "event_index": self.event_index,
            "stream_id": self.stream_id,
        }


@dataclass(slots=True)
class ValidationReport:
    total_events: int
    issues: list[ValidationIssue] = field(default_factory=list)
    stream_summaries: dict[str, dict[str, JSONValue]] = field(default_factory=dict)
    sync_group_summaries: dict[str, dict[str, JSONValue]] = field(default_factory=dict)
    time_start: datetime | None = None
    time_end: datetime | None = None

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def to_record(self) -> dict[str, JSONValue]:
        return {
            "total_events": self.total_events,
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "time_start": None if self.time_start is None else serialize_timestamp(self.time_start),
            "time_end": None if self.time_end is None else serialize_timestamp(self.time_end),
            "stream_count": len(self.stream_summaries),
            "stream_summaries": self.stream_summaries,
            "sync_group_count": len(self.sync_group_summaries),
            "sync_group_summaries": self.sync_group_summaries,
            "issues": [issue.to_record() for issue in self.issues],
        }


@dataclass(slots=True)
class TemporalSegment:
    label: str
    start: datetime
    end: datetime
    events: list["TemporalEvent"] = field(default_factory=list)
    anchor_event: "TemporalEvent | None" = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.start = coerce_timestamp(self.start)
        self.end = coerce_timestamp(self.end)
        if self.end < self.start:
            raise ValueError("segment end must be on or after start")

    def to_record(self) -> dict[str, JSONValue]:
        return {
            "label": self.label,
            "start": serialize_timestamp(self.start),
            "end": serialize_timestamp(self.end),
            "duration_seconds": (self.end - self.start).total_seconds(),
            "event_count": len(self.events),
            "metadata": self.metadata,
            "anchor_event": None if self.anchor_event is None else self.anchor_event.to_record(),
            "events": [event.to_record() for event in self.events],
        }


@dataclass(slots=True)
class TemporalEvent:
    timestamp: datetime
    modality: str
    source: str
    signal_type: str
    value: JSONValue
    unit: str
    contextual_metadata: dict[str, JSONValue] = field(default_factory=dict)
    extent: TemporalExtent | None = None
    event_kind: str = "observation"
    stream_id: str | None = None
    sequence_index: int | None = None
    confidence: float | None = None
    phase: str | None = None
    sync_group: str | None = None
    window_id: str | None = None
    episode_id: str | None = None
    transition_from: JSONValue = None
    transition_to: JSONValue = None

    def __post_init__(self) -> None:
        from .standards import normalize_event_kind, normalize_modality, normalize_phase, normalize_signal_type, normalize_unit

        self.timestamp = coerce_timestamp(self.timestamp)
        if self.extent is None:
            self.extent = TemporalExtent.from_timestamp(self.timestamp)
        else:
            self.timestamp = self.extent.timestamp

        self.modality = normalize_modality(self.modality)
        self.signal_type = normalize_signal_type(self.signal_type)
        self.event_kind = normalize_event_kind(self.event_kind)
        self.unit = normalize_unit(self.unit)
        if self.phase is not None:
            self.phase = normalize_phase(self.phase)

        for name in ("modality", "source", "signal_type", "unit", "event_kind"):
            current = getattr(self, name)
            if not isinstance(current, str) or not current.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not _is_json_compatible(self.value):
            raise TypeError("value must be JSON compatible")
        if not isinstance(self.contextual_metadata, dict):
            raise TypeError("contextual_metadata must be a dictionary")
        self.contextual_metadata = _standardize_contextual_metadata(self.contextual_metadata, self.source)
        if not _is_json_compatible(self.contextual_metadata):
            raise TypeError("contextual_metadata must be JSON compatible")
        if self.sequence_index is not None:
            self.sequence_index = int(self.sequence_index)
        if self.confidence is not None:
            self.confidence = float(self.confidence)
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be between 0.0 and 1.0")
        for name in ("phase", "sync_group", "window_id", "episode_id"):
            value = getattr(self, name)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{name} must be a non-empty string when provided")
                setattr(self, name, value.strip())
        for name in ("transition_from", "transition_to"):
            value = getattr(self, name)
            if value is not None and not _is_json_compatible(value):
                raise TypeError(f"{name} must be JSON compatible")
        if self.stream_id is None:
            self.stream_id = self._default_stream_id()
        elif not isinstance(self.stream_id, str) or not self.stream_id.strip():
            raise ValueError("stream_id must be a non-empty string")

    def _default_stream_id(self) -> str:
        channel = self.contextual_metadata.get("channel")
        parts = [self.modality, self.source]
        if channel not in (None, ""):
            parts.append(str(channel))
        parts.append(self.signal_type)
        return "::".join(parts)

    def to_record(self) -> dict[str, JSONValue]:
        from .standards import TSEL_SPEC_VERSION

        metadata = _standardize_contextual_metadata(dict(self.contextual_metadata), self.source)
        existing_temporal = metadata.get("temporal")
        if isinstance(existing_temporal, dict):
            temporal = dict(existing_temporal)
        else:
            temporal = {}
        temporal.update(self.extent.to_metadata())
        temporal["event_kind"] = self.event_kind
        temporal["stream_id"] = self.stream_id
        temporal["schema_version"] = TSEL_SPEC_VERSION
        if self.sequence_index is not None:
            temporal["sequence_index"] = self.sequence_index
        if self.confidence is not None:
            temporal["confidence"] = self.confidence
        if self.phase is not None:
            temporal["phase"] = self.phase
        if self.sync_group is not None:
            temporal["sync_group"] = self.sync_group
        if self.window_id is not None:
            temporal["window_id"] = self.window_id
        if self.episode_id is not None:
            temporal["episode_id"] = self.episode_id
        if self.transition_from is not None:
            temporal["transition_from"] = self.transition_from
        if self.transition_to is not None:
            temporal["transition_to"] = self.transition_to
        metadata["temporal"] = temporal
        return {
            "timestamp": serialize_timestamp(self.timestamp),
            "modality": self.modality,
            "source": self.source,
            "signal_type": self.signal_type,
            "value": self.value,
            "unit": self.unit,
            "contextual_metadata": metadata,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "TemporalEvent":
        metadata = dict(record.get("contextual_metadata", {}))
        raw_temporal = metadata.pop("temporal", {})
        if not isinstance(raw_temporal, dict):
            raw_temporal = {}
        extent = TemporalExtent.from_metadata(record["timestamp"], raw_temporal)
        return cls(
            timestamp=record["timestamp"],
            modality=str(record["modality"]),
            source=str(record["source"]),
            signal_type=str(record["signal_type"]),
            value=record["value"],
            unit=str(record["unit"]),
            contextual_metadata=metadata,
            extent=extent,
            event_kind=str(raw_temporal.get("event_kind", "observation")),
            stream_id=None if raw_temporal.get("stream_id") is None else str(raw_temporal.get("stream_id")),
            sequence_index=None if raw_temporal.get("sequence_index") is None else int(raw_temporal.get("sequence_index")),
            confidence=None if raw_temporal.get("confidence") is None else float(raw_temporal.get("confidence")),
            phase=None if raw_temporal.get("phase") is None else str(raw_temporal.get("phase")),
            sync_group=None if raw_temporal.get("sync_group") is None else str(raw_temporal.get("sync_group")),
            window_id=None if raw_temporal.get("window_id") is None else str(raw_temporal.get("window_id")),
            episode_id=None if raw_temporal.get("episode_id") is None else str(raw_temporal.get("episode_id")),
            transition_from=raw_temporal.get("transition_from"),
            transition_to=raw_temporal.get("transition_to"),
        )


@dataclass(slots=True)
class TemporalEventCollection:
    events: list[TemporalEvent] = field(default_factory=list)

    def append(self, event: TemporalEvent) -> None:
        self.events.append(event)

    def extend(self, events: Iterable[TemporalEvent]) -> None:
        self.events.extend(events)

    def sort_in_place(self) -> None:
        self.events.sort(key=lambda event: (event.extent.start, event.modality, event.source, event.signal_type, event.sequence_index if event.sequence_index is not None else -1))

    def to_records(self) -> list[dict[str, JSONValue]]:
        return [event.to_record() for event in self.events]

    def to_bundle(self) -> dict[str, JSONValue]:
        from .standards import TSEL_SPEC_VERSION

        return {
            "spec_version": TSEL_SPEC_VERSION,
            "generated_at": serialize_timestamp(datetime.now(timezone.utc)),
            "event_count": len(self.events),
            "summary": self.summary(),
            "events": self.to_records(),
        }

    @classmethod
    def from_records(cls, records: Iterable[dict[str, Any]]) -> "TemporalEventCollection":
        collection = cls([TemporalEvent.from_record(record) for record in records])
        collection.sort_in_place()
        return collection

    def summary(self) -> dict[str, JSONValue]:
        if not self.events:
            return {
                "event_count": 0,
                "modalities": [],
                "sources": [],
                "event_kinds": [],
                "time_scales": [],
                "phases": [],
                "primary_senses": [],
                "submodalities": [],
                "trajectory_roles": [],
                "acquisition_profiles": [],
                "observation_statuses": [],
                "missing_dimensions": [],
                "partial_event_count": 0,
                "inferred_event_count": 0,
                "future_inference_ready_count": 0,
                "experience_count": 0,
                "continuity_count": 0,
                "window_count": 0,
                "stimulus_count": 0,
                "relation_count": 0,
                "stream_count": 0,
                "sync_group_count": 0,
                "time_start": None,
                "time_end": None,
                "duration_seconds": 0.0,
            }
        start = min(event.extent.start for event in self.events)
        end = max((event.extent.end or event.extent.start) for event in self.events)
        phases = sorted({event.phase for event in self.events if event.phase is not None})
        primary_senses = sorted(
            {
                str(sensory["primary_sense"])
                for event in self.events
                for sensory in [event.contextual_metadata.get("sensory")]
                if isinstance(sensory, dict) and isinstance(sensory.get("primary_sense"), str)
            }
        )
        submodalities = sorted(
            {
                str(sensory["submodality"])
                for event in self.events
                for sensory in [event.contextual_metadata.get("sensory")]
                if isinstance(sensory, dict) and isinstance(sensory.get("submodality"), str)
            }
        )
        trajectory_roles = sorted(
            {
                str(sensory["trajectory_role"])
                for event in self.events
                for sensory in [event.contextual_metadata.get("sensory")]
                if isinstance(sensory, dict) and isinstance(sensory.get("trajectory_role"), str)
            }
        )
        acquisition_profiles = sorted(
            {
                str(acquisition["acquisition_profile"])
                for event in self.events
                for acquisition in [event.contextual_metadata.get("acquisition")]
                if isinstance(acquisition, dict) and isinstance(acquisition.get("acquisition_profile"), str)
            }
        )
        observation_statuses = sorted(
            {
                str(completeness["observation_status"])
                for event in self.events
                for completeness in [event.contextual_metadata.get("completeness")]
                if isinstance(completeness, dict) and isinstance(completeness.get("observation_status"), str)
            }
        )
        missing_dimensions = sorted(
            {
                str(dimension)
                for event in self.events
                for completeness in [event.contextual_metadata.get("completeness")]
                if isinstance(completeness, dict)
                for dimension in completeness.get("missing_dimensions", [])
                if isinstance(dimension, str)
            }
        )
        partial_event_count = sum(
            1
            for event in self.events
            for completeness in [event.contextual_metadata.get("completeness")]
            if isinstance(completeness, dict) and completeness.get("observation_status") in {"partial", "missing"}
        )
        inferred_event_count = sum(
            1
            for event in self.events
            for completeness in [event.contextual_metadata.get("completeness")]
            if isinstance(completeness, dict) and completeness.get("observation_status") in {"inferred", "imputed", "derived"}
        )
        future_inference_ready_count = sum(
            1
            for event in self.events
            for completeness in [event.contextual_metadata.get("completeness")]
            if isinstance(completeness, dict) and completeness.get("future_inference_allowed") is True
        )
        experience_count = len(
            {
                str(experience["experience_id"])
                for event in self.events
                for experience in [event.contextual_metadata.get("experience")]
                if isinstance(experience, dict) and isinstance(experience.get("experience_id"), str)
            }
        )
        continuity_count = len(
            {
                str(experience["continuity_id"])
                for event in self.events
                for experience in [event.contextual_metadata.get("experience")]
                if isinstance(experience, dict) and isinstance(experience.get("continuity_id"), str)
            }
        )
        window_count = len({event.window_id for event in self.events if event.window_id is not None})
        stimulus_count = sum(1 for event in self.events if isinstance(event.contextual_metadata.get("stimulus"), dict))
        relation_count = sum(
            len(relations)
            for event in self.events
            for relations in [event.contextual_metadata.get("relations")]
            if isinstance(relations, list)
        )
        return {
            "event_count": len(self.events),
            "modalities": sorted({event.modality for event in self.events}),
            "sources": sorted({event.source for event in self.events}),
            "event_kinds": sorted({event.event_kind for event in self.events}),
            "time_scales": sorted({event.extent.time_scale for event in self.events if event.extent.time_scale is not None}),
            "phases": phases,
            "primary_senses": primary_senses,
            "submodalities": submodalities,
            "trajectory_roles": trajectory_roles,
            "acquisition_profiles": acquisition_profiles,
            "observation_statuses": observation_statuses,
            "missing_dimensions": missing_dimensions,
            "partial_event_count": partial_event_count,
            "inferred_event_count": inferred_event_count,
            "future_inference_ready_count": future_inference_ready_count,
            "experience_count": experience_count,
            "continuity_count": continuity_count,
            "window_count": window_count,
            "stimulus_count": stimulus_count,
            "relation_count": relation_count,
            "stream_count": len({event.stream_id for event in self.events}),
            "sync_group_count": len({event.sync_group for event in self.events if event.sync_group is not None}),
            "time_start": serialize_timestamp(start),
            "time_end": serialize_timestamp(end),
            "duration_seconds": (end - start).total_seconds(),
        }

    def validate(self) -> ValidationReport:
        from .standards import CORE_EVENT_KINDS, CORE_EXPERIENCE_PHASES, CORE_SIGNAL_TYPES, CORE_TIME_SCALES, is_extension_token

        issues: list[ValidationIssue] = []
        if not self.events:
            return ValidationReport(total_events=0, issues=issues, stream_summaries={})

        stream_groups: dict[str, list[tuple[int, TemporalEvent]]] = {}
        sync_group_groups: dict[str, list[tuple[int, TemporalEvent]]] = {}
        previous_timestamp = self.events[0].extent.start
        for index, event in enumerate(self.events):
            if index > 0 and event.extent.start < previous_timestamp:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="out_of_order",
                        message="event timestamps are not globally ordered",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            previous_timestamp = event.extent.start
            if event.extent.end is not None and event.extent.end < event.extent.start:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="negative_duration",
                        message="temporal extent end precedes start",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if not event.stream_id:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_stream_id",
                        message="event is missing a stream identifier",
                        event_index=index,
                    )
                )
            if event.event_kind not in CORE_EVENT_KINDS and not is_extension_token(event.event_kind):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="noncanonical_event_kind",
                        message=f"event_kind '{event.event_kind}' is not canonical or extension-safe",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.extent.time_scale is not None and event.extent.time_scale not in CORE_TIME_SCALES and not is_extension_token(event.extent.time_scale):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="noncanonical_time_scale",
                        message=f"time_scale '{event.extent.time_scale}' is not canonical or extension-safe",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.phase is not None and event.phase not in CORE_EXPERIENCE_PHASES and not is_extension_token(event.phase):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="noncanonical_phase",
                        message=f"phase '{event.phase}' is not canonical or extension-safe",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            canonical_signal_type = _canonical_token(event.signal_type)
            if canonical_signal_type not in CORE_SIGNAL_TYPES and not is_extension_token(canonical_signal_type):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="noncanonical_signal_type",
                        message=f"signal_type '{event.signal_type}' is not canonical or extension-safe",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.event_kind == "transition" and (event.transition_from is None or event.transition_to is None):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_transition_event",
                        message="transition events require transition_from and transition_to",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.event_kind in {"window", "episode"} and event.extent.end is None:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_interval_event",
                        message=f"{event.event_kind} events require an end timestamp",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.event_kind == "window" and event.window_id is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_window_id",
                        message="window events should declare a window_id",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.event_kind == "episode" and event.episode_id is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_episode_id",
                        message="episode events should declare an episode_id",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            if event.event_kind == "sample" and event.extent.resolution_seconds is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_resolution",
                        message="sample events should declare resolution_seconds",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            completeness = event.contextual_metadata.get("completeness")
            if isinstance(completeness, dict):
                observation_status = completeness.get("observation_status")
                missing_dimensions = completeness.get("missing_dimensions", [])
                inferred_fields = completeness.get("inferred_fields", [])
                if observation_status in {"partial", "missing"} and not missing_dimensions:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_missing_dimensions",
                            message="partial or missing observations should declare missing_dimensions",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
                if observation_status in {"inferred", "imputed", "derived"} and not inferred_fields:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_inferred_fields",
                            message="inferred observations should declare inferred_fields",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
            experience = event.contextual_metadata.get("experience")
            if isinstance(experience, dict):
                if experience.get("continuity_index") is not None and experience.get("continuity_id") is None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_continuity_id",
                            message="experience continuity_index should be paired with a continuity_id",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
            assertion_basis = _assertion_basis_map(event.contextual_metadata)
            unresolved = _unresolved_map(event.contextual_metadata)
            for field_path in unresolved.keys():
                if assertion_basis.get(field_path) != "unresolved":
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="inconsistent_unresolved_basis",
                            message=f"unresolved field '{field_path}' should declare assertion_basis 'unresolved'",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
            if event.phase is not None:
                phase_basis = assertion_basis.get("temporal.phase")
                if phase_basis is None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_phase_basis",
                            message="phase claims should declare assertion_basis.temporal.phase",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
                elif phase_basis == "unresolved":
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="conflicting_phase_basis",
                            message="temporal.phase cannot be populated while assertion_basis.temporal.phase is unresolved",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
            acquisition = event.contextual_metadata.get("acquisition")
            if isinstance(acquisition, dict) and acquisition.get("acquisition_profile") is not None:
                if assertion_basis.get("acquisition.acquisition_profile") is None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_acquisition_basis",
                            message="acquisition_profile should declare assertion_basis.acquisition.acquisition_profile",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
            if isinstance(experience, dict) and experience.get("continuity_state") is not None:
                if assertion_basis.get("experience.continuity_state") is None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_continuity_basis",
                            message="continuity_state should declare assertion_basis.experience.continuity_state",
                            event_index=index,
                            stream_id=event.stream_id,
                        )
                    )
            stimulus = event.contextual_metadata.get("stimulus")
            if isinstance(stimulus, dict):
                for field_name in ("stimulus_id", "presentation_phase", "delivery_state"):
                    if stimulus.get(field_name) is None:
                        continue
                    if assertion_basis.get(f"stimulus.{field_name}") is None:
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="missing_stimulus_basis",
                                message=f"stimulus.{field_name} should declare a supporting assertion basis",
                                event_index=index,
                                stream_id=event.stream_id,
                            )
                        )
            relations = event.contextual_metadata.get("relations")
            if isinstance(relations, list) and relations and assertion_basis.get("relations") is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_relation_basis",
                        message="relation claims should declare assertion_basis.relations",
                        event_index=index,
                        stream_id=event.stream_id,
                    )
                )
            stream_groups.setdefault(event.stream_id or "", []).append((index, event))
            if event.sync_group is not None:
                sync_group_groups.setdefault(event.sync_group, []).append((index, event))

        aligned_groups: dict[tuple[str, str, str], list[tuple[int, TemporalEvent]]] = {}
        for index, event in enumerate(self.events):
            if event.event_kind != "sample":
                continue
            alignment_key = (event.modality, event.source, serialize_timestamp(event.extent.start))
            aligned_groups.setdefault(alignment_key, []).append((index, event))
        for aligned_events in aligned_groups.values():
            stream_ids = {event.stream_id for _, event in aligned_events}
            if len(stream_ids) < 2:
                continue
            sync_groups = {event.sync_group for _, event in aligned_events if event.sync_group is not None}
            if not sync_groups:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_sync_group",
                        message="parallel sample events share a timestamp across streams but do not declare a sync_group",
                        event_index=aligned_events[0][0],
                        stream_id=aligned_events[0][1].stream_id,
                    )
                )
            elif len(sync_groups) > 1:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="inconsistent_sync_group",
                        message="parallel sample events share a timestamp across streams but disagree on sync_group",
                        event_index=aligned_events[0][0],
                        stream_id=aligned_events[0][1].stream_id,
                    )
                )

        sync_group_summaries: dict[str, dict[str, JSONValue]] = {}
        alignment_scope_keys = ("session_id", "recording_id", "subject_id", "trial_id")
        alignment_summary_keys = ("source_id", "session_id", "recording_id", "subject_id", "trial_id", "device_id")
        for sync_group, grouped_events in sync_group_groups.items():
            ordered_sync_events = sorted(grouped_events, key=lambda item: (item[1].extent.start, item[1].sequence_index if item[1].sequence_index is not None else -1))
            modalities = sorted({event.modality for _, event in ordered_sync_events})
            sources = sorted({event.source for _, event in ordered_sync_events})
            signal_types = sorted({event.signal_type for _, event in ordered_sync_events})
            alignment_values: dict[str, set[str]] = {key: set() for key in alignment_summary_keys}
            for index, event in ordered_sync_events:
                alignment = event.contextual_metadata.get("alignment")
                if not isinstance(alignment, dict):
                    continue
                for key in alignment_summary_keys:
                    normalized_value = _normalized_alignment_value(alignment.get(key))
                    if normalized_value is not None:
                        alignment_values[key].add(normalized_value)
            for key in alignment_scope_keys:
                if len(alignment_values[key]) > 1:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="inconsistent_alignment_context",
                            message=f"sync_group '{sync_group}' contains conflicting {key} values",
                            event_index=ordered_sync_events[0][0],
                            stream_id=ordered_sync_events[0][1].stream_id,
                        )
                    )
            if len(sources) > 1 and not any(alignment_values[key] for key in alignment_scope_keys):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="weak_alignment_context",
                        message="sync_group spans multiple sources without session, recording, subject, or trial identifiers",
                        event_index=ordered_sync_events[0][0],
                        stream_id=ordered_sync_events[0][1].stream_id,
                    )
                )
            sync_start = ordered_sync_events[0][1].extent.start
            sync_end = max(item[1].extent.end or item[1].extent.start for item in ordered_sync_events)
            sync_group_summaries[sync_group] = {
                "event_count": len(ordered_sync_events),
                "modalities": modalities,
                "sources": sources,
                "signal_types": signal_types,
                "time_start": serialize_timestamp(sync_start),
                "time_end": serialize_timestamp(sync_end),
                "duration_seconds": (sync_end - sync_start).total_seconds(),
                "alignment": {
                    key: sorted(values)
                    for key, values in alignment_values.items()
                    if values
                },
            }

        stream_summaries: dict[str, dict[str, JSONValue]] = {}
        for stream_id, grouped_events in stream_groups.items():
            ordered = sorted(grouped_events, key=lambda item: (item[1].extent.start, item[1].sequence_index if item[1].sequence_index is not None else -1))
            gap_count = 0
            overlap_count = 0
            previous_sample: TemporalEvent | None = None
            kind_counts: dict[str, int] = {}
            time_scales: set[str] = set()
            sync_groups: set[str] = set()
            for index, event in ordered:
                kind_counts[event.event_kind] = kind_counts.get(event.event_kind, 0) + 1
                if event.extent.time_scale is not None:
                    time_scales.add(event.extent.time_scale)
                if event.sync_group is not None:
                    sync_groups.add(event.sync_group)
                if event.event_kind != "sample":
                    continue
                if event.sequence_index is None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_sequence_index",
                            message="sample event is missing sequence_index",
                            event_index=index,
                            stream_id=stream_id,
                        )
                    )
                elif previous_sample is not None and previous_sample.sequence_index is not None and event.sequence_index <= previous_sample.sequence_index:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="non_monotonic_sequence",
                            message="sample sequence_index is not strictly increasing within stream",
                            event_index=index,
                            stream_id=stream_id,
                        )
                    )
                if previous_sample is not None and previous_sample.extent.resolution_seconds is not None:
                    expected_delta = previous_sample.extent.resolution_seconds
                    actual_delta = (event.extent.start - previous_sample.extent.start).total_seconds()
                    tolerance = max(expected_delta * 0.25, 1e-6)
                    if actual_delta > expected_delta + tolerance:
                        gap_count += 1
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="sampling_gap",
                                message="detected a temporal gap between consecutive sample events",
                                event_index=index,
                                stream_id=stream_id,
                            )
                        )
                    elif actual_delta < expected_delta - tolerance:
                        overlap_count += 1
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="sampling_overlap",
                                message="detected an overlap or duplicate spacing between consecutive sample events",
                                event_index=index,
                                stream_id=stream_id,
                            )
                        )
                previous_sample = event

            stream_start = ordered[0][1].extent.start
            stream_end = max(item[1].extent.end or item[1].extent.start for item in ordered)
            stream_summaries[stream_id] = {
                "event_count": len(ordered),
                "event_kinds": kind_counts,
                "time_scales": sorted(time_scales),
                "sync_groups": sorted(sync_groups),
                "time_start": serialize_timestamp(stream_start),
                "time_end": serialize_timestamp(stream_end),
                "duration_seconds": (stream_end - stream_start).total_seconds(),
                "gap_count": gap_count,
                "overlap_count": overlap_count,
            }

        continuity_groups: dict[str, list[tuple[int, TemporalEvent]]] = {}
        for index, event in enumerate(self.events):
            experience = event.contextual_metadata.get("experience")
            if not isinstance(experience, dict):
                continue
            continuity_id = experience.get("continuity_id")
            if isinstance(continuity_id, str) and continuity_id:
                continuity_groups.setdefault(continuity_id, []).append((index, event))

        for continuity_id, grouped_events in continuity_groups.items():
            claimed_states = {
                str(event.contextual_metadata["experience"]["continuity_state"])
                for _, event in grouped_events
                if isinstance(event.contextual_metadata.get("experience"), dict)
                and isinstance(event.contextual_metadata["experience"].get("continuity_state"), str)
            }
            if len(claimed_states) > 1:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="conflicting_continuity_state",
                        message=f"continuity_id '{continuity_id}' contains conflicting continuity_state claims",
                        event_index=grouped_events[0][0],
                        stream_id=grouped_events[0][1].stream_id,
                    )
                )
            if "continuous" not in claimed_states:
                continue
            related_stream_ids = {
                event.stream_id
                for _, event in grouped_events
                if event.stream_id in stream_summaries
            }
            if any(int(stream_summaries[stream_id].get("gap_count", 0)) > 0 for stream_id in related_stream_ids):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="unsupported_continuity_claim",
                        message=f"continuity_id '{continuity_id}' is marked continuous despite detected stream gaps",
                        event_index=grouped_events[0][0],
                        stream_id=grouped_events[0][1].stream_id,
                    )
                )

        return ValidationReport(
            total_events=len(self.events),
            issues=issues,
            stream_summaries=stream_summaries,
            sync_group_summaries=sync_group_summaries,
            time_start=min(event.extent.start for event in self.events),
            time_end=max((event.extent.end or event.extent.start) for event in self.events),
        )

    def window(self, start: datetime | str, end: datetime | str) -> "TemporalEventCollection":
        window_start = coerce_timestamp(start)
        window_end = coerce_timestamp(end)
        if window_end < window_start:
            raise ValueError("window end must be on or after window start")
        selected = [
            event
            for event in self.events
            if event.extent.start <= window_end and (event.extent.end or event.extent.start) >= window_start
        ]
        collection = TemporalEventCollection(selected)
        collection.sort_in_place()
        return collection

    def synchronization_groups(self) -> dict[str, "TemporalEventCollection"]:
        grouped: dict[str, list[TemporalEvent]] = {}
        for event in self.events:
            if event.sync_group is None:
                continue
            grouped.setdefault(event.sync_group, []).append(event)
        return {key: TemporalEventCollection.from_records([item.to_record() for item in value]) for key, value in grouped.items()}

    def materialize_intervals(self, *, event_kinds: Iterable[str] | None = None) -> list[TemporalSegment]:
        kind_filter = set(event_kinds or {"window", "episode"})
        segments: list[TemporalSegment] = []
        for event in self.events:
            if event.event_kind not in kind_filter or event.extent.end is None:
                continue
            interval_events = self.window(event.extent.start, event.extent.end).events
            label = str(event.contextual_metadata.get("annotation_label", event.signal_type))
            segments.append(
                TemporalSegment(
                    label=label,
                    start=event.extent.start,
                    end=event.extent.end,
                    events=interval_events,
                    anchor_event=event,
                    metadata={
                        "event_kind": event.event_kind,
                        "source": event.source,
                        "modality": event.modality,
                        "sync_group": event.sync_group,
                        "window_id": event.window_id,
                        "episode_id": event.episode_id,
                    },
                )
            )
        return segments

    def segment_around_markers(
        self,
        *,
        marker_signal_types: Iterable[str] | None = None,
        pre_seconds: float = 0.0,
        post_seconds: float = 0.0,
        limit: int | None = None,
    ) -> list[TemporalSegment]:
        marker_filter = set(marker_signal_types or [])
        segments: list[TemporalSegment] = []
        for event in self.events:
            if marker_filter:
                if event.signal_type not in marker_filter:
                    continue
            elif event.event_kind != "marker":
                continue
            start = event.extent.start - timedelta(seconds=pre_seconds)
            end = (event.extent.end or event.extent.start) + timedelta(seconds=post_seconds)
            label = str(event.contextual_metadata.get("annotation_label", event.value))
            segment_events = self.window(start, end).events
            segments.append(
                TemporalSegment(
                    label=label,
                    start=start,
                    end=end,
                    events=segment_events,
                    anchor_event=event,
                    metadata={
                        "marker_signal_type": event.signal_type,
                        "source": event.source,
                        "modality": event.modality,
                        "sync_group": event.sync_group,
                    },
                )
            )
            if limit is not None and len(segments) >= limit:
                break
        return segments









