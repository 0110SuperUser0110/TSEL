from __future__ import annotations

"""Deterministic enrichment rules for TSEL.

This module is intentionally conservative. It only enriches temporal experience
structure when one of the following is true:
1. the source already provided the value,
2. the packet declared the value,
3. or a documented deterministic rule can derive it from explicit evidence.

When support is insufficient, TSEL records the field as unresolved instead of
inventing structure.
"""

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean, median
import re

from .models import TemporalEvent, TemporalEventCollection
from .standards import normalize_delivery_state, normalize_primary_sense


STRICT_ENRICHMENT_DEFAULT = True
MIN_NUMERIC_PHASE_SAMPLES = 4
MAX_GAP_MULTIPLIER = 2.0

SOURCE_BASIS = "source_provided"
PACKET_BASIS = "packet_declared"
OBSERVED_BASIS = "directly_observed"
DERIVED_BASIS = "deterministically_derived"
UNRESOLVED_BASIS = "unresolved"

_ONSET_HINTS = (
    "onset",
    "start",
    "begin",
    "stim_on",
    "present",
    "presented",
    "introduce",
    "light_on",
    "visual_on",
    "flash_on",
    "tone_on",
    "sound_on",
    "audio_on",
    "taste_on",
    "delivery_on",
    "touch_on",
    "contact_on",
    "odor_on",
)
_OFFSET_HINTS = (
    "offset",
    "end",
    "stop",
    "remove",
    "removed",
    "return",
    "stim_off",
    "light_off",
    "visual_off",
    "tone_off",
    "sound_off",
    "audio_off",
    "taste_off",
    "delivery_off",
    "touch_off",
    "contact_off",
    "odor_off",
)
_REPORT_HINTS = ("report", "describe", "verbal", "summary")
_BASELINE_HINTS = ("baseline", "rest", "pre", "before")
_AFTEREFFECT_HINTS = ("aftereffect", "after_effect", "post", "residual")
_RECOVERY_HINTS = ("recovery", "recover", "return_to_baseline")

_DIRECT_MODALITY_SENSE = {
    "olfaction": "olfaction",
    "olfaction_perception": "olfaction",
    "olfaction_aggregate": "olfaction",
    "olfaction_challenge_split": "olfaction",
}


@dataclass(frozen=True, slots=True)
class ExperienceSegment:
    start: datetime
    end: datetime
    explicit_end: bool
    onset_event: TemporalEvent
    offset_event: TemporalEvent | None = None


def _canonical_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _event_time(event: TemporalEvent) -> datetime:
    return event.extent.start


def _event_end(event: TemporalEvent) -> datetime:
    return event.extent.end or event.extent.start


def _context_object(event: TemporalEvent, key: str) -> dict[str, object]:
    raw = event.contextual_metadata.get(key)
    return dict(raw) if isinstance(raw, dict) else {}


def _set_assertion_basis(event: TemporalEvent, field_path: str, basis: str) -> None:
    basis_map = event.contextual_metadata.get("assertion_basis")
    normalized = dict(basis_map) if isinstance(basis_map, dict) else {}
    normalized[field_path] = basis
    event.contextual_metadata["assertion_basis"] = normalized


def _set_assertion_basis_if_missing(event: TemporalEvent, field_path: str, basis: str) -> None:
    basis_map = event.contextual_metadata.get("assertion_basis")
    if isinstance(basis_map, dict) and basis_map.get(field_path) is not None:
        return
    _set_assertion_basis(event, field_path, basis)


def _mark_unresolved(event: TemporalEvent, field_path: str, reason: str) -> None:
    unresolved = event.contextual_metadata.get("unresolved")
    normalized = dict(unresolved) if isinstance(unresolved, dict) else {}
    normalized[field_path] = reason
    event.contextual_metadata["unresolved"] = normalized
    _set_assertion_basis(event, field_path, UNRESOLVED_BASIS)


def _clear_unresolved(event: TemporalEvent, field_path: str) -> None:
    unresolved = event.contextual_metadata.get("unresolved")
    if not isinstance(unresolved, dict) or field_path not in unresolved:
        return
    normalized = dict(unresolved)
    normalized.pop(field_path, None)
    if normalized:
        event.contextual_metadata["unresolved"] = normalized
    else:
        event.contextual_metadata.pop("unresolved", None)


def _record_existing_structure_basis(event: TemporalEvent) -> None:
    ingest_mode = str(event.contextual_metadata.get("ingest_mode", "")).strip()
    if ingest_mode == "packet_profile":
        basis = PACKET_BASIS
    elif ingest_mode == "auto_profile":
        basis = DERIVED_BASIS
    else:
        basis = SOURCE_BASIS
    if event.phase is not None:
        _set_assertion_basis_if_missing(event, "temporal.phase", basis)
    for block_name in ("sensory", "acquisition", "stimulus", "domain_profile"):
        block = event.contextual_metadata.get(block_name)
        if not isinstance(block, dict):
            continue
        for key in block.keys():
            _set_assertion_basis_if_missing(event, f"{block_name}.{key}", basis)
    if isinstance(event.contextual_metadata.get("relations"), list):
        _set_assertion_basis_if_missing(event, "relations", basis)


def _explicit_hint_tokens(event: TemporalEvent) -> set[str]:
    if event.event_kind not in {"marker", "transition", "window", "episode", "report"}:
        return set()
    values = [
        event.signal_type,
        str(event.contextual_metadata.get("annotation_label", "")),
        str(event.contextual_metadata.get("marker_type", "")),
        str(event.contextual_metadata.get("phase", "")),
    ]
    if isinstance(event.value, str):
        values.append(event.value)
    return {_canonical_token(value) for value in values if _canonical_token(value)}


def _contains_hint(tokens: set[str], hints: tuple[str, ...]) -> bool:
    return any(any(hint in token for hint in hints) for token in tokens)


def _classify_explicit_phase(event: TemporalEvent) -> str | None:
    if event.phase is not None:
        return event.phase
    if event.event_kind == "report":
        return "report"
    tokens = _explicit_hint_tokens(event)
    if not tokens:
        return None
    if _contains_hint(tokens, _REPORT_HINTS):
        return "report"
    if _contains_hint(tokens, _OFFSET_HINTS):
        return "offset"
    if _contains_hint(tokens, _ONSET_HINTS):
        return "onset"
    if _contains_hint(tokens, _BASELINE_HINTS):
        return "baseline"
    if _contains_hint(tokens, _AFTEREFFECT_HINTS):
        return "aftereffect"
    if _contains_hint(tokens, _RECOVERY_HINTS):
        return "recovery"
    if "peak" in tokens:
        return "peak"
    return None


def _set_phase(event: TemporalEvent, phase: str, *, basis: str = DERIVED_BASIS) -> None:
    if event.phase is None:
        event.phase = phase
        _clear_unresolved(event, "temporal.phase")
        _set_assertion_basis(event, "temporal.phase", basis)


def _numeric_value(event: TemporalEvent) -> float | None:
    value = event.value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _experience_id(modality: str, source: str, index: int) -> str:
    return f"experience::{modality}::{_canonical_token(source)}::{index:03d}"


def _relation_exists(event: TemporalEvent, relation_type: str, target_id: str) -> bool:
    relations = event.contextual_metadata.get("relations")
    if not isinstance(relations, list):
        return False
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        if relation.get("relation_type") == relation_type and relation.get("target_id") == target_id:
            return True
    return False


def _append_relation(
    event: TemporalEvent,
    relation_type: str,
    target_id: str,
    *,
    target_type: str | None = None,
    description: str | None = None,
    confidence: float | None = None,
    basis: str = DERIVED_BASIS,
) -> None:
    if _relation_exists(event, relation_type, target_id):
        return
    relations = event.contextual_metadata.get("relations")
    if not isinstance(relations, list):
        relations = []
        event.contextual_metadata["relations"] = relations
    relation: dict[str, object] = {
        "relation_type": relation_type,
        "target_id": target_id,
    }
    if target_type is not None:
        relation["target_type"] = target_type
    if description is not None:
        relation["description"] = description
    if confidence is not None:
        relation["confidence"] = confidence
    relations.append(relation)
    _set_assertion_basis(event, "relations", basis)


def _attach_experience(event: TemporalEvent, experience_id: str, continuity_id: str) -> None:
    experience = _context_object(event, "experience")
    existing_experience_id = experience.get("experience_id")
    existing_continuity_id = experience.get("continuity_id")
    if isinstance(existing_experience_id, str) and existing_experience_id != experience_id:
        _mark_unresolved(event, "experience.experience_id", "ambiguous_experience_membership")
        return
    if isinstance(existing_continuity_id, str) and existing_continuity_id != continuity_id:
        _mark_unresolved(event, "experience.continuity_id", "ambiguous_continuity_membership")
        return
    if existing_experience_id is None:
        experience["experience_id"] = experience_id
        _set_assertion_basis(event, "experience.experience_id", DERIVED_BASIS)
    if existing_continuity_id is None:
        experience["continuity_id"] = continuity_id
        _set_assertion_basis(event, "experience.continuity_id", DERIVED_BASIS)
    event.contextual_metadata["experience"] = experience
    if event.episode_id is None:
        event.episode_id = experience_id
    _append_relation(event, "part_of", experience_id, target_type="experience")
    _append_relation(event, "belongs_to", continuity_id, target_type="continuity")


def _set_continuity_index(event: TemporalEvent, continuity_index: int) -> None:
    experience = _context_object(event, "experience")
    if experience.get("continuity_index") is None:
        experience["continuity_index"] = continuity_index
        _set_assertion_basis(event, "experience.continuity_index", DERIVED_BASIS)
    event.contextual_metadata["experience"] = experience


def _set_continuity_state(event: TemporalEvent, continuity_state: str, *, basis: str) -> None:
    experience = _context_object(event, "experience")
    if experience.get("continuity_state") is None:
        experience["continuity_state"] = continuity_state
        _set_assertion_basis(event, "experience.continuity_state", basis)
    event.contextual_metadata["experience"] = experience


def _primary_sense_from_event(event: TemporalEvent) -> str | None:
    sensory = event.contextual_metadata.get("sensory")
    if isinstance(sensory, dict) and isinstance(sensory.get("primary_sense"), str):
        return normalize_primary_sense(str(sensory["primary_sense"]))
    legacy = event.contextual_metadata.get("sensory_class")
    if isinstance(legacy, str) and legacy.strip():
        return normalize_primary_sense(legacy)
    modality_sense = _DIRECT_MODALITY_SENSE.get(event.modality)
    if modality_sense is not None:
        return modality_sense
    return None


def _trajectory_role_for_phase(phase: str | None) -> str:
    if phase in {"baseline", "anticipation"}:
        return "baseline"
    if phase == "report":
        return "report"
    if phase in {"aftereffect", "recovery"}:
        return "aftereffect"
    if phase in {"onset", "rise", "peak", "sustain", "decay", "offset"}:
        return "stimulus"
    return "response"


def _ensure_sensory_context(event: TemporalEvent) -> None:
    sensory = _context_object(event, "sensory")
    primary_sense = _primary_sense_from_event(event)
    if primary_sense is not None and sensory.get("primary_sense") is None:
        sensory["primary_sense"] = primary_sense
        _set_assertion_basis(event, "sensory.primary_sense", DERIVED_BASIS)
    if event.phase is not None and sensory.get("trajectory_role") is None:
        sensory["trajectory_role"] = _trajectory_role_for_phase(event.phase)
        _set_assertion_basis(event, "sensory.trajectory_role", DERIVED_BASIS)
    if sensory:
        event.contextual_metadata["sensory"] = sensory


def _ensure_acquisition_context(event: TemporalEvent) -> None:
    acquisition = _context_object(event, "acquisition")
    if acquisition.get("acquisition_profile") is None:
        explicit_profile = event.contextual_metadata.get("acquisition_profile")
        if isinstance(explicit_profile, str) and explicit_profile.strip():
            acquisition["acquisition_profile"] = _canonical_token(explicit_profile)
            _set_assertion_basis(event, "acquisition.acquisition_profile", DERIVED_BASIS)
        else:
            declared_profile = event.contextual_metadata.get("sensory_profile")
            if isinstance(declared_profile, str) and declared_profile.strip():
                acquisition["acquisition_profile"] = _canonical_token(declared_profile)
                basis = PACKET_BASIS if str(event.contextual_metadata.get("ingest_mode", "")).strip() == "packet_profile" else DERIVED_BASIS
                _set_assertion_basis(event, "acquisition.acquisition_profile", basis)
    channel = event.contextual_metadata.get("channel")
    if acquisition.get("channel") is None and isinstance(channel, str) and channel.strip():
        acquisition["channel"] = channel.strip()
        _set_assertion_basis(event, "acquisition.channel", OBSERVED_BASIS)
    sample_rate_hz = event.contextual_metadata.get("sample_rate_hz")
    if acquisition.get("sample_rate_hz") is None and isinstance(sample_rate_hz, (int, float)):
        acquisition["sample_rate_hz"] = float(sample_rate_hz)
        _set_assertion_basis(event, "acquisition.sample_rate_hz", OBSERVED_BASIS)
    if acquisition.get("transform_stage") is None:
        acquisition["transform_stage"] = "normalized"
        _set_assertion_basis(event, "acquisition.transform_stage", DERIVED_BASIS)
    if acquisition:
        event.contextual_metadata["acquisition"] = acquisition


def _delivery_state_for_phase(phase: str | None) -> str | None:
    mapping = {
        "onset": "presented",
        "rise": "active",
        "peak": "active",
        "sustain": "maintained",
        "decay": "active",
        "offset": "removed",
        "aftereffect": "residual",
        "recovery": "residual",
        "report": "reported",
    }
    state = mapping.get(phase)
    return None if state is None else normalize_delivery_state(state)


def _has_explicit_stimulus_evidence(event: TemporalEvent) -> bool:
    if isinstance(event.contextual_metadata.get("stimulus"), dict):
        return True
    marker_type = _canonical_token(str(event.contextual_metadata.get("marker_type", "")))
    return event.event_kind in {"marker", "transition"} and marker_type == "stimulus"


def _ensure_stimulus_context(event: TemporalEvent) -> None:
    if not _has_explicit_stimulus_evidence(event):
        return
    stimulus = _context_object(event, "stimulus")
    if stimulus.get("stimulus_label") is None:
        label = event.contextual_metadata.get("annotation_label")
        if isinstance(label, str) and label.strip():
            stimulus["stimulus_label"] = label.strip()
            _set_assertion_basis(event, "stimulus.stimulus_label", OBSERVED_BASIS)
        elif event.event_kind in {"marker", "transition"} and isinstance(event.value, str) and event.value.strip():
            stimulus["stimulus_label"] = event.value.strip()
            _set_assertion_basis(event, "stimulus.stimulus_label", OBSERVED_BASIS)
    if stimulus.get("stimulus_id") is None and stimulus.get("stimulus_label") is not None and event.event_kind in {"marker", "transition"}:
        suffix = event.sequence_index if event.sequence_index is not None else int(_event_time(event).timestamp())
        stimulus["stimulus_id"] = f"stimulus::{_canonical_token(str(stimulus['stimulus_label']))}::{suffix}"
        _set_assertion_basis(event, "stimulus.stimulus_id", DERIVED_BASIS)
    if event.phase is not None:
        if stimulus.get("presentation_phase") is None:
            stimulus["presentation_phase"] = event.phase
            _set_assertion_basis(event, "stimulus.presentation_phase", DERIVED_BASIS)
        delivery_state = _delivery_state_for_phase(event.phase)
        if delivery_state is not None and stimulus.get("delivery_state") is None:
            stimulus["delivery_state"] = delivery_state
            _set_assertion_basis(event, "stimulus.delivery_state", DERIVED_BASIS)
    if stimulus:
        event.contextual_metadata["stimulus"] = stimulus


def _window_label_for_phase(phase: str | None) -> str:
    if phase in {"baseline", "anticipation"}:
        return "baseline"
    if phase in {"aftereffect", "recovery"}:
        return "aftereffect"
    if phase == "report":
        return "report"
    return "stimulus"


def _ensure_window(event: TemporalEvent, experience_id: str) -> None:
    expected_window_id = f"{experience_id}::{_window_label_for_phase(event.phase)}"
    if event.window_id is None:
        event.window_id = expected_window_id
    elif event.window_id != expected_window_id:
        _mark_unresolved(event, "temporal.window_id", "ambiguous_window_membership")
        return
    _append_relation(event, "part_of", event.window_id, target_type="window")


def _infer_segments(events: list[TemporalEvent]) -> list[ExperienceSegment]:
    if not events:
        return []
    sorted_events = sorted(events, key=_event_time)
    last_time = max(_event_end(event) for event in sorted_events)
    explicit_phase_events = [(event, _classify_explicit_phase(event)) for event in sorted_events]
    onset_events = [event for event, phase in explicit_phase_events if phase == "onset"]
    offset_events = [event for event, phase in explicit_phase_events if phase == "offset"]
    if onset_events:
        segments: list[ExperienceSegment] = []
        for index, onset_event in enumerate(onset_events):
            next_onset_time = _event_time(onset_events[index + 1]) if index + 1 < len(onset_events) else None
            offset_event = next(
                (
                    candidate
                    for candidate in offset_events
                    if _event_time(candidate) >= _event_time(onset_event)
                    and (next_onset_time is None or _event_time(candidate) < next_onset_time)
                ),
                None,
            )
            if offset_event is not None:
                end = _event_time(offset_event)
                explicit_end = True
            elif next_onset_time is not None:
                eligible = [event for event in sorted_events if _event_time(onset_event) <= _event_time(event) < next_onset_time]
                end = max((_event_end(event) for event in eligible), default=next_onset_time)
                explicit_end = False
            else:
                end = last_time
                explicit_end = False
            segments.append(
                ExperienceSegment(
                    start=_event_time(onset_event),
                    end=end,
                    explicit_end=explicit_end,
                    onset_event=onset_event,
                    offset_event=offset_event,
                )
            )
        return segments

    interval_events = [event for event in sorted_events if event.event_kind in {"window", "episode"} and event.extent.end is not None]
    return [
        ExperienceSegment(
            start=event.extent.start,
            end=event.extent.end or event.extent.start,
            explicit_end=True,
            onset_event=event,
            offset_event=None,
        )
        for event in interval_events
    ]


def _mark_phase_unresolved(events: list[TemporalEvent], reason: str) -> None:
    for event in events:
        if event.phase is None:
            _mark_unresolved(event, "temporal.phase", reason)


def _non_decreasing(values: list[float], tolerance: float) -> bool:
    return all(next_value >= current - tolerance for current, next_value in zip(values, values[1:], strict=False))


def _non_increasing(values: list[float], tolerance: float) -> bool:
    return all(next_value <= current + tolerance for current, next_value in zip(values, values[1:], strict=False))


def _annotate_numeric_stream(samples: list[TemporalEvent], baseline_samples: list[TemporalEvent], *, explicit_end: bool) -> None:
    ordered = sorted(samples, key=_event_time)
    if not ordered:
        return
    if len(ordered) < MIN_NUMERIC_PHASE_SAMPLES:
        _mark_phase_unresolved(ordered, "insufficient_numeric_phase_evidence")
        return

    values = [value for value in (_numeric_value(event) for event in ordered) if value is not None]
    if len(values) != len(ordered):
        _mark_phase_unresolved(ordered, "non_numeric_stream_values")
        return

    dynamic_range = max(values) - min(values)
    if dynamic_range <= 0:
        _mark_phase_unresolved(ordered, "flat_numeric_stream")
        return

    tolerance = max(dynamic_range * 0.05, 1e-9)
    peak_value = max(values)
    peak_indices = [index for index, value in enumerate(values) if abs(value - peak_value) <= tolerance]
    first_peak = min(peak_indices)
    last_peak = max(peak_indices)
    if first_peak == 0 or last_peak == len(values) - 1:
        _mark_phase_unresolved(ordered, "edge_peak_without_full_trajectory")
        return

    if not _non_decreasing(values[: first_peak + 1], tolerance):
        _mark_phase_unresolved(ordered, "non_monotonic_rise")
        return
    if not _non_increasing(values[last_peak:], tolerance):
        _mark_phase_unresolved(ordered, "non_monotonic_decay")
        return

    baseline_values = [value for value in (_numeric_value(event) for event in baseline_samples) if value is not None]
    if baseline_values:
        baseline_value = fmean(baseline_values)
        if abs(peak_value - baseline_value) <= tolerance:
            _mark_phase_unresolved(ordered, "no_meaningful_deviation_from_baseline")
            return

    for index, event in enumerate(ordered):
        if index == 0:
            phase = "onset"
        elif index < first_peak:
            phase = "rise"
        elif first_peak <= index <= last_peak:
            phase = "peak" if first_peak == last_peak else "sustain"
        elif explicit_end and index == len(ordered) - 1:
            phase = "offset"
        else:
            phase = "decay"
        _set_phase(event, phase)


def _annotate_trailing_events(events: list[TemporalEvent], baseline_by_stream: dict[str, list[TemporalEvent]]) -> None:
    samples_by_stream: dict[str, list[TemporalEvent]] = {}
    for event in sorted(events, key=_event_time):
        classified = _classify_explicit_phase(event)
        if classified is not None:
            _set_phase(event, classified)
        if event.event_kind == "sample" and _numeric_value(event) is not None and event.stream_id is not None:
            samples_by_stream.setdefault(event.stream_id, []).append(event)

    for stream_id, samples in samples_by_stream.items():
        baseline_values = [value for value in (_numeric_value(event) for event in baseline_by_stream.get(stream_id, [])) if value is not None]
        if not baseline_values:
            _mark_phase_unresolved(samples, "missing_baseline_for_recovery")
            continue
        baseline_value = fmean(baseline_values)
        deviations = [abs((_numeric_value(event) or baseline_value) - baseline_value) for event in samples]
        if len(samples) == 1:
            tolerance = max(deviations[0] * 0.15, 1e-9)
            phase = "recovery" if deviations[0] <= tolerance else "aftereffect"
            _set_phase(samples[0], phase)
            continue
        tolerance = max(max(deviations) * 0.1, 1e-9)
        if not _non_increasing(deviations, tolerance):
            _mark_phase_unresolved(samples, "non_monotonic_recovery")
            continue
        baseline_tolerance = max(max(deviations) * 0.15, 1e-9)
        for event, deviation in zip(samples, deviations, strict=False):
            phase = "recovery" if deviation <= baseline_tolerance else "aftereffect"
            _set_phase(event, phase)


def _expected_stream_resolution(samples: list[TemporalEvent]) -> float | None:
    explicit = [event.extent.resolution_seconds for event in samples if event.extent.resolution_seconds is not None]
    if explicit:
        return float(median(explicit))
    diffs: list[float] = []
    previous: TemporalEvent | None = None
    for event in sorted(samples, key=_event_time):
        if previous is not None and previous.sequence_index is not None and event.sequence_index is not None:
            if event.sequence_index - previous.sequence_index == 1:
                diffs.append((_event_time(event) - _event_time(previous)).total_seconds())
        previous = event
    positive = [diff for diff in diffs if diff > 0]
    if positive:
        return float(median(positive))
    return None


def _continuity_break_count(samples: list[TemporalEvent], expected_resolution: float) -> int:
    breaks = 0
    previous: TemporalEvent | None = None
    for event in sorted(samples, key=_event_time):
        if previous is None:
            previous = event
            continue
        if previous.sequence_index is not None and event.sequence_index is not None:
            if event.sequence_index - previous.sequence_index > 1:
                breaks += 1
                previous = event
                continue
        gap_seconds = (_event_time(event) - _event_time(previous)).total_seconds()
        if gap_seconds > expected_resolution * MAX_GAP_MULTIPLIER:
            breaks += 1
        previous = event
    return breaks


def _resolve_continuity_state(events: list[TemporalEvent]) -> tuple[str, str]:
    streams: dict[str, list[TemporalEvent]] = {}
    for event in events:
        if event.event_kind == "sample" and event.stream_id is not None:
            streams.setdefault(event.stream_id, []).append(event)

    supported_streams = 0
    total_breaks = 0
    for samples in streams.values():
        if len(samples) < 2:
            continue
        expected_resolution = _expected_stream_resolution(samples)
        if expected_resolution is None:
            continue
        supported_streams += 1
        total_breaks += _continuity_break_count(samples, expected_resolution)

    if supported_streams == 0:
        return "unknown", UNRESOLVED_BASIS
    if total_breaks == 0:
        return "continuous", DERIVED_BASIS
    if total_breaks == 1:
        return "interrupted", DERIVED_BASIS
    return "fragmented", DERIVED_BASIS


def _finalize_event_context(event: TemporalEvent) -> None:
    _ensure_sensory_context(event)
    _ensure_acquisition_context(event)
    _ensure_stimulus_context(event)
    if event.stream_id is not None:
        _append_relation(event, "part_of", event.stream_id, target_type="stream")


def enrich_experience(collection: TemporalEventCollection, *, strict: bool = STRICT_ENRICHMENT_DEFAULT) -> TemporalEventCollection:
    if not collection.events:
        return collection
    collection.sort_in_place()
    grouped: dict[tuple[str, str], list[TemporalEvent]] = {}
    for event in collection.events:
        grouped.setdefault((event.modality, event.source), []).append(event)

    for (modality, source), events in grouped.items():
        ordered_events = sorted(events, key=_event_time)
        for event in ordered_events:
            _record_existing_structure_basis(event)
            classified = _classify_explicit_phase(event)
            if classified is not None:
                _set_phase(event, classified)
            _finalize_event_context(event)

        segments = _infer_segments(ordered_events)
        if not segments and not strict:
            sample_events = [event for event in ordered_events if event.event_kind == "sample"]
            if sample_events:
                segments = [
                    ExperienceSegment(
                        start=_event_time(sample_events[0]),
                        end=_event_end(sample_events[-1]),
                        explicit_end=False,
                        onset_event=sample_events[0],
                        offset_event=None,
                    )
                ]
        if not segments:
            continue

        for experience_index, segment in enumerate(segments, start=1):
            experience_id = _experience_id(modality, source, experience_index)
            continuity_id = f"continuity::{experience_id}"
            baseline_events = [event for event in ordered_events if _event_time(event) < segment.start]
            active_events = [event for event in ordered_events if segment.start <= _event_time(event) <= segment.end]
            trailing_events = [event for event in ordered_events if segment.explicit_end and _event_time(event) > segment.end]

            baseline_by_stream: dict[str, list[TemporalEvent]] = {}
            for event in baseline_events:
                _attach_experience(event, experience_id, continuity_id)
                if event.event_kind == "sample":
                    _set_phase(event, "baseline")
                    if event.stream_id is not None:
                        baseline_by_stream.setdefault(event.stream_id, []).append(event)
                _ensure_window(event, experience_id)
                _finalize_event_context(event)

            numeric_by_stream: dict[str, list[TemporalEvent]] = {}
            assigned_events: list[TemporalEvent] = []
            for event in active_events:
                _attach_experience(event, experience_id, continuity_id)
                assigned_events.append(event)
                if event.event_kind == "sample" and _numeric_value(event) is not None and event.stream_id is not None:
                    numeric_by_stream.setdefault(event.stream_id, []).append(event)

            for samples in numeric_by_stream.values():
                _annotate_numeric_stream(samples, baseline_by_stream.get(samples[0].stream_id or "", []), explicit_end=segment.explicit_end)

            for event in active_events:
                _ensure_window(event, experience_id)
                _finalize_event_context(event)

            assigned_events.extend(baseline_events)

            if segment.explicit_end and trailing_events:
                for event in trailing_events:
                    _attach_experience(event, experience_id, continuity_id)
                _annotate_trailing_events(trailing_events, baseline_by_stream)
                for event in trailing_events:
                    _ensure_window(event, experience_id)
                    _finalize_event_context(event)
                assigned_events.extend(trailing_events)

            unique_events: list[TemporalEvent] = []
            seen: set[int] = set()
            for event in sorted(assigned_events, key=_event_time):
                marker = id(event)
                if marker in seen:
                    continue
                seen.add(marker)
                unique_events.append(event)

            continuity_state, continuity_basis = _resolve_continuity_state(unique_events)
            for continuity_index, event in enumerate(unique_events):
                _set_continuity_index(event, continuity_index)
                _set_continuity_state(event, continuity_state, basis=continuity_basis)
                _finalize_event_context(event)
                experience = event.contextual_metadata.get("experience")
                if isinstance(experience, dict) and event.phase == "report":
                    target_id = experience.get("experience_id")
                    if isinstance(target_id, str):
                        _append_relation(event, "describes", target_id, target_type="experience")

    collection.sort_in_place()
    return collection






