# Olfactory Handling Audit

## Current Olfactory Handling
- TSEL still emits the same seven top-level fields for olfactory events: `timestamp`, `modality`, `source`, `signal_type`, `value`, `unit`, and `contextual_metadata`.
- Olfactory interpretation now passes through `tsel/olfactory_profiles.py` instead of relying only on broad route hints.
- Automatic olfactory handling is now split into explicit collection classes:
  - `olfactory_event_profile`
  - `olfactory_sensor_stream_profile`
  - `olfactory_receptor_series_profile`
  - `olfactory_neural_response_profile`
  - `olfactory_trial_packet_profile`
  - `olfactory_subjective_report_profile`
- Auto-routing in `tsel/autorouting.py` uses the olfactory profile layer for CSV, TSV, TXT, JSON, and JSONL inputs when the selected profile is `olfaction`.
- Packet handling in `tsel/packet_profiles.py` now resolves the DREAM Synapse bundle through the same olfactory domain-profile path instead of embedding all semantics directly in the packet config.
- Manual config ingestion in `tsel/pipeline.py` also applies the olfactory domain-profile layer so configured olfactory data receive the same profile and missing-metadata logic.
- Shared validation and normalization now recognize `contextual_metadata.domain_profile` through `tsel/models.py` and `tsel/standards.py`.

## Risks Addressed
- Broad olfactory routing is now narrowed by collection-class resolution instead of only field-name hints.
- Packet-specific olfactory behavior is now explicit and basis-marked through `domain_profile`.
- TSEL no longer claims packet instrument or device class for the DREAM Synapse data.
- Olfactory neural-response inputs can now resolve to an EEG acquisition route while still preserving olfaction as the primary sense.
- Missing odor identity, concentration, trial context, sampling rate, and stimulus markers now surface as partial or unresolved structure instead of being silently filled.

## Remaining Risks
- Automatic olfactory profile resolution is conservative and field-name driven; weakly labeled datasets will remain unresolved.
- EDF auto-routing is still not sufficient for olfactory neural-response claims without an explicit config or explicit odor annotation support.
- Typed packet support is still narrow; DREAM Synapse is handled, but other olfactory packets will need their own explicit declarations.
- Receptor-series vs sensor-stream distinctions remain conservative and may reject mixed layouts instead of guessing.
