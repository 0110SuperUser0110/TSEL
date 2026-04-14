# Olfactory Collection Quality Diagnostics

TSEL now exposes the following upstream olfactory collection weaknesses directly instead of hiding them:

- missing odor identity
- missing odor concentration or dilution
- missing onset or offset markers
- missing sampling rate for sampled olfactory streams
- missing trial identifiers
- missing acquisition metadata such as explicit device description
- insufficient pre-exposure windows for baseline recovery
- insufficient post-exposure windows for recovery or aftereffect recovery
- sparse timestamps that are too weak to justify continuity claims
- incomplete packet declarations
- profile-disambiguation metadata that are too weak to separate receptor-series and sensor-stream layouts

These weaknesses now appear through `contextual_metadata.completeness.missing_dimensions`, `contextual_metadata.unresolved`, or explicit profile-resolution refusal.
