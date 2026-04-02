# Deterministic Guardrails for TSEL

TSEL is hardened to avoid false-positive temporal structure. In this codebase, an enrichment claim is only allowed when it is supported by one of the following:

1. source-provided data
2. packet-declared data
3. a deterministic derivation rule that is explicit, testable, and implemented in code

If support is insufficient, TSEL must leave the field absent or mark it as `unresolved`, `unknown`, `partial`, or `missing`.

## Assertion basis

TSEL now tracks claim provenance in `contextual_metadata.assertion_basis` using these values:

- `source_provided`
- `packet_declared`
- `directly_observed`
- `deterministically_derived`
- `unresolved`

Open unresolved fields are tracked in `contextual_metadata.unresolved`.

## Guardrail rules

| Inference point | Required evidence | Allowed claims | Disallowed claims | Fallback |
| --- | --- | --- | --- | --- |
| Acquisition route | Explicit file structure, supported headers, channel layout, or packet declaration | `eeg`, `olfaction`, `dream`, `environment`, `multisensory` when uniquely supported | First-match routing, weak generic guessing, ambiguous auto-selection | Raise `AutoRoutingError` |
| Phase labels | Explicit marker/window/report semantics or a monotonic numeric trajectory inside an explicit segment | Canonical phase labels with `assertion_basis.temporal.phase` | Phase assignment from noise, flat streams, unlabeled sequences, or weak hints alone | Leave phase empty and mark `unresolved.temporal.phase` when applicable |
| Continuity | Sample cadence plus deterministic gap analysis inside an explicit experience | `continuous`, `interrupted`, `fragmented`, `unknown` | Defaulting to `continuous` without cadence evidence | Emit `unknown` or a gap-backed deterministic state |
| Stimulus context | Source `stimulus` block or explicit marker type `stimulus` | Stimulus label, id, delivery state, presentation phase | Converting any annotation label or generic onset/offset marker into a stimulus | Leave stimulus block absent |
| Cross-event relations | Deterministic membership or explicit report linkage | `part_of`, `belongs_to`, `describes`, and stream relations when supported | Experience, window, continuity, or report relations without explicit membership evidence | Omit the relation |
| Metadata completion | Direct metadata field, packet declaration, or deterministic normalization | Acquisition channel, sample rate, transform stage, basis, unresolved state | Adapter-driven instrument/device defaults, silent metadata completion | Leave field absent |

## Current implementation points

- `tsel/autorouting.py`
  Generic routing now requires unique deterministic evidence and fails explicitly on ambiguous or insufficient evidence.
- `tsel/experience.py`
  Experience enrichment is conservative and segment-based. It does not infer stimulus, continuity, or phase structure without support.
- `tsel/models.py`
  Metadata normalization no longer fabricates stimulus blocks or adapter-derived acquisition details, and validation now checks basis coverage and unsupported continuity claims.
- `tsel/standards.py`
  Conformance checks now understand `assertion_basis` and `unresolved` so unsupported claims can be flagged in later formal testing.
- `tsel/pipeline.py`
  `strict_mode=True` is now the default for thesis validation.

## Anti-false-positive regression coverage

`tests/test_guardrails.py` covers:

- null structure restraint
- ambiguous route refusal
- missing stimulus context restraint
- broken continuity restraint
- cross-event relation restraint
- noise-only phase restraint
- malformed input safe failure
- strict-mode default
