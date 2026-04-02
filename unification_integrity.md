# Unification Integrity

- Unified contract status: yes
- Canonical top-level fields: timestamp, modality, source, signal_type, value, unit, contextual_metadata

## Semantic Findings
- All inspected routes still emit the same seven-field top-level event schema.
- Temporal semantics continue to flow through contextual_metadata.temporal across manual, auto-routed, packet, and typed-packet paths.
- assertion_basis and unresolved are normalized and validated through the same metadata standardizer.
- Packet-specific and route-specific metadata remain inside contextual_metadata rather than creating route-specific top-level schemas.
- No inspected route bypasses TemporalEvent serialization or bundle generation.

## Route Checks
- `eeg_config`: top_level=True, temporal=True, bundle=True, assertion_basis=True, unresolved=True, modality_primary_sense=True
- `olfaction_config`: top_level=True, temporal=True, bundle=True, assertion_basis=True, unresolved=True, modality_primary_sense=True
- `multisensory_auto`: top_level=True, temporal=True, bundle=True, assertion_basis=True, unresolved=True, modality_primary_sense=True
- `generic_packet`: top_level=True, temporal=True, bundle=True, assertion_basis=True, unresolved=True, modality_primary_sense=True
- `typed_packet`: top_level=True, temporal=True, bundle=True, assertion_basis=True, unresolved=True, modality_primary_sense=True

## Fragmentation Risks
- `viewer_alias_fields` (low): viewer/app.py writes convenience aliases such as sensory_class and top-level acquisition_profile alongside the canonical sensory and acquisition blocks. These do not fork the contract, but they duplicate canonical meanings.
- `modality_subtype_overloading` (low): packet-derived modalities such as olfaction_perception and olfaction_aggregate are valid subtypes, but they rely on contextual_metadata.sensory.primary_sense to keep sensory semantics aligned with broader routes.
