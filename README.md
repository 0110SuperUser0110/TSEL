# Temporal Sensory Encoding Layer

TSEL is a deterministic temporal coding layer that operates before any downstream AI, LLM, or machine learning system. Its job is to preserve timing, ordering, interval structure, synchronization, provenance, and modality context before raw sensory data is flattened or abstracted.

## TSEL v1.0.0 standard

The implementation now carries a versioned standard surface in `standards/`.

Core specification artifacts:

- `standards/TSEL_SPEC.md`
- `standards/tsel-event.schema.json`
- `standards/tsel-bundle.schema.json`
- `standards/vocabulary.json`

The canonical event envelope remains seven top-level fields:

- `timestamp`
- `modality`
- `source`
- `signal_type`
- `value`
- `unit`
- `contextual_metadata`

The temporal layer is carried inside `contextual_metadata.temporal` and standardizes:

- `start`
- `end`
- `anchor`
- `duration_seconds`
- `resolution_seconds`
- `uncertainty_seconds`
- `time_scale`
- `event_kind`
- `stream_id`
- `sequence_index`
- `confidence`
- `phase`
- `sync_group`
- `window_id`
- `episode_id`
- `transition_from`
- `transition_to`
- `schema_version`

That means TSEL can represent point events, sampled streams, interval events, transitions, reports, synchronized multichannel data, and full sensory trajectories in one normalized structure. Cross-session and cross-device linkage lives in `contextual_metadata.alignment`, which standardizes `source_id`, `session_id`, `recording_id`, `subject_id`, `trial_id`, and `device_id` when those identifiers are available.

The unified layer is now deeper inside `contextual_metadata`, not broader at the top level. In addition to `temporal`, TSEL standardizes `sensory`, `acquisition`, `stimulus`, `relations`, `completeness`, and `experience`. `sensory.primary_sense` is constrained to the five base senses: `vision`, `audition`, `olfaction`, `gustation`, and `somatosensation`. Acquisition tools such as EEG remain acquisition metadata, not sensory classes.

TSEL also now treats incomplete observation and experiential continuity as first-class schema concepts. `contextual_metadata.completeness` can declare whether an event is observed, partial, missing, inferred, imputed, or derived, what dimensions are missing, and whether later systems are allowed to infer them. `contextual_metadata.experience` can preserve continuity across fragmented evidence with `experience_id`, `continuity_id`, `continuity_index`, and `continuity_state`, so downstream systems can reconstruct missing structure without breaking the original temporal envelope into disconnected bits. `contextual_metadata.temporal.phase` is now also a normative field for preserving the shape of an experience across `baseline`, `onset`, `rise`, `peak`, `sustain`, `decay`, `offset`, `aftereffect`, `report`, and `recovery` rather than collapsing the episode to a single onset or offset marker.

## What is implemented

TSEL now includes:

- row-mapped CSV and JSON ingestion for observation-style records
- declarative temporal semantics in configs, including event kind, end time, duration, resolution, uncertainty, time scale, confidence, phase, synchronization group, windows, episodes, and transitions
- multichannel time-series CSV ingestion with explicit channels or channel autodiscovery
- direct multichannel JSON stream ingestion with annotation expansion
- native EEG EDF ingestion in pure Python
- temporal validation for ordering, stream identity, sequence monotonicity, interval validity, transition completeness, sample-gap detection, and sync-group alignment consistency
- sensory profile switching at ingest time (`generic`, `eeg`, `olfaction`, `dream`, `environment`, `multisensory`) with one unchanged normalized output schema
- conformance evaluation against the TSEL v1.0.0 standard
- first-class completeness and experience metadata for partial observations, inferred fields, and continuity-preserving reconstruction
- canonical five-sense ontology blocks for sensory class, acquisition route, stimulus state, and inter-event relations inside `contextual_metadata`
- automatic experience-phase derivation over continuous episodes, including baseline, onset, rise, peak, sustain, decay, offset, aftereffect, report, and recovery when the data supports them
- marker-centered segmentation and interval materialization over normalized timelines
- normalized reload from JSON, JSONL, or bundle files
- a thin local GUI viewer that demonstrates the layer without embedding any AI logic

## Input coverage

Current adapters cover one unified temporal structure with selectable sensory profiles at ingress. The profile switch changes how a dataset is interpreted, not the event schema it resolves into.

Current adapters cover:

- `csv`
- `json`
- `timeseries_csv`
- `timeseries_json`
- `edf`

This makes the temporal code universal at the schema level even though vendor-specific readers can still be added over time.

## CLI

```powershell
python -m tsel.cli auto-ingest examples/data/eeg_direct.json eeg output/eeg_direct.jsonl --format jsonl
python -m tsel.cli ingest examples/data/eeg_direct.json examples/configs/eeg_direct.json output/eeg_direct.jsonl --profile eeg
python -m tsel.cli batch examples/configs/demo_manifest.json output/demo.jsonl
python -m tsel.cli batch examples/configs/demo_manifest.json output/demo.bundle.json --format bundle
python -m tsel.cli summarize output/demo.bundle.json --json
python -m tsel.cli validate output/demo.bundle.json --json --strict
python -m tsel.cli conformance output/demo.bundle.json --json --strict
python -m tsel.cli standard --json
python -m tsel.cli standard --output-dir standards
python tools/export_standard_assets.py
python tools/prepare_sourced_data.py
python tools/import_synapse_dream_data.py --source-dir "<path-to-synapse-export>"
python -m tsel.cli batch external_data/configs/source_full_manifest.json output/source_full_manifest.jsonl --format jsonl
python -m tsel.cli validate output/source_full_manifest.jsonl --json --strict
python -m tsel.cli conformance output/source_full_manifest.jsonl --json --strict
python -m tsel.cli segment output/demo.jsonl output/demo_segments.json --marker-signal marker --pre-seconds 0.25 --post-seconds 0.25
pytest
```

## GUI viewer

The viewer is a thin local application that demonstrates the single TSEL operation:

- select raw sensory input
- select one explicit sensory class
- let TSEL infer the raw acquisition route from the file
- build the unified temporal layer
- store the resulting temporal code for the rest of the system
- display that stored output in the window

Launch it with:

```powershell
python -m viewer.app
```

The GUI is intentionally minimal. It does not expose validation, conformance, segmentation, or export controls in the main surface. The selector now exposes the base senses only: `vision`, `audition`, `olfaction`, `gustation`, and `somatosensation`. EEG is treated as an internal measurement route, not a sensory selector. The viewer stores the current system bundle under `output/<sense>/current_temporal_layer.bundle.json`, shows the raw source preview on the left, and shows the stored unified temporal code on the right. The status area now also exposes the derived experience phases, experience and continuity tracks, sensory ontology summary, and acquisition ontology summary so the preserved episode shape is visible without reading the raw JSON manually.

## Operational examples

Representative configs and inputs include:

- `examples/configs/eeg_direct.json`: direct EEG stream with markers
- `examples/configs/eeg_edf.json`: direct EEG EDF ingestion
- `examples/configs/multisensory_matrix.json`: generic sensory matrix autodiscovery
- `examples/configs/temporal_states.json`: declarative window, episode, transition, and confidence mapping
- `examples/configs/demo_manifest.json`: multi-modality batch normalization
- `examples/data/vision_episode.json`: representative visual episode
- `examples/data/audition_episode.json`: representative auditory episode
- `examples/data/olfaction_episode.json`: representative olfactory episode
- `examples/data/gustation_episode.json`: representative gustatory episode
- `examples/data/somatosensation_episode.json`: representative somatosensory episode
- `external_data/configs/source_olfactory_gas.json`: sourced olfactory sensor matrix
- `external_data/configs/source_dream_reports.json`: sourced dream reports
- `external_data/configs/source_sleep_edf.json`: sourced EEG from Sleep-EDF
- `external_data/configs/source_sleep_hypnogram.json`: sourced sleep-stage markers
- `external_data/configs/source_dream_synapse_train.json`: DREAM Synapse train-set olfactory ratings
- `external_data/configs/source_dream_synapse_individual.json`: DREAM Synapse individual leaderboard ratings
- `external_data/configs/source_dream_synapse_aggregate.json`: DREAM Synapse aggregate leaderboard targets
- `external_data/configs/source_dream_synapse_molecular.json`: DREAM Synapse molecular descriptor matrix
- `external_data/configs/source_dream_synapse_split_registry.json`: DREAM Synapse challenge split registry
- `external_data/configs/source_synapse_manifest.json`: Synapse-only sourced batch run
- `external_data/configs/source_full_manifest.json`: full multimodal sourced batch run
- `external_data/SOURCES.md`: provenance and preparation notes

## Real sourced datasets

TSEL is exercised against real external data, not only synthetic fixtures:

- olfactory sensor data from the UCI Gas Sensor Array Drift Dataset
- olfactory perception, leaderboard, split, and molecular descriptor data from the DREAM Olfaction Prediction Challenge Synapse export
- EEG polysomnography and sleep-stage annotation data from the Sleep-EDF Database Expanded
- dream report text data from the Sleep and Dream Database mirror on Zenodo

The Synapse files under the user's `Dream` folder are DREAM challenge assets, not dream reports. They are handled as olfactory challenge data alongside the separate dream-report dataset. The gas-sensor-array path remains the electronic-olfaction source.

## Verification

The implementation is covered by automated tests for:

- EEG EDF ingestion
- raw EEG JSON ingestion
- generic matrix autodiscovery
- temporal semantics mapping for windows, episodes, transitions, and confidence
- sourced olfactory ingestion
- sourced dream-report ingestion
- sourced EEG EDF ingestion
- sourced sleep-stage annotation ingestion
- DREAM Synapse train-set olfactory ingestion
- DREAM Synapse individual leaderboard ingestion
- DREAM Synapse aggregate leaderboard ingestion
- DREAM Synapse molecular descriptor ingestion
- DREAM Synapse split-registry ingestion
- bundle roundtripping
- standard asset export
- conformance evaluation
- temporal validation
- completeness and continuity validation for partial, inferred, and reconstructed event sequences
- marker segmentation
- interval materialization
- normalized file roundtripping
- CLI batch, validate, conformance, and segment workflows