# EEG Collection Quality Diagnostics

This note summarizes the recurring upstream EEG data-collection issues that now become visible through TSEL's conservative profile handling.

| Upstream weakness | What it blocks | How TSEL responds |
| --- | --- | --- |
| Missing channel names | channel identity, strong EEG route evidence | leaves channel identity unresolved or refuses EEG route resolution |
| Missing sampling rate | sampling-rate-aware continuity, exact sample timing | marks `sampling_rate` missing and keeps timing partial |
| Missing timestamps or start time | absolute-time continuity, gap analysis | preserves relative order only and marks `absolute_time` missing |
| Missing event markers | event-aligned windows, cleaner trajectory segmentation | preserves raw sampled stream only; no marker/window claims |
| Missing session or trial identifiers | trustworthy continuity/session grouping | marks `session_or_trial_id` missing |
| Missing montage/reference metadata | stronger acquisition provenance, cleaner electrode interpretation | preserves samples but marks montage/reference metadata missing |
| Broken continuity or dropped segments | continuous-experience claims across gaps | refuses to bridge gaps unsupported by timing evidence |
| Sparse annotation-only logs | sampled continuity, channel-level interpretations | preserves markers/windows only; does not invent samples or cognitive meaning |
| Weak or ambiguous labeling | confident EEG route resolution | refuses EEG route instead of guessing |
| EDF header present but poorly labeled | EEG route recovery from EDF | leaves EDF unresolved when labels are not deterministically EEG |
| Incomplete packet manifest | packet-declared session/trial claims | refuses packet grouping or leaves packet context incomplete |
| Missing pre/post event windows | stronger event-aligned recovery and comparison | keeps event support limited to what is explicitly declared |

## Interpretation
Unresolved EEG outputs should now be read as information about collection quality as much as information about TSEL restraint. If the route, timing, window, or provenance evidence is weak, TSEL exposes that weakness instead of hiding it.

## Practical Implication
For stronger temporal encoding, upstream EEG collection should prioritize:
- deterministic channel naming
- explicit sampling rate
- explicit session and trial identifiers
- explicit event markers or window bounds
- complete montage/reference metadata where available
- packet manifests for multi-file session bundles
