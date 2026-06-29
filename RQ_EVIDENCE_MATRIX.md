# RQ Evidence Matrix

Status date: 2026-06-29

## Approved Research Framing

TSEL should be written as a unified temporal encoding artifact evaluated through Design Science Research. The thesis validation is olfactory-led, while non-olfactory routes demonstrate that the same representational contract can generalize across heterogeneous temporal inputs.

## RQ1

Research question:

What structural characteristics are required to represent temporally dynamic sensory data within a unified encoding framework?

Current evidence:

| Evidence | Location | Status |
| --- | --- | --- |
| Seven-field event envelope | `standards/TSEL_SPEC.md` | complete |
| Temporal grammar under `contextual_metadata.temporal` | `standards/TSEL_SPEC.md` | complete |
| Canonical inner ontology blocks for temporal, sensory, acquisition, stimulus, relations, completeness, and experience | `standards/TSEL_SPEC.md` | complete |
| Unified route audit | `unification_integrity.md` | complete |
| Deterministic guardrail rules | `DETERMINISTIC_GUARDRAILS.md` | complete |
| Olfactory collection/profile definitions | `OLFACTORY_PROFILE_SPEC.md`, `OLFACTORY_MINIMUM_INFORMATION.md` | complete |
| General non-EEG profile preservation | `tsel/general_profiles.py`, `tests/test_general_profiles.py` | implemented and tested |

Thesis claim supported:

TSEL requires a stable top-level envelope, a richer temporal/contextual metadata layer, explicit provenance, assertion-basis semantics, unresolved states, and route/profile discipline.

## RQ2

Research question:

To what extent does the proposed temporal encoding layer preserve temporal and stimulus-response structure in free olfactory reference data and generated mock olfactory data?

Current evidence:

| Evidence | Location | Status |
| --- | --- | --- |
| Olfactory profile restraint/recovery tests | `tests/test_olfactory_profiles.py` | passing |
| Curated UCI gas sensor bundle | `output/thesis_validation/olfactory_gas.bundle.json` | generated, ignored from git |
| Curated DREAM/Synapse olfaction bundle | `output/thesis_validation/synapse_olfaction.bundle.json` | generated, ignored from git |
| Gas bundle validation/conformance | `THESIS_VALIDATION_SUMMARY.md` | valid and conformant |
| Synapse bundle validation/conformance | `THESIS_VALIDATION_SUMMARY.md` | valid and conformant with warnings |
| Balance diagnostics for restraint and recovery | `supported_structure_test_summary.md`, `balance_diagnostics.json` | passing |

Thesis claim supported:

TSEL preserves supported olfactory temporal structure, source provenance, descriptor context, molecular descriptor context, event kinds, sample timing, stream identity, and explicit partiality. It does not invent stimulus markers, phase structure, continuity, odor identity, or acquisition metadata when source support is insufficient.

Remaining RQ2 need:

Generated mock olfactory data must be finalized under documented assumptions and explicitly labeled as mock in the thesis outputs.

## RQ3

Research question:

How consistently does the proposed framework support inspectable, reproducible, and clearly labeled mock olfactory data representation before downstream computational modeling?

Current evidence:

| Evidence | Location | Status |
| --- | --- | --- |
| Repeatable CLI commands | `THESIS_VALIDATION_SUMMARY.md`, `README.md` | complete |
| Strict validation and conformance hooks | `tsel/cli.py`, `tsel/standards.py`, `tests/test_standard.py` | complete |
| Source/raw/curated separation | `external_data/SOURCES.md`, `.gitignore` | complete |
| Machine-readable bundles | `output/thesis_validation/` | generated locally |
| Explicit unresolved and completeness semantics | `standards/TSEL_SPEC.md`, `DETERMINISTIC_GUARDRAILS.md` | complete |
| Anti-false-positive diagnostics | `supported_structure_test_summary.md`, `collection_quality_diagnostics.md` | complete |

Thesis claim supported:

TSEL supports reproducible artifact validation through deterministic transforms, strict validation, explicit conformance checks, source/curated separation, and inspectable JSON bundle outputs.

Remaining RQ3 need:

The final mock-data generator or mock-data fixture set must be documented with assumptions, seed or construction rules, labels, and rerun instructions.

## Current Bottom Line

The artifact now supports the approved research framing. The remaining work is not broad feature expansion. It is thesis packaging, raw-source restoration for full reruns, and final mock olfactory dataset documentation.
