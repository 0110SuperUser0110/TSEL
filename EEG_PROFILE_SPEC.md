# EEG Profile Spec

EEG profiles in TSEL are domain profiles, not separate schemas. Every EEG event still maps into the shared seven-field TSEL contract, and all profile-specific interpretation is carried inside `contextual_metadata`.

## Classification Table
| Profile ID | Class name | Expected temporal structure | Expected input structure | Minimum required metadata | Supported TSEL claims | Forbidden or unsupported claims | Likely unresolved states |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `eeg_direct_stream_profile` | EEG Direct Multichannel Sampled Stream | Continuous or sequence-timed samples across explicit EEG channels | JSON object with `channels` arrays plus timestamps or sample-rate timing | time basis, channel arrays, strong EEG channel or metadata evidence | sample stream, channel identity, sampling rate when explicit, deterministic continuity | cognitive state, emotional state, subjective experience, stimulus identity without explicit linkage | missing sampling rate, missing absolute time, missing session or trial id, missing electrode labels |
| `eeg_tabular_series_profile` | EEG Tabular Time Series | Timestamped or sequence-timed rows across EEG channels | CSV, TSV, or TXT with EEG channel columns and timing fields | time basis, numeric channel columns, strong EEG channel or metadata evidence | sample stream, channel identity, sampling rate when explicit, deterministic continuity | cognitive state, emotional state, stimulus meaning without linkage | missing sampling rate, missing absolute time, missing session or trial id, missing electrode labels |
| `eeg_edf_profile` | EEG EDF File Input | Header-timed sampled EEG with optional annotation channels | EDF container with deterministic EEG signal labels | EDF container, EEG signal labels | EDF route, sample stream, channel identity, sampling rate from header, annotation preservation when present | cognitive state, emotional state, stimulus meaning without explicit annotation, header over-interpretation | missing EEG labels, missing montage/reference metadata, header inadequate for stronger claims |
| `eeg_event_aligned_profile` | EEG Event-Aligned Response Windows | Sampled EEG plus explicit markers or windows | Direct JSON stream with explicit annotations or windows | sample stream, explicit annotation or window support | sample stream, marker preservation, window preservation when explicit, deterministic temporal trajectory claims when clearly supported | stimulus identity without linkage, cognitive state, emotional state, subjective experience | missing sampling rate, missing pre/post context, missing session or trial id |
| `eeg_packet_profile` | EEG Packetized Trial or Session Records | Packet-declared grouping around one or more EEG members | Directory with explicit `packet_manifest.json` | explicit packet manifest, packet type, member paths | packet-declared grouping, packet session/trial provenance, packet basis marking | invented member semantics, invented stimulus identity, invented cognitive interpretation | missing trial id, incomplete manifest |
| `eeg_annotation_log_profile` | Sparse EEG Annotation or Event Logs | Timestamped markers or explicit windows without raw sample arrays | CSV or JSON rows with time basis plus annotation/window fields | time basis, source or session context, annotation or window field | marker preservation, window preservation when explicit, session/trial context when explicit | sampled continuity without samples, cognitive state, stimulus meaning without explicit linkage | missing absolute time, missing session/trial id, missing channel identity |

## Profile Mapping Rules
- All EEG profiles map into the same top-level TSEL envelope.
- EEG profile resolution may add `contextual_metadata.domain_profile`, `contextual_metadata.acquisition.acquisition_profile`, `contextual_metadata.completeness`, and `contextual_metadata.assertion_basis`.
- Packet declarations add packet provenance separately and do not replace the member collection class.
- `modality` remains the same shared field. For example, sparse stage logs may emit `sleep_stage` as modality while still using EEG acquisition/profile logic.

## Resolution Discipline
- Strong route evidence is required for EEG resolution.
- Ambiguous or weak evidence must remain unresolved.
- Missing metadata may produce `partial` resolution status, not invented completion.
- Unsupported interpretation stays unresolved even when route resolution succeeds.
