from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import re

from .models import ValidationIssue, ValidationReport


TSEL_SPEC_VERSION = "1.0.0"

CORE_MODALITIES = (
    "dream",
    "eeg",
    "environment",
    "multisensory",
    "molecular_descriptor",
    "olfaction",
    "olfaction_aggregate",
    "olfaction_challenge_split",
    "olfaction_perception",
    "sleep_stage",
)

CORE_EVENT_KINDS = (
    "aggregate",
    "episode",
    "marker",
    "observation",
    "report",
    "sample",
    "transition",
    "window",
)

CORE_SIGNAL_TYPES = (
    "marker",
    "measurement",
    "state",
    "status",
    "text",
    "voltage",
)

CORE_TIME_SCALES = (
    "sample",
    "millisecond",
    "second",
    "minute",
    "hour",
    "session",
    "day",
    "epoch",
    "experiment",
)

CORE_UNITS = (
    "C",
    "Hz",
    "V",
    "a.u.",
    "event",
    "index",
    "label",
    "m/s",
    "ppm",
    "ppb",
    "score",
    "stage",
    "text",
    "uS",
    "uV",
)

CORE_ALIGNMENT_KEYS = (
    "source_id",
    "session_id",
    "recording_id",
    "subject_id",
    "trial_id",
    "device_id",
)

CORE_OBSERVATION_STATUSES = (
    "observed",
    "partial",
    "missing",
    "inferred",
    "imputed",
    "derived",
)

CORE_CONTINUITY_STATES = (
    "continuous",
    "interrupted",
    "fragmented",
    "reconstructed",
    "unknown",
)

CORE_PRIMARY_SENSES = (
    "vision",
    "audition",
    "olfaction",
    "gustation",
    "somatosensation",
)

CORE_LATERALITY = (
    "left",
    "right",
    "midline",
    "bilateral",
    "diffuse",
    "unknown",
)

CORE_TRAJECTORY_ROLES = (
    "baseline",
    "stimulus",
    "response",
    "report",
    "context",
    "aftereffect",
)

CORE_DELIVERY_STATES = (
    "prepared",
    "presented",
    "active",
    "maintained",
    "removed",
    "residual",
    "reported",
    "unknown",
)

CORE_RELATION_TYPES = (
    "part_of",
    "precedes",
    "follows",
    "overlaps",
    "caused_by",
    "evoked_by",
    "reported_by",
    "synchronized_with",
    "measured_by",
    "belongs_to",
    "describes",
)

CORE_TRANSFORM_STAGES = (
    "raw",
    "normalized",
    "segmented",
    "derived",
    "inferred",
    "annotated",
)

CORE_EXPERIENCE_PHASES = (
    "baseline",
    "anticipation",
    "onset",
    "rise",
    "peak",
    "sustain",
    "decay",
    "offset",
    "aftereffect",
    "report",
    "recovery",
)

SENSORY_PROFILES: dict[str, dict[str, Any]] = {
    "generic": {
        "label": "Generic",
        "description": "Modality-agnostic sensory ingestion routed into the unified temporal layer.",
        "modalities": (),
        "adapters": ("csv", "json", "timeseries_csv", "timeseries_json", "edf"),
    },
    "eeg": {
        "label": "EEG",
        "description": "Electrical brain activity, sleep-stage annotations, and related recording streams.",
        "modalities": ("eeg", "sleep_stage"),
        "adapters": ("csv", "json", "timeseries_csv", "timeseries_json", "edf"),
    },
    "olfaction": {
        "label": "Olfaction",
        "description": "Chemical sensing, odor presentation, and olfactory perception records.",
        "modalities": (
            "olfaction",
            "olfaction_aggregate",
            "olfaction_challenge_split",
            "olfaction_perception",
            "molecular_descriptor",
        ),
        "adapters": ("csv", "json", "timeseries_csv", "timeseries_json"),
    },
    "dream": {
        "label": "Dream",
        "description": "Dream reports and related narrative sleep-state data.",
        "modalities": ("dream",),
        "adapters": ("csv", "json"),
    },
    "environment": {
        "label": "Environment",
        "description": "Environmental or apparatus-state measurements synchronized to experimental time.",
        "modalities": ("environment",),
        "adapters": ("csv", "json", "timeseries_csv", "timeseries_json"),
    },
    "multisensory": {
        "label": "Multisensory",
        "description": "Cross-modal or mixed sensor matrices aligned inside one temporal envelope.",
        "modalities": ("multisensory",),
        "adapters": ("csv", "json", "timeseries_csv", "timeseries_json", "edf"),
    },
}

MODALITY_ALIASES = {
    "electroencephalography": "eeg",
    "gas_sensor": "olfaction",
    "gas-sensor": "olfaction",
    "molecular": "molecular_descriptor",
    "sleep-stage": "sleep_stage",
}

EVENT_KIND_ALIASES = {
    "annotation": "marker",
    "annotations": "marker",
    "interval": "window",
    "state_change": "transition",
}

SIGNAL_TYPE_ALIASES = {
    "annotation": "marker",
    "annotations": "marker",
    "sleep stage": "sleep_stage",
    "sleep-stage": "sleep_stage",
    "text_report": "text",
}

UNIT_ALIASES = {
    "au": "a.u.",
    "celsius": "C",
    "deg_c": "C",
    "microvolt": "uV",
    "microvolts": "uV",
    "microsiemens": "uS",
    "uv": "uV",
    "\u00b5v": "uV",
    "\u03bcv": "uV",
}

PHASE_ALIASES = {
    "pre_exposure": "anticipation",
    "pre-exposure": "anticipation",
    "start": "onset",
    "begin": "onset",
    "rising": "rise",
    "max": "peak",
    "plateau": "sustain",
    "wane": "decay",
    "waning": "decay",
    "end": "offset",
    "post_exposure": "aftereffect",
    "post-exposure": "aftereffect",
}

SENSE_ALIASES = {
    "sight": "vision",
    "visual": "vision",
    "hearing": "audition",
    "audio": "audition",
    "sound": "audition",
    "smell": "olfaction",
    "olfactory": "olfaction",
    "taste": "gustation",
    "gustatory": "gustation",
    "touch": "somatosensation",
    "tactile": "somatosensation",
    "somatic": "somatosensation",
}

LATERALITY_ALIASES = {
    "both": "bilateral",
    "center": "midline",
    "centre": "midline",
    "central": "midline",
}

TRAJECTORY_ROLE_ALIASES = {
    "stimulus_window": "stimulus",
    "post_effect": "aftereffect",
    "posteffect": "aftereffect",
}

DELIVERY_STATE_ALIASES = {
    "on": "active",
    "off": "removed",
    "present": "presented",
    "presentation": "presented",
    "maintain": "maintained",
    "post": "residual",
}

RELATION_TYPE_ALIASES = {
    "partof": "part_of",
    "synced_with": "synchronized_with",
    "sync_with": "synchronized_with",
    "described_by": "reported_by",
}

TRANSFORM_STAGE_ALIASES = {
    "normalised": "normalized",
}

PROFILE_ALIASES = {
    "ecog": "eeg",
    "electroencephalography": "eeg",
    "gas_sensor": "olfaction",
    "gas-sensor": "olfaction",
    "odor": "olfaction",
    "sleep": "eeg",
}

_TOKEN_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_ALIGNMENT_SCOPE_KEYS = ("session_id", "recording_id", "subject_id", "trial_id")


def _canonical_token(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def normalize_modality(value: str) -> str:
    token = _canonical_token(value)
    return MODALITY_ALIASES.get(token, token)


def normalize_event_kind(value: str) -> str:
    token = _canonical_token(value)
    return EVENT_KIND_ALIASES.get(token, token)


def normalize_signal_type(value: str) -> str:
    raw = value.strip()
    token = _canonical_token(raw)
    alias = SIGNAL_TYPE_ALIASES.get(token)
    return alias or raw


def normalize_unit(value: str) -> str:
    token = value.strip()
    alias = UNIT_ALIASES.get(_canonical_token(token))
    return alias or token


def normalize_phase(value: str) -> str:
    token = _canonical_token(value)
    return PHASE_ALIASES.get(token, token)


def normalize_primary_sense(value: str) -> str:
    token = _canonical_token(value)
    return SENSE_ALIASES.get(token, token)


def normalize_laterality(value: str) -> str:
    token = _canonical_token(value)
    return LATERALITY_ALIASES.get(token, token)


def normalize_trajectory_role(value: str) -> str:
    token = _canonical_token(value)
    return TRAJECTORY_ROLE_ALIASES.get(token, token)


def normalize_delivery_state(value: str) -> str:
    token = _canonical_token(value)
    return DELIVERY_STATE_ALIASES.get(token, token)


def normalize_relation_type(value: str) -> str:
    token = _canonical_token(value)
    return RELATION_TYPE_ALIASES.get(token, token)


def normalize_transform_stage(value: str) -> str:
    token = _canonical_token(value)
    return TRANSFORM_STAGE_ALIASES.get(token, token)


def normalize_sensory_profile(value: str) -> str:
    token = _canonical_token(value)
    normalized = PROFILE_ALIASES.get(token, token)
    if normalized not in SENSORY_PROFILES:
        raise ValueError(f"unsupported sensory profile: {value}")
    return normalized


def available_sensory_profiles() -> list[str]:
    return list(SENSORY_PROFILES.keys())


def is_extension_token(value: str) -> bool:
    return bool(_TOKEN_PATTERN.match(value))


def _profile_snapshot() -> dict[str, Any]:
    return {
        name: {
            "label": profile["label"],
            "description": profile["description"],
            "modalities": list(profile["modalities"]),
            "adapters": list(profile["adapters"]),
        }
        for name, profile in SENSORY_PROFILES.items()
    }


def _infer_modality_from_config(config_data: dict[str, Any]) -> str | None:
    if "mapping" in config_data and isinstance(config_data["mapping"], dict):
        modality_spec = config_data["mapping"].get("modality")
        if isinstance(modality_spec, dict) and "value" in modality_spec:
            return str(modality_spec["value"])
        return None
    modality_spec = config_data.get("modality")
    if isinstance(modality_spec, dict):
        if "value" in modality_spec:
            return str(modality_spec["value"])
        return None
    if modality_spec is not None:
        return str(modality_spec)
    adapter = str(config_data.get("adapter", ""))
    if adapter == "edf":
        return "eeg"
    return None


def _infer_primary_sense_from_config(config_data: dict[str, Any]) -> str | None:
    context_block: dict[str, Any] | None = None
    if "mapping" in config_data and isinstance(config_data["mapping"], dict):
        context_spec = config_data["mapping"].get("context")
        if isinstance(context_spec, dict):
            static_context = context_spec.get("static")
            if isinstance(static_context, dict):
                context_block = static_context
    elif isinstance(config_data.get("context"), dict):
        context_block = dict(config_data["context"])

    if not isinstance(context_block, dict):
        return None
    sensory = context_block.get("sensory")
    if isinstance(sensory, dict) and sensory.get("primary_sense") is not None:
        return normalize_primary_sense(str(sensory["primary_sense"]))
    domain_profile = context_block.get("domain_profile")
    if isinstance(domain_profile, dict) and domain_profile.get("domain") is not None:
        return _canonical_token(str(domain_profile["domain"]))
    return None


def infer_sensory_profile(config_data: dict[str, Any]) -> str:
    explicit = config_data.get("sensory_profile")
    if explicit is not None:
        return normalize_sensory_profile(str(explicit))
    primary_sense = _infer_primary_sense_from_config(config_data)
    if primary_sense in SENSORY_PROFILES:
        return str(primary_sense)
    modality = _infer_modality_from_config(config_data)
    if modality is None:
        return "generic"
    normalized_modality = normalize_modality(modality)
    for profile_name, profile in SENSORY_PROFILES.items():
        if normalized_modality in profile["modalities"]:
            return profile_name
    return "generic"


def validate_sensory_profile(config_data: dict[str, Any], profile: str) -> None:
    normalized_profile = normalize_sensory_profile(profile)
    profile_spec = SENSORY_PROFILES[normalized_profile]
    adapter = str(config_data.get("adapter", ""))
    if adapter and adapter not in profile_spec["adapters"]:
        raise ValueError(f"adapter '{adapter}' is not supported by sensory profile '{normalized_profile}'")
    modality = _infer_modality_from_config(config_data)
    if modality is None or normalized_profile == "generic":
        return
    normalized_modality = normalize_modality(modality)
    allowed_modalities = set(profile_spec["modalities"])
    if allowed_modalities and normalized_modality in allowed_modalities:
        return
    primary_sense = _infer_primary_sense_from_config(config_data)
    if primary_sense == normalized_profile:
        return
    raise ValueError(
        f"sensory profile '{normalized_profile}' is incompatible with modality '{normalized_modality}'"
    )


def vocabulary_snapshot() -> dict[str, Any]:
    return {
        "spec_version": TSEL_SPEC_VERSION,
        "modalities": list(CORE_MODALITIES),
        "event_kinds": list(CORE_EVENT_KINDS),
        "signal_types": list(CORE_SIGNAL_TYPES),
        "time_scales": list(CORE_TIME_SCALES),
        "observation_statuses": list(CORE_OBSERVATION_STATUSES),
        "continuity_states": list(CORE_CONTINUITY_STATES),
        "primary_senses": list(CORE_PRIMARY_SENSES),
        "laterality": list(CORE_LATERALITY),
        "trajectory_roles": list(CORE_TRAJECTORY_ROLES),
        "delivery_states": list(CORE_DELIVERY_STATES),
        "relation_types": list(CORE_RELATION_TYPES),
        "transform_stages": list(CORE_TRANSFORM_STAGES),
        "experience_phases": list(CORE_EXPERIENCE_PHASES),
        "units": list(CORE_UNITS),
        "alignment_keys": list(CORE_ALIGNMENT_KEYS),
        "sensory_profiles": _profile_snapshot(),
        "aliases": {
            "modalities": dict(MODALITY_ALIASES),
            "event_kinds": dict(EVENT_KIND_ALIASES),
            "signal_types": dict(SIGNAL_TYPE_ALIASES),
            "units": dict(UNIT_ALIASES),
            "phases": dict(PHASE_ALIASES),
            "primary_senses": dict(SENSE_ALIASES),
            "laterality": dict(LATERALITY_ALIASES),
            "trajectory_roles": dict(TRAJECTORY_ROLE_ALIASES),
            "delivery_states": dict(DELIVERY_STATE_ALIASES),
            "relation_types": dict(RELATION_TYPE_ALIASES),
            "transform_stages": dict(TRANSFORM_STAGE_ALIASES),
            "sensory_profiles": dict(PROFILE_ALIASES),
        },
    }


def event_schema() -> dict[str, Any]:
    alignment_properties = {
        key: {"type": ["string", "null"]}
        for key in CORE_ALIGNMENT_KEYS
    }
    completeness_properties = {
        "observation_status": {"type": ["string", "null"]},
        "completeness_score": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
        "missing_dimensions": {"type": "array", "items": {"type": "string"}},
        "inferred_fields": {"type": "array", "items": {"type": "string"}},
        "future_inference_allowed": {"type": ["boolean", "null"]},
    }
    experience_properties = {
        "experience_id": {"type": ["string", "null"]},
        "continuity_id": {"type": ["string", "null"]},
        "continuity_index": {"type": ["integer", "null"]},
        "continuity_state": {"type": ["string", "null"]},
    }
    sensory_properties = {
        "primary_sense": {"type": ["string", "null"]},
        "submodality": {"type": ["string", "null"]},
        "body_site": {"type": ["string", "null"]},
        "laterality": {"type": ["string", "null"]},
        "receptor_pathway": {"type": ["string", "null"]},
        "trajectory_role": {"type": ["string", "null"]},
    }
    acquisition_properties = {
        "acquisition_profile": {"type": ["string", "null"]},
        "device_class": {"type": ["string", "null"]},
        "instrument": {"type": ["string", "null"]},
        "channel": {"type": ["string", "null"]},
        "sample_rate_hz": {"type": ["number", "null"], "exclusiveMinimum": 0},
        "transform_stage": {"type": ["string", "null"]},
    }
    stimulus_properties = {
        "stimulus_id": {"type": ["string", "null"]},
        "stimulus_label": {"type": ["string", "null"]},
        "stimulus_object": {"type": ["string", "null"]},
        "presentation_phase": {"type": ["string", "null"]},
        "delivery_state": {"type": ["string", "null"]},
        "intensity_estimate": {"type": ["number", "null"]},
        "intensity_unit": {"type": ["string", "null"]},
    }
    domain_profile_properties = {
        "domain": {"type": ["string", "null"]},
        "profile_id": {"type": ["string", "null"]},
        "profile_version": {"type": ["string", "null"]},
        "resolution_status": {"type": ["string", "null"]},
        "evidence_signatures": {"type": "array", "items": {"type": "string"}},
        "candidate_profiles": {"type": "array", "items": {"type": "string"}},
        "missing_metadata": {"type": "array", "items": {"type": "string"}},
    }
    relation_properties = {
        "relation_type": {"type": "string"},
        "target_id": {"type": "string"},
        "target_type": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://tsel.dev/schema/tsel-event-1.0.0.json",
        "title": "TSEL Event",
        "type": "object",
        "required": [
            "timestamp",
            "modality",
            "source",
            "signal_type",
            "value",
            "unit",
            "contextual_metadata",
        ],
        "additionalProperties": False,
        "properties": {
            "timestamp": {"type": "string", "format": "date-time"},
            "modality": {"type": "string"},
            "source": {"type": "string", "minLength": 1},
            "signal_type": {"type": "string", "minLength": 1},
            "value": {},
            "unit": {"type": "string", "minLength": 1},
            "contextual_metadata": {
                "type": "object",
                "properties": {
                    "alignment": {
                        "type": "object",
                        "properties": alignment_properties,
                        "additionalProperties": True,
                    },
                    "completeness": {
                        "type": "object",
                        "properties": completeness_properties,
                        "additionalProperties": True,
                    },
                    "experience": {
                        "type": "object",
                        "properties": experience_properties,
                        "additionalProperties": True,
                    },
                    "sensory": {
                        "type": "object",
                        "properties": sensory_properties,
                        "additionalProperties": True,
                    },
                    "acquisition": {
                        "type": "object",
                        "properties": acquisition_properties,
                        "additionalProperties": True,
                    },
                    "stimulus": {
                        "type": "object",
                        "properties": stimulus_properties,
                        "additionalProperties": True,
                    },
                    "domain_profile": {
                        "type": "object",
                        "properties": domain_profile_properties,
                        "additionalProperties": True,
                    },
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["relation_type", "target_id"],
                            "properties": relation_properties,
                            "additionalProperties": True,
                        },
                    },
                    "temporal": {
                        "type": "object",
                        "required": ["start", "anchor", "event_kind", "stream_id", "schema_version"],
                        "properties": {
                            "start": {"type": "string", "format": "date-time"},
                            "end": {"type": ["string", "null"], "format": "date-time"},
                            "anchor": {"type": "string"},
                            "duration_seconds": {"type": ["number", "null"]},
                            "resolution_seconds": {"type": ["number", "null"]},
                            "uncertainty_seconds": {"type": ["number", "null"]},
                            "time_scale": {"type": ["string", "null"]},
                            "event_kind": {"type": "string"},
                            "stream_id": {"type": "string", "minLength": 1},
                            "sequence_index": {"type": ["integer", "null"]},
                            "confidence": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
                            "phase": {"type": ["string", "null"]},
                            "sync_group": {"type": ["string", "null"]},
                            "window_id": {"type": ["string", "null"]},
                            "episode_id": {"type": ["string", "null"]},
                            "transition_from": {},
                            "transition_to": {},
                            "schema_version": {"type": "string"},
                        },
                        "additionalProperties": True,
                    }
                },
                "additionalProperties": True,
            },
        },
    }


def bundle_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://tsel.dev/schema/tsel-bundle-1.0.0.json",
        "title": "TSEL Bundle",
        "type": "object",
        "required": ["spec_version", "event_count", "events"],
        "additionalProperties": False,
        "properties": {
            "spec_version": {"type": "string"},
            "event_count": {"type": "integer", "minimum": 0},
            "generated_at": {"type": ["string", "null"], "format": "date-time"},
            "summary": {"type": "object"},
            "events": {"type": "array", "items": event_schema()},
        },
    }


def standard_assets() -> dict[str, Any]:
    return {
        "vocabulary.json": vocabulary_snapshot(),
        "tsel-event.schema.json": event_schema(),
        "tsel-bundle.schema.json": bundle_schema(),
    }


def write_standard_assets(output_dir: str | Path) -> list[Path]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for file_name, payload in standard_assets().items():
        path = target_dir / file_name
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


@dataclass(slots=True)
class ConformanceReport:
    spec_version: str
    total_events: int
    issues: list[ValidationIssue] = field(default_factory=list)
    temporal_validation: ValidationReport | None = None

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def is_conformant(self) -> bool:
        temporal_valid = True if self.temporal_validation is None else self.temporal_validation.is_valid
        return temporal_valid and self.error_count == 0

    def to_record(self) -> dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "total_events": self.total_events,
            "is_conformant": self.is_conformant,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "temporal_validation": None if self.temporal_validation is None else self.temporal_validation.to_record(),
            "issues": [issue.to_record() for issue in self.issues],
        }


def _normalized_alignment_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        normalized = str(value).strip()
        return normalized or None
    raise TypeError("alignment values must be primitive")


def evaluate_conformance(records: list[dict[str, Any]], temporal_validation: ValidationReport | None = None) -> ConformanceReport:
    issues: list[ValidationIssue] = []
    sync_groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}

    for index, record in enumerate(records):
        missing_fields = {"timestamp", "modality", "source", "signal_type", "value", "unit", "contextual_metadata"} - set(record.keys())
        if missing_fields:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_required_fields",
                    message=f"event is missing required fields: {sorted(missing_fields)}",
                    event_index=index,
                )
            )
            continue

        contextual_metadata = record.get("contextual_metadata")
        if not isinstance(contextual_metadata, dict):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_contextual_metadata",
                    message="contextual_metadata must be an object",
                    event_index=index,
                )
            )
            continue

        temporal = contextual_metadata.get("temporal")
        if not isinstance(temporal, dict):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="missing_temporal_metadata",
                    message="event is missing contextual_metadata.temporal",
                    event_index=index,
                )
            )
            continue

        assertion_basis = contextual_metadata.get("assertion_basis")
        if assertion_basis is not None and not isinstance(assertion_basis, dict):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_assertion_basis_context",
                    message="contextual_metadata.assertion_basis must be an object when provided",
                    event_index=index,
                )
            )
            assertion_basis = {}
        elif not isinstance(assertion_basis, dict):
            assertion_basis = {}
        unresolved = contextual_metadata.get("unresolved")
        if unresolved is not None and not isinstance(unresolved, dict):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_unresolved_context",
                    message="contextual_metadata.unresolved must be an object when provided",
                    event_index=index,
                )
            )
            unresolved = {}
        elif not isinstance(unresolved, dict):
            unresolved = {}
        for field_path, basis in assertion_basis.items():
            if not isinstance(field_path, str) or not field_path.strip() or not isinstance(basis, str) or not basis.strip():
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_assertion_basis_entry",
                        message="assertion_basis must map non-empty field paths to non-empty strings",
                        event_index=index,
                    )
                )
                continue
            if _canonical_token(basis) not in {"source_provided", "packet_declared", "directly_observed", "deterministically_derived", "unresolved"}:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="unsupported_assertion_basis",
                        message=f"assertion basis '{basis}' is not supported",
                        event_index=index,
                    )
                )
        for field_path, reason in unresolved.items():
            if not isinstance(field_path, str) or not field_path.strip() or not isinstance(reason, str) or not reason.strip():
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_unresolved_entry",
                        message="unresolved must map non-empty field paths to non-empty strings",
                        event_index=index,
                    )
                )
                continue
            if assertion_basis.get(field_path) != "unresolved":
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="inconsistent_unresolved_basis",
                        message=f"unresolved field '{field_path}' should declare assertion_basis 'unresolved'",
                        event_index=index,
                    )
                )

        if temporal.get("schema_version") != TSEL_SPEC_VERSION:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="schema_version_mismatch",
                    message=f"expected schema_version '{TSEL_SPEC_VERSION}'",
                    event_index=index,
                )
            )

        modality = normalize_modality(str(record["modality"]))
        if modality not in CORE_MODALITIES and not is_extension_token(modality):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="noncanonical_modality",
                    message=f"modality '{record['modality']}' is not canonical or extension-safe",
                    event_index=index,
                )
            )

        event_kind = normalize_event_kind(str(temporal.get("event_kind", "")))
        if event_kind not in CORE_EVENT_KINDS and not is_extension_token(event_kind):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="noncanonical_event_kind",
                    message=f"event_kind '{temporal.get('event_kind')}' is not canonical or extension-safe",
                    event_index=index,
                )
            )

        signal_type = normalize_signal_type(str(record["signal_type"]))
        canonical_signal_type = _canonical_token(signal_type)
        if canonical_signal_type not in CORE_SIGNAL_TYPES and not is_extension_token(canonical_signal_type):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="noncanonical_signal_type",
                    message=f"signal_type '{record['signal_type']}' is not canonical or extension-safe",
                    event_index=index,
                )
            )

        unit = normalize_unit(str(record["unit"]))
        if unit not in CORE_UNITS and not is_extension_token(_canonical_token(unit)):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="noncanonical_unit",
                    message=f"unit '{record['unit']}' is not canonical or extension-safe",
                    event_index=index,
                )
            )

        time_scale = temporal.get("time_scale")
        if time_scale is not None:
            normalized_time_scale = _canonical_token(str(time_scale))
            if normalized_time_scale not in CORE_TIME_SCALES and not is_extension_token(normalized_time_scale):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="noncanonical_time_scale",
                        message=f"time_scale '{time_scale}' is not canonical or extension-safe",
                        event_index=index,
                    )
                )

        phase = temporal.get("phase")
        if phase is not None:
            normalized_phase = normalize_phase(str(phase))
            if normalized_phase not in CORE_EXPERIENCE_PHASES and not is_extension_token(normalized_phase):
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="noncanonical_phase",
                        message=f"phase '{phase}' is not canonical or extension-safe",
                        event_index=index,
                    )
                )

        alignment = contextual_metadata.get("alignment")
        if alignment is not None:
            if not isinstance(alignment, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_alignment_context",
                        message="contextual_metadata.alignment must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                for key, value in alignment.items():
                    normalized_key = _canonical_token(str(key))
                    if normalized_key not in CORE_ALIGNMENT_KEYS and not is_extension_token(normalized_key):
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="noncanonical_alignment_key",
                                message=f"alignment key '{key}' is not canonical or extension-safe",
                                event_index=index,
                            )
                        )
                    try:
                        _normalized_alignment_value(value)
                    except TypeError:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_alignment_value",
                                message=f"alignment value for '{key}' must be primitive",
                                event_index=index,
                            )
                        )

        completeness = contextual_metadata.get("completeness")
        if completeness is not None:
            if not isinstance(completeness, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_completeness_context",
                        message="contextual_metadata.completeness must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                observation_status = completeness.get("observation_status")
                normalized_status = None if observation_status is None else _canonical_token(str(observation_status))
                if normalized_status is not None and normalized_status not in CORE_OBSERVATION_STATUSES and not is_extension_token(normalized_status):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_observation_status",
                            message=f"observation_status '{observation_status}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )
                completeness_score = completeness.get("completeness_score")
                if completeness_score is not None:
                    try:
                        completeness_score = float(completeness_score)
                    except (TypeError, ValueError):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_completeness_score",
                                message="completeness_score must be numeric when provided",
                                event_index=index,
                            )
                        )
                    else:
                        if not 0.0 <= completeness_score <= 1.0:
                            issues.append(
                                ValidationIssue(
                                    severity="error",
                                    code="invalid_completeness_score",
                                    message="completeness_score must be between 0.0 and 1.0",
                                    event_index=index,
                                )
                            )
                for field_name in ("missing_dimensions", "inferred_fields"):
                    values = completeness.get(field_name)
                    if values is None:
                        continue
                    if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_completeness_fields",
                                message=f"{field_name} must be a list of non-empty strings",
                                event_index=index,
                            )
                        )
                future_inference_allowed = completeness.get("future_inference_allowed")
                if future_inference_allowed is not None and not isinstance(future_inference_allowed, bool):
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="invalid_future_inference_flag",
                            message="future_inference_allowed must be boolean when provided",
                            event_index=index,
                        )
                    )
                missing_dimensions = completeness.get("missing_dimensions") or []
                inferred_fields = completeness.get("inferred_fields") or []
                if normalized_status in {"partial", "missing"} and not missing_dimensions:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_missing_dimensions",
                            message="partial or missing observations should declare missing_dimensions",
                            event_index=index,
                        )
                    )
                if normalized_status in {"inferred", "imputed", "derived"} and not inferred_fields:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="missing_inferred_fields",
                            message="inferred observations should declare inferred_fields",
                            event_index=index,
                        )
                    )

        experience = contextual_metadata.get("experience")
        if experience is not None:
            if not isinstance(experience, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_experience_context",
                        message="contextual_metadata.experience must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                continuity_state = experience.get("continuity_state")
                normalized_continuity_state = None if continuity_state is None else _canonical_token(str(continuity_state))
                if normalized_continuity_state is not None and normalized_continuity_state not in CORE_CONTINUITY_STATES and not is_extension_token(normalized_continuity_state):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_continuity_state",
                            message=f"continuity_state '{continuity_state}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )
                continuity_index = experience.get("continuity_index")
                if continuity_index is not None:
                    if not isinstance(continuity_index, int):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_continuity_index",
                                message="continuity_index must be an integer when provided",
                                event_index=index,
                            )
                        )
                    elif continuity_index < 0:
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_continuity_index",
                                message="continuity_index must be non-negative",
                                event_index=index,
                            )
                        )
                    if experience.get("continuity_id") is None:
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="missing_continuity_id",
                                message="continuity_index should be paired with a continuity_id",
                                event_index=index,
                            )
                        )

        sensory = contextual_metadata.get("sensory")
        if sensory is not None:
            if not isinstance(sensory, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_sensory_context",
                        message="contextual_metadata.sensory must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                primary_sense = sensory.get("primary_sense")
                normalized_primary_sense = None if primary_sense is None else normalize_primary_sense(str(primary_sense))
                if normalized_primary_sense is not None and normalized_primary_sense not in CORE_PRIMARY_SENSES:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_primary_sense",
                            message=f"primary_sense '{primary_sense}' is not one of the five canonical senses",
                            event_index=index,
                        )
                    )
                laterality = sensory.get("laterality")
                normalized_laterality = None if laterality is None else normalize_laterality(str(laterality))
                if normalized_laterality is not None and normalized_laterality not in CORE_LATERALITY and not is_extension_token(normalized_laterality):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_laterality",
                            message=f"laterality '{laterality}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )
                trajectory_role = sensory.get("trajectory_role")
                normalized_trajectory_role = None if trajectory_role is None else normalize_trajectory_role(str(trajectory_role))
                if normalized_trajectory_role is not None and normalized_trajectory_role not in CORE_TRAJECTORY_ROLES and not is_extension_token(normalized_trajectory_role):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_trajectory_role",
                            message=f"trajectory_role '{trajectory_role}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )
                for field_name in ("submodality", "body_site", "receptor_pathway"):
                    value = sensory.get(field_name)
                    if value is None:
                        continue
                    normalized_value = _canonical_token(str(value))
                    if not is_extension_token(normalized_value):
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="noncanonical_sensory_field",
                                message=f"{field_name} '{value}' is not extension-safe",
                                event_index=index,
                            )
                        )

        acquisition = contextual_metadata.get("acquisition")
        if acquisition is not None:
            if not isinstance(acquisition, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_acquisition_context",
                        message="contextual_metadata.acquisition must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                for field_name in ("acquisition_profile", "device_class", "instrument", "channel"):
                    value = acquisition.get(field_name)
                    if value is None:
                        continue
                    normalized_value = _canonical_token(str(value))
                    if not is_extension_token(normalized_value):
                        issues.append(
                            ValidationIssue(
                                severity="warning",
                                code="noncanonical_acquisition_field",
                                message=f"{field_name} '{value}' is not extension-safe",
                                event_index=index,
                            )
                        )
                sample_rate_hz = acquisition.get("sample_rate_hz")
                if sample_rate_hz is not None:
                    try:
                        sample_rate_hz = float(sample_rate_hz)
                    except (TypeError, ValueError):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_sample_rate_hz",
                                message="sample_rate_hz must be numeric when provided",
                                event_index=index,
                            )
                        )
                    else:
                        if sample_rate_hz <= 0:
                            issues.append(
                                ValidationIssue(
                                    severity="error",
                                    code="invalid_sample_rate_hz",
                                    message="sample_rate_hz must be positive",
                                    event_index=index,
                                )
                            )
                transform_stage = acquisition.get("transform_stage")
                normalized_transform_stage = None if transform_stage is None else normalize_transform_stage(str(transform_stage))
                if normalized_transform_stage is not None and normalized_transform_stage not in CORE_TRANSFORM_STAGES and not is_extension_token(normalized_transform_stage):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_transform_stage",
                            message=f"transform_stage '{transform_stage}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )

        stimulus = contextual_metadata.get("stimulus")
        if stimulus is not None:
            if not isinstance(stimulus, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_stimulus_context",
                        message="contextual_metadata.stimulus must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                presentation_phase = stimulus.get("presentation_phase")
                normalized_presentation_phase = None if presentation_phase is None else normalize_phase(str(presentation_phase))
                if normalized_presentation_phase is not None and normalized_presentation_phase not in CORE_EXPERIENCE_PHASES and not is_extension_token(normalized_presentation_phase):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_presentation_phase",
                            message=f"presentation_phase '{presentation_phase}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )
                delivery_state = stimulus.get("delivery_state")
                normalized_delivery_state = None if delivery_state is None else normalize_delivery_state(str(delivery_state))
                if normalized_delivery_state is not None and normalized_delivery_state not in CORE_DELIVERY_STATES and not is_extension_token(normalized_delivery_state):
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="noncanonical_delivery_state",
                            message=f"delivery_state '{delivery_state}' is not canonical or extension-safe",
                            event_index=index,
                        )
                    )
                intensity_estimate = stimulus.get("intensity_estimate")
                if intensity_estimate is not None:
                    try:
                        float(intensity_estimate)
                    except (TypeError, ValueError):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_intensity_estimate",
                                message="intensity_estimate must be numeric when provided",
                                event_index=index,
                            )
                        )

        domain_profile = contextual_metadata.get("domain_profile")
        if domain_profile is not None:
            if not isinstance(domain_profile, dict):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_domain_profile_context",
                        message="contextual_metadata.domain_profile must be an object when provided",
                        event_index=index,
                    )
                )
            else:
                resolution_status = domain_profile.get("resolution_status")
                normalized_resolution_status = None if resolution_status is None else _canonical_token(str(resolution_status))
                if normalized_resolution_status is not None and normalized_resolution_status not in {"resolved", "partial", "ambiguous", "unresolved"}:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="invalid_domain_profile_status",
                            message=f"domain_profile resolution_status '{resolution_status}' is not supported",
                            event_index=index,
                        )
                    )
                profile_id = domain_profile.get("profile_id")
                if normalized_resolution_status == "resolved" and profile_id is None:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            code="missing_domain_profile_id",
                            message="resolved domain_profile claims require profile_id",
                            event_index=index,
                        )
                    )
                if normalized_resolution_status in {"ambiguous", "unresolved"} and profile_id is not None:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="conflicting_domain_profile_status",
                            message="ambiguous or unresolved domain_profile claims should not also populate profile_id",
                            event_index=index,
                        )
                    )

        relations = contextual_metadata.get("relations")
        if relations is not None:
            if not isinstance(relations, list):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_relations_context",
                        message="contextual_metadata.relations must be an array when provided",
                        event_index=index,
                    )
                )
            else:
                for relation_index, relation in enumerate(relations):
                    if not isinstance(relation, dict):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="invalid_relation_record",
                                message=f"relation at index {relation_index} must be an object",
                                event_index=index,
                            )
                        )
                        continue
                    relation_type = relation.get("relation_type")
                    target_id = relation.get("target_id")
                    if not isinstance(relation_type, str) or not relation_type.strip():
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="missing_relation_type",
                                message=f"relation at index {relation_index} is missing relation_type",
                                event_index=index,
                            )
                        )
                    else:
                        normalized_relation_type = normalize_relation_type(relation_type)
                        if normalized_relation_type not in CORE_RELATION_TYPES and not is_extension_token(normalized_relation_type):
                            issues.append(
                                ValidationIssue(
                                    severity="warning",
                                    code="noncanonical_relation_type",
                                    message=f"relation_type '{relation_type}' is not canonical or extension-safe",
                                    event_index=index,
                                )
                            )
                    if not isinstance(target_id, str) or not target_id.strip():
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                code="missing_relation_target",
                                message=f"relation at index {relation_index} is missing target_id",
                                event_index=index,
                            )
                        )
                    confidence = relation.get("confidence")
                    if confidence is not None:
                        try:
                            confidence = float(confidence)
                        except (TypeError, ValueError):
                            issues.append(
                                ValidationIssue(
                                    severity="error",
                                    code="invalid_relation_confidence",
                                    message="relation confidence must be numeric when provided",
                                    event_index=index,
                                )
                            )
                        else:
                            if not 0.0 <= confidence <= 1.0:
                                issues.append(
                                    ValidationIssue(
                                        severity="error",
                                        code="invalid_relation_confidence",
                                        message="relation confidence must be between 0.0 and 1.0",
                                        event_index=index,
                                    )
                                )

        if phase is not None:
            phase_basis = assertion_basis.get("temporal.phase")
            if phase_basis is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_phase_basis",
                        message="phase claims should declare assertion_basis.temporal.phase",
                        event_index=index,
                    )
                )
            elif _canonical_token(str(phase_basis)) == "unresolved":
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="conflicting_phase_basis",
                        message="temporal.phase cannot be populated while assertion_basis.temporal.phase is unresolved",
                        event_index=index,
                    )
                )

        if isinstance(acquisition, dict) and acquisition.get("acquisition_profile") is not None and assertion_basis.get("acquisition.acquisition_profile") is None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="missing_acquisition_basis",
                    message="acquisition_profile should declare assertion_basis.acquisition.acquisition_profile",
                    event_index=index,
                )
            )
        if isinstance(experience, dict) and experience.get("continuity_state") is not None and assertion_basis.get("experience.continuity_state") is None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="missing_continuity_basis",
                    message="continuity_state should declare assertion_basis.experience.continuity_state",
                    event_index=index,
                )
            )
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
                        )
                    )
        if isinstance(domain_profile, dict):
            if domain_profile.get("profile_id") is not None and assertion_basis.get("domain_profile.profile_id") is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_domain_profile_basis",
                        message="domain_profile.profile_id should declare assertion_basis.domain_profile.profile_id",
                        event_index=index,
                    )
                )
            if domain_profile.get("resolution_status") is not None and assertion_basis.get("domain_profile.resolution_status") is None:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="missing_domain_profile_basis",
                        message="domain_profile.resolution_status should declare assertion_basis.domain_profile.resolution_status",
                        event_index=index,
                    )
                )
        if isinstance(relations, list) and relations and assertion_basis.get("relations") is None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="missing_relation_basis",
                    message="relation claims should declare assertion_basis.relations",
                    event_index=index,
                )
            )

        if event_kind == "transition":
            if "transition_from" not in temporal or "transition_to" not in temporal:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="invalid_transition_event",
                        message="transition events require transition_from and transition_to",
                        event_index=index,
                    )
                )

        if event_kind in {"window", "episode"} and temporal.get("end") is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_interval_event",
                    message=f"{event_kind} events require an end timestamp",
                    event_index=index,
                )
            )

        sync_group = temporal.get("sync_group")
        if isinstance(sync_group, str) and sync_group.strip():
            sync_groups.setdefault(sync_group.strip(), []).append((index, record))

    for sync_group, grouped_records in sync_groups.items():
        alignment_values: dict[str, set[str]] = {key: set() for key in CORE_ALIGNMENT_KEYS}
        sources = {str(record["source"]).strip() for _, record in grouped_records}
        for _, record in grouped_records:
            alignment = record.get("contextual_metadata", {}).get("alignment")
            if not isinstance(alignment, dict):
                continue
            for key in CORE_ALIGNMENT_KEYS:
                try:
                    normalized = _normalized_alignment_value(alignment.get(key))
                except TypeError:
                    normalized = None
                if normalized is not None:
                    alignment_values[key].add(normalized)

        for key in _ALIGNMENT_SCOPE_KEYS:
            if len(alignment_values[key]) > 1:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="inconsistent_alignment_context",
                        message=f"sync_group '{sync_group}' contains conflicting {key} values",
                        event_index=grouped_records[0][0],
                    )
                )

        if len(sources) > 1:
            has_scope = any(alignment_values[key] for key in _ALIGNMENT_SCOPE_KEYS)
            if not has_scope:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="weak_alignment_context",
                        message=f"sync_group '{sync_group}' spans multiple sources without session, recording, trial, or subject alignment metadata",
                        event_index=grouped_records[0][0],
                    )
                )

    return ConformanceReport(
        spec_version=TSEL_SPEC_VERSION,
        total_events=len(records),
        issues=issues,
        temporal_validation=temporal_validation,
    )







