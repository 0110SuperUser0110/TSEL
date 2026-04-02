# Supported Structure Test Summary

- False-positive restraint: 7 / 7
- Supported-structure recovery: 8 / 8

## Supported Recovery Cases
- `explicit_stimulus_recovery`: PASS
  support: Source annotations explicitly mark stimulus onset and stimulus offset with marker_type=stimulus.
  expected: Stimulus onset and offset markers retain stimulus blocks.; presentation_phase and delivery_state are deterministically derived on those explicit markers.
  unresolved: stimulus_object remains absent because it was never supplied.
  observed: onset, offset
- `valid_continuity_recovery`: PASS
  support: Timestamps, sequence indices, and sample spacing are internally continuous across the deterministic benchmark.
  expected: The experience continuity state resolves to continuous.
  unresolved: No continuity_state should remain unresolved for this case.
  observed: continuous
- `phase_recovery`: PASS
  support: The benchmark includes a baseline sample, explicit onset/offset, a monotonic rise to peak, monotonic decay, and trailing post-offset samples.
  expected: baseline, onset, rise, peak, decay, offset, aftereffect, and recovery are recovered where supported.; report is recovered on the explicit verbal report marker.
  unresolved: sustain remains absent because the signal never forms a plateau.
  observed: aftereffect, baseline, decay, offset, onset, peak, recovery, report, rise
- `provenance_recovery`: PASS
  support: The source metadata explicitly provide acquisition profile, instrument, device class, recording_id, subject_id, and trial_id.
  expected: Explicit acquisition metadata are preserved with source_provided basis.; Explicit alignment identifiers remain attached as provenance context.
  unresolved: No extra device or alignment identifiers are invented beyond the supplied values.
  observed: benchmark_eeg_cap, rec-001
- `relation_recovery`: PASS
  support: The report marker falls inside a supported deterministic experience with explicit onset and offset markers.
  expected: The report marker preserves a describes relation to the resolved experience.; Events preserve shared part_of stream and experience relations.
  unresolved: No caused_by or unsupported causal relations are asserted.
  observed: experience::eeg::rec_01::001
- `route_recovery`: PASS
  support: Route evidence is strong and unambiguous for EEG JSON, olfaction table, multisensory matrix, and the typed Synapse packet directory.
  expected: Generic auto-routing resolves strong routes rather than downgrading them to unresolved.; The typed packet is detected and planned through its dedicated packet profile.
  unresolved: No route remains ambiguous in these benchmark cases.
  observed: eeg, olfaction, multisensory, dream_synapse
- `packet_provenance_recovery`: PASS
  support: The typed packet declares olfaction, packet profile identity, and packet-level acquisition metadata.
  expected: Packet-declared sensory and acquisition metadata are preserved with packet_declared basis.; Packet completeness and profile provenance remain attached to normalized events.
  unresolved: Absolute time remains partial rather than fabricated.
  observed: dream_synapse
- `tabular_context_recovery`: PASS
  support: The tabular olfaction observation file supplies timestamp, source, trial_id, and humidity_pct directly.
  expected: Explicit row metadata are preserved inside contextual_metadata without weakening the shared event schema.
  unresolved: No sample-level phase or continuity is invented for row-style observations.
  observed: T-001

## Restraint Reference Cases
- `null_structure_restraint`: PASS
  support: Only generic samples are present, with no explicit segment markers or packet declarations.
  expected: No phase, experience, or stimulus structure should be invented.
  unresolved: All higher-order experience structure remains absent.
- `ambiguous_route_restraint`: PASS
  support: The file mixes strong EEG and olfaction route evidence.
  expected: The route must remain unresolved and raise an explicit ambiguity error.
  unresolved: No acquisition route should be guessed.
  notes: ambiguous deterministic route evidence: eeg (recognized EEG channel names were detected), olfaction (olfaction-specific fields were detected)
- `missing_context_restraint`: PASS
  support: Behavior markers are present, but no stimulus marker type or source stimulus block exists.
  expected: No stimulus block should be fabricated.
  unresolved: Stimulus context remains absent.
- `broken_continuity_restraint`: PASS
  support: The sampled stream has a deterministic temporal gap inside an otherwise marked segment.
  expected: Continuity may be interrupted or fragmented, but not continuous.
  unresolved: No continuous experience claim is allowed across a verified gap.
  observed: interrupted
- `cross_event_relation_restraint`: PASS
  support: A report marker exists, but there is no supported experience membership.
  expected: A report phase is allowed, but no describes relation should be invented.
  unresolved: Experience relation targets remain absent.
- `noise_only_phase_restraint`: PASS
  support: Active samples are noisy and do not form a deterministic phase trajectory.
  expected: No meaningful rise, peak, decay, or offset phases should be asserted.
  unresolved: temporal.phase remains unresolved because the decay is non-monotonic.
  observed: non_monotonic_decay
- `malformed_input_restraint`: PASS
  support: The raw JSON file is syntactically invalid.
  expected: The system must fail safely and explicitly.
  unresolved: No route or structure should be guessed from malformed input.
  notes: invalid JSON input: Expecting value
