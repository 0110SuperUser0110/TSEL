# TSEL Specification v1.0.0

TSEL is a deterministic temporal coding layer that operates before any downstream AI or machine learning system. Its purpose is to preserve temporal structure, provenance, synchronization, and modality context while normalizing heterogeneous sensory inputs into one inspectable representation.

## Canonical Event Envelope

Every TSEL event must expose exactly these top-level fields:

- `timestamp`
- `modality`
- `source`
- `signal_type`
- `value`
- `unit`
- `contextual_metadata`

The temporal layer is carried inside `contextual_metadata.temporal`. Alignment context lives in `contextual_metadata.alignment`.

TSEL also standardizes canonical inner ontology blocks inside `contextual_metadata`:

- `alignment`
- `temporal`
- `sensory`
- `acquisition`
- `stimulus`
- `relations`
- `completeness`
- `experience`

## Sensory Profile Switch

TSEL may be entered through an acquisition-oriented sensory profile switch such as `generic`, `eeg`, `olfaction`, `dream`, `environment`, or `multisensory`. The profile affects ingestion routing and validation expectations only. It does not change the seven-field event envelope or the temporal grammar.

The preserved sensory class itself is standardized separately in `contextual_metadata.sensory.primary_sense` and is constrained to the five base human senses: `vision`, `audition`, `olfaction`, `gustation`, and `somatosensation`.

## Normative Temporal Fields

The following temporal fields are standardized:

- `start`
- `end`
- `anchor`
- `duration_seconds`
- `resolution_seconds`
- `uncertainty_seconds`
- `time_scale`
- `event_kind`
- `stream_id`
- `sequence_index`
- `confidence`
- `phase`
- `sync_group`
- `window_id`
- `episode_id`
- `transition_from`
- `transition_to`
- `schema_version`

`phase` is where the layer can preserve the lived temporal shape of an episode instead of only its boundary markers.

`schema_version` is required for conformance and is currently `1.0.0`.

## Canonical Event Kinds

TSEL v1.0.0 defines these core event kinds:

- `sample`
- `observation`
- `marker`
- `report`
- `transition`
- `window`
- `episode`
- `aggregate`

The standard is extensible. Non-core values are allowed if they are token-safe and clearly documented by the implementation.

## Canonical Experience Phases

TSEL v1.0.0 defines these core experience phases:

- `baseline`
- `anticipation`
- `onset`
- `rise`
- `peak`
- `sustain`
- `decay`
- `offset`
- `aftereffect`
- `report`
- `recovery`

These are generic temporal states for preserving a full sensory episode such as pre-exposure baseline, stimulus onset, biological rise, peak response, waning response, removal, and post-stimulus report.

## Canonical Time Scales

TSEL v1.0.0 defines these core temporal scales:

- `sample`
- `millisecond`
- `second`
- `minute`
- `hour`
- `session`
- `day`
- `epoch`
- `experiment`

## Sensory Context

TSEL v1.0.0 standardizes a sense-aware ontology inside `contextual_metadata.sensory`.

Canonical fields are:

- `primary_sense`
- `submodality`
- `body_site`
- `laterality`
- `receptor_pathway`
- `trajectory_role`

The five canonical base senses are:

- `vision`
- `audition`
- `olfaction`
- `gustation`
- `somatosensation`

`trajectory_role` distinguishes whether an event participates as baseline, stimulus, response, report, contextual support, or aftereffect within a preserved episode.

## Acquisition Context

TSEL standardizes how the raw observation was obtained inside `contextual_metadata.acquisition`.

Canonical fields are:

- `acquisition_profile`
- `device_class`
- `instrument`
- `channel`
- `sample_rate_hz`
- `transform_stage`

This is how EEG, cameras, microphones, chemical sensors, pressure sensors, and other tools are represented without confusing them with the five senses themselves.

## Stimulus Context

TSEL standardizes stimulus-state information inside `contextual_metadata.stimulus`.

Canonical fields are:

- `stimulus_id`
- `stimulus_label`
- `stimulus_object`
- `presentation_phase`
- `delivery_state`
- `intensity_estimate`
- `intensity_unit`

This allows the layer to preserve not only that a stimulus existed, but how it unfolded across onset, rise, peak, sustain, decay, offset, and aftermath.

## Relations Context

TSEL standardizes inter-event and event-to-episode links inside `contextual_metadata.relations`.

Each relation object may include:

- `relation_type`
- `target_id`
- `target_type`
- `description`
- `confidence`

This is how events can remain unified across windows, streams, experiences, continuity tracks, and reports.

## Alignment Context

When session, recording, subject, trial, or device identifiers are available, they should be standardized in `contextual_metadata.alignment` using:

- `source_id`
- `session_id`
- `recording_id`
- `subject_id`
- `trial_id`
- `device_id`

## Completeness Context

Raw sensory data is often partial. TSEL preserves that partiality explicitly instead of flattening it away.

`contextual_metadata.completeness` may include:

- `observation_status`
- `completeness_score`
- `missing_dimensions`
- `inferred_fields`
- `future_inference_allowed`

Canonical observation statuses in v1.0.0 are:

- `observed`
- `partial`
- `missing`
- `inferred`
- `imputed`
- `derived`

Normative rules:

- Partially observed events should declare `missing_dimensions` when known.
- Inferred, imputed, or derived events should declare `inferred_fields` when known.
- `future_inference_allowed` marks events whose missing structure may be reconstructed by downstream systems later without losing the original observed envelope.

## Experience Context

TSEL can preserve experiential continuity across fragmented or reconstructed temporal evidence.

`contextual_metadata.experience` may include:

- `experience_id`
- `continuity_id`
- `continuity_index`
- `continuity_state`

Canonical continuity states in v1.0.0 are:

- `continuous`
- `interrupted`
- `fragmented`
- `reconstructed`
- `unknown`

Normative rules:

- `continuity_index` should be paired with `continuity_id`.
- `experience_id` may group events that belong to one experiential sequence even when the raw acquisition is incomplete.
- `continuity_state` should describe whether the preserved sequence is direct, interrupted, fragmented, or reconstructed.

## Interval and Transition Rules

- `transition` events should define both `transition_from` and `transition_to`.
- `window` and `episode` events should define an interval with both `start` and `end`.
- Multichannel streams sampled at the same timestamp should use a shared `sync_group` when the adapter can determine alignment deterministically.
- If a `sync_group` spans multiple sources, the implementation should preserve alignment identifiers so cross-source timing remains interpretable.

## Bundle Format

TSEL supports line-oriented normalized events and a bundle object. The bundle object contains:

- `spec_version`
- `generated_at`
- `event_count`
- `summary`
- `events`

## Conformance

A TSEL-conformant artifact must:

1. Preserve the seven-field top-level envelope.
2. Include `contextual_metadata.temporal.schema_version` on every event.
3. Produce valid temporal ordering and stream semantics.
4. Use canonical vocabulary values or extension-safe tokens.
5. Preserve alignment identifiers when they exist and keep them consistent within synchronization groups.
6. Satisfy the interval and transition rules above.
7. Preserve partial observation and experiential continuity explicitly when raw inputs are incomplete rather than silently discarding those gaps.

Machine-readable schemas and vocabulary exports are generated into this directory by:

```powershell
python -m tsel.cli standard --output-dir standards
```