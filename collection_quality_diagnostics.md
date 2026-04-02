# Collection Quality Diagnostics

- Collection-quality diagnostics expose why valid structure could not be asserted safely.

## Upstream Issue Counts
- `ambiguous_route_evidence`: 1
- `broken_timestamp_continuity`: 1
- `inadequate_temporal_resolution`: 1
- `incomplete_packet_annotation`: 1
- `insufficient_post_stimulus_window`: 1
- `insufficient_pre_stimulus_window`: 1
- `missing_acquisition_metadata`: 1
- `missing_contextual_labels`: 1
- `missing_stimulus_markers`: 1
- `weak_provenance`: 1

## Collection Quality Cases
- `missing_stimulus_markers`: PASS
  support: Only sampled values exist; no stimulus markers or declared packet segments exist.
  expected: Higher-order experience structure remains unresolved.
  unresolved: No phases, stimulus blocks, or experience membership are created.
  upstream issues: missing_stimulus_markers
  notes: The unresolved output is caused by missing stimulus annotation rather than TSEL under-claiming.
- `missing_acquisition_metadata`: PASS
  support: The source defines a sampled EEG stream but omits explicit instrument and device class.
  expected: Observed sample_rate and channel are retained, but instrument and device class remain absent.
  unresolved: Missing acquisition metadata are not silently completed.
  upstream issues: missing_acquisition_metadata
  notes: This unresolved area reflects missing source acquisition metadata.
- `weak_provenance`: PASS
  support: The source provides only a source identifier and no session, recording, subject, or trial identifiers.
  expected: source_id is preserved, but no stronger alignment context is fabricated.
  unresolved: Session, recording, subject, and trial provenance remain absent.
  upstream issues: weak_provenance
  notes: Weak provenance is visible in the normalized output and not hidden by defaults.
- `inadequate_temporal_resolution`: PASS
  support: The olfaction table contains timestamped observations but not high-resolution within-episode sampled trajectories.
  expected: Row observations stay as observations; phase and continuity richness is not forced.
  unresolved: No baseline, rise, peak, or recovery structure is invented from sparse rows.
  upstream issues: inadequate_temporal_resolution
  notes: This is an upstream collection-resolution limitation, not a TSEL failure.
- `insufficient_pre_post_windows`: PASS
  support: The deterministic stream contains explicit onset and offset but omits baseline samples and post-offset trailing samples.
  expected: Supported stimulus phases are retained, but baseline and aftereffect/recovery remain absent.
  unresolved: No baseline or recovery phases are claimed without supporting windows.
  upstream issues: insufficient_pre_stimulus_window, insufficient_post_stimulus_window
  notes: The missing windows are visible as absent supported phases rather than as fabricated structure.
- `broken_timestamp_continuity`: PASS
  support: A marked experience contains a verified internal temporal gap.
  expected: The experience cannot remain continuous across the gap.
  unresolved: Continuity downgrades to interrupted or fragmented.
  observed: interrupted
  upstream issues: broken_timestamp_continuity
  notes: The continuity downgrade is driven by sample spacing, not by a heuristic guess.
- `incomplete_packet_annotation`: PASS
  support: The packet directory is missing a required typed-packet member.
  expected: Typed packet detection refuses to treat the directory as a complete packet profile.
  unresolved: Packet-level declarations remain unavailable.
  observed: LBs2.txt
  upstream issues: incomplete_packet_annotation
  notes: The missing file list identifies the upstream packet annotation gap directly.
- `ambiguous_route_evidence`: PASS
  support: The input contains equally strong EEG and olfaction evidence in one flat table.
  expected: The route remains ambiguous rather than being forced into one profile.
  unresolved: Automatic route remains unresolved.
  upstream issues: ambiguous_route_evidence
  notes: ambiguous deterministic route evidence: eeg (recognized EEG channel names were detected), olfaction (olfaction-specific fields were detected)
- `missing_contextual_labels`: PASS
  support: Markers exist, but they are typed only as generic behavior and never labeled as stimulus markers.
  expected: The events remain unstimulated behavior context; no stimulus object is invented.
  unresolved: Stimulus context remains absent.
  upstream issues: missing_contextual_labels
  notes: The missing label weakness is visible in output restraint rather than being silently repaired.
