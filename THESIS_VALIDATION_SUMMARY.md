# Thesis Validation Summary

Status date: 2026-06-29

## Scope

This validation pass supports the thesis framing approved through ARB minor revisions:

- TSEL is evaluated as a Design Science Research artifact.
- The thesis validation is olfactory-led.
- EEG, dream, environment, and multisensory routes remain supporting evidence for the unified contract.
- The artifact is evaluated for representation, provenance, temporal preservation, conformance, and conservative restraint, not predictive performance.

## Repository Status

- Canonical working folder: `I:\codex\TSEL`
- Recovery folder retained: `I:\codex\TSEL_recovery_20260623`
- Remote: `https://github.com/0110SuperUser0110/TSEL.git`

## Test Results

- Full suite in canonical repo: `109 passed, 13 skipped`
- Focused olfactory/unification validation: `15 passed, 13 skipped`

The skipped focused cases require raw external datasets that are intentionally excluded from version control:

- DREAM Synapse raw challenge bundle
- UCI gas sensor raw source files
- Sleep-EDF raw files
- Sleep and Dream Database raw report export

Curated deterministic subsets remain available in `external_data/curated/`.

## Generated Validation Bundles

Generated under ignored output path `output/thesis_validation/`.

| Bundle | Events | Validation | Conformance | Notes |
| --- | ---: | --- | --- | --- |
| `olfactory_gas.bundle.json` | 1,024 | valid, 0 errors, 0 warnings | conformant, 0 errors, 0 warnings | UCI gas sensor curated sample; 128 streams over 8 seconds |
| `synapse_olfaction.bundle.json` | 10,408 | valid, 0 errors, 5,240 warnings | conformant, 0 errors, 10,416 warnings | DREAM/Synapse curated challenge sample; warnings preserve source descriptor token shapes and noncanonical acquisition fields |

The Synapse warnings are not failed claims. They identify source vocabulary tokens that are preserved but not canonicalized into TSEL's preferred token vocabulary. This is useful thesis evidence for provenance transparency and collection-quality diagnostics.

## Commands Run

```powershell
pytest -q
pytest -q -rs tests/test_olfactory_profiles.py tests/test_synapse_data.py tests/test_sourced_data.py tests/test_supported_recovery.py tests/test_unification_integrity.py
python -m tsel.cli ingest external_data/curated/olfactory_gas_batch1_sample.csv external_data/configs/source_olfactory_gas.json output/thesis_validation/olfactory_gas.bundle.json --format bundle
python -m tsel.cli batch external_data/configs/source_synapse_manifest.json output/thesis_validation/synapse_olfaction.bundle.json --format bundle
python -m tsel.cli validate output/thesis_validation/olfactory_gas.bundle.json --json --strict
python -m tsel.cli conformance output/thesis_validation/olfactory_gas.bundle.json --json --strict
python -m tsel.cli validate output/thesis_validation/synapse_olfaction.bundle.json --json --strict
python -m tsel.cli conformance output/thesis_validation/synapse_olfaction.bundle.json --json --strict
```

## Reassessment

TSEL is thesis-ready at the artifact-contract level. The remaining thesis work is evidence packaging and raw-data restoration for full-source reruns, not core architecture repair.

The main remaining limitation is that the final thesis should describe the current validation as olfactory-led using curated deterministic subsets, with raw-source rerun pending restoration of excluded external raw files.
