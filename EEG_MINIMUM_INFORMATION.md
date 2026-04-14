# EEG Minimum Information Requirements

This note defines the minimum evidence required before TSEL is allowed to assert EEG-specific claims inside the shared TSEL contract.

## Claim Requirements

### Acquisition route = EEG
- Minimum source evidence:
  explicit EEG channel labels, deterministic EDF EEG signal labels, or explicit EEG metadata combined with multichannel sampled structure.
- Acceptable evidence sources:
  channel names, EDF header labels, explicit metadata fields such as `montage`, `reference`, `electrode`, or `eeg`.
- Deterministic derivation rule:
  route may be resolved only when EEG evidence is stronger than generic multichannel sensor evidence.
- Fallback when unmet:
  unresolved route or refusal to auto-plan as EEG.

### Multichannel continuity
- Minimum source evidence:
  explicit timestamps or start-time plus explicit sampling rate for sampled streams.
- Acceptable evidence sources:
  row timestamps, JSON `start_time`, JSON `timestamps`, EDF header timing, explicit sample-rate fields.
- Deterministic derivation rule:
  continuity may be derived only across actual sampled sequences with no unsupported gap-bridging.
- Fallback when unmet:
  relative ordering only, partial timing, or no continuity claim.

### Channel identity preservation
- Minimum source evidence:
  explicit channel labels.
- Acceptable evidence sources:
  table column names, JSON channel keys, EDF signal labels.
- Deterministic derivation rule:
  channel identity is copied, not inferred semantically.
- Fallback when unmet:
  unresolved channel identity.

### Sampling-rate-aware continuity
- Minimum source evidence:
  explicit sampling rate or EDF header-derived sample rate.
- Acceptable evidence sources:
  `sample_rate_hz`, `sampling_rate_hz`, `sample_rate`, EDF signal header.
- Deterministic derivation rule:
  sampling rate may be used only when directly declared or header-derived.
- Fallback when unmet:
  partial timing with missing `sampling_rate` in completeness.

### Event marker preservation
- Minimum source evidence:
  explicit annotation, event, marker, or stage fields.
- Acceptable evidence sources:
  JSON `annotations`/`events`/`markers`, row `annotation_label`, `event_label`, `sleep_stage`, `stage`.
- Deterministic derivation rule:
  explicit markers may be preserved as markers; explicit window bounds may be preserved as windows.
- Fallback when unmet:
  no marker or window claims.

### Temporal gap identification
- Minimum source evidence:
  explicit timestamps, explicit window bounds, or deterministic sampled timing.
- Acceptable evidence sources:
  timestamps, start time plus sample rate, EDF record timing, window start/end fields.
- Deterministic derivation rule:
  gaps may be identified only where actual timing evidence exposes them.
- Fallback when unmet:
  unresolved continuity/gap state.

### Trial/session provenance
- Minimum source evidence:
  explicit session/trial identifiers in source metadata or packet manifest.
- Acceptable evidence sources:
  `session_id`, `recording_id`, `trial_id`, explicit packet manifest.
- Deterministic derivation rule:
  identifiers may be propagated exactly as declared and marked with the correct assertion basis.
- Fallback when unmet:
  missing `session_or_trial_id` in completeness.

### Packet/session grouping
- Minimum source evidence:
  explicit `packet_manifest.json` with `packet_type = eeg_session` and valid member paths.
- Acceptable evidence sources:
  packet manifest only.
- Deterministic derivation rule:
  packet grouping may be asserted as `packet_declared`; it must not overwrite the member collection class.
- Fallback when unmet:
  no packet grouping claim.

### Window or phase structure
- Minimum source evidence for window claims:
  explicit window start/end or equivalent explicit marker/window support.
- Minimum source evidence for generic temporal phase claims:
  continuous sampled signal trajectory with deterministic timing support.
- Deterministic derivation rule:
  TSEL may derive generic temporal trajectory phases from supported continuous signals, but it must not convert those into cognition, perception, or subjective labels.
- Fallback when unmet:
  unresolved window/phase structure or marker-only preservation.

### Cross-event relations
- Minimum source evidence:
  explicit linkage or deterministic temporal/session linkage with shared source context.
- Acceptable evidence sources:
  explicit window IDs, packet/session IDs, aligned markers, deterministic same-stream continuity rules.
- Deterministic derivation rule:
  relations may be added only when shared source, timing, and explicit linkage justify them.
- Fallback when unmet:
  no relation claim.

## Claims TSEL Must Not Make From EEG Alone
- cognitive state
- emotional state
- perceptual content
- odor identity
- stimulus meaning
- subjective experience labels
- brain-state interpretation beyond source-declared or explicitly linked metadata

If the source does not justify one of these claims, TSEL must emit unresolved, partial, or nothing at all rather than inventing interpretation.
