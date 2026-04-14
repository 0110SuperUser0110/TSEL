# Olfactory Minimum Information Requirements

## Claim Requirements

| Claim Type | Minimum Required Evidence | Acceptable Evidence Sources | Deterministic Rule | Fallback When Unmet |
| --- | --- | --- | --- | --- |
| Stimulus block | explicit onset and offset markers, or a declared packet stimulus block | source markers, packet declarations | onset/offset markers may delimit an experience segment | leave stimulus block unresolved |
| Stimulus onset or offset | explicit marker or explicit phase field | source marker rows, source annotation records, packet declarations | marker labels may normalize to canonical phases when the marker itself is explicit | keep `temporal.phase` unresolved |
| Continuity | sampled stream with monotonic sequence or timestamp continuity and enough resolution to assess gaps | source samples, source timestamps, source sample rate | continuity may be derived from observed spacing and sequence integrity | emit `unknown` or no continuity claim |
| Phase structure | explicit markers plus deterministic monotonic numeric trajectory, or explicit source phases | source markers, source phase fields, packet declarations | only derive baseline/onset/rise/peak/decay/offset/recovery when the trajectory is numerically and temporally supported | keep phases unresolved |
| Acquisition route | unambiguous route evidence such as EEG channel names, sensor-stream fields, receptor identifiers, or packet declarations | source field names, packet declarations, source metadata | route may resolve only when one supported interpretation dominates | ambiguous or unresolved route/profile |
| Cross-event relations | explicit declarations or deterministic shared membership such as stream, experience, continuity, or window | source relations, packet declarations, deterministic membership rules | relations like `part_of` and `belongs_to` may be derived from explicit experience segmentation | omit relation entirely |
| Odor identity | explicit odor field, explicit compound identifier, or packet declaration | source fields, packet declaration | normalize only the provided identity token; do not guess labels | add `odor_identity` to missing dimensions |
| Concentration or dilution | explicit concentration, dilution, or intensity-concentration field | source fields, packet declaration | preserve as context only when explicitly present | add `odor_concentration` to missing dimensions |
| Trial identity | explicit `trial_id`, replicate label, or packet partition membership | source fields, packet declaration | preserve directly; do not synthesize a trial ID from order alone | add `trial_id` to missing dimensions |
| Subjective report semantics | explicit text or subjective report field linked to odor or trial context | source fields | classify as a report event when the report field is explicit and odor or trial context is present | unresolved or refuse profile resolution |

## Shared Rules
- If evidence is weak, TSEL must emit `partial`, `unresolved`, `unknown`, or refuse enrichment.
- No olfactory claim may bypass the shared assertion-basis rules.
- Packet declarations may support packet-level claims, but they do not justify invented absolute time, device metadata, or unsupported sensory semantics.
