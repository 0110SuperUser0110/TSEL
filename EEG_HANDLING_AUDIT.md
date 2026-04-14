# EEG Handling Audit

## Scope
This note audits EEG handling as an internal TSEL domain/profile area. EEG remains an acquisition route and collection-class family inside TSEL, not a separate schema or second system.

## Current EEG Support Paths
- Direct JSON multichannel sampled streams are classified in [tsel/eeg_profiles.py](E:/TSEL/tsel/eeg_profiles.py) and planned through [tsel/autorouting.py](E:/TSEL/tsel/autorouting.py) as `timeseries_json` when deterministic EEG evidence is strong.
- Tabular EEG time-series inputs are classified conservatively from explicit EEG channel labels or explicit EEG metadata plus multichannel sampled structure, then mapped through the shared `timeseries_csv` path.
- EDF inputs are accepted only when the EDF header declares deterministic EEG signal labels. Generic EDF containers are no longer treated as EEG by default.
- Sparse EEG annotation or window logs are handled as row-style `csv` or `json` mappings when explicit time basis plus annotation/window evidence are present.
- Explicit packetized EEG session inputs are supported through a manifest-based packet path in [tsel/packet_profiles.py](E:/TSEL/tsel/packet_profiles.py). Packet support is declaration-driven, not inferred from folder shape alone.

## What Is Explicit
- EEG route resolution now depends on deterministic evidence: EEG channel labels, EDF signal labels, or explicit EEG metadata combined with multichannel sampled structure.
- `contextual_metadata.domain_profile` is populated for EEG collection classes using the same shared domain-profile block already used elsewhere in TSEL.
- `contextual_metadata.assertion_basis` and `contextual_metadata.completeness` are used for EEG the same way they are used for other TSEL inputs.
- Packet/session provenance can now be added explicitly through `packet_manifest.json`, with packet metadata basis-marked as `packet_declared`.

## What Was Previously Implicit or Too Broad
- EDF files were previously treated as EEG by suffix alone. That was too broad and risked false-positive route resolution.
- Explicit `eeg` routing for tables and JSON inputs was under-specified: any numeric multichannel shape could drift toward EEG handling if the user requested EEG directly.
- Sparse annotation logs were not previously documented as a distinct EEG collection class.
- Packet/session EEG handling was not explicit before this pass.

## Conservative Behavior Added In This Pass
- Unresolved or ambiguous EEG evidence now fails safely instead of silently guessing.
- Weakly labeled multichannel streams do not become EEG without deterministic evidence.
- Sparse annotation logs preserve markers and explicit windows only; they do not become sampled continuity or stimulus meaning.
- Raw EEG does not imply cognitive, emotional, perceptual, or subjective labels.
- Packet declarations do not erase the member collection class. Direct-stream, EDF, and annotation-log identity remain visible while packet fields are added separately with `packet_declared` basis.

## Unification Check
EEG handling remains unified with the rest of TSEL.
- The same seven-field top-level contract is preserved: `timestamp`, `modality`, `source`, `signal_type`, `value`, `unit`, `contextual_metadata`.
- Field meanings are unchanged. EEG does not redefine `modality`, `value`, `signal_type`, or `unit` semantics.
- `assertion_basis`, `unresolved`, `completeness`, provenance, and bundle semantics remain shared.
- No EEG-only top-level schema was introduced.
- No EEG path bypasses the common validation and serialization path.

Verdict: EEG handling is unified, not drifting.

## Remaining Gaps and Risks
- EEG packet support is intentionally narrow and requires an explicit manifest. This is conservative, but some real session folders will remain unresolved until they are declared better.
- Montage/reference metadata remain partial or missing for many EEG sources; TSEL preserves that missingness instead of fabricating it.
- Sparse annotation logs can preserve windows and labels, but they cannot justify sampled continuity, cognition, or stimulus meaning on their own.
- EDF support is intentionally label-dependent. Poorly labeled EDF headers will remain unresolved even if the file contains EEG-like data.
