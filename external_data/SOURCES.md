# Sourced Data

These files are the real external datasets currently used to exercise TSEL beyond the synthetic examples.

## Sources

- UCI Gas Sensor Array Drift Dataset: https://archive.ics.uci.edu/dataset/224/gas+sensor+array+drift+dataset
- Sleep-EDF Database Expanded: https://physionet.org/content/sleep-edfx/1.0.0/sleep-cassette/
- Sleep and Dream Database mirror: https://zenodo.org/records/18076716
- DREAM Olfaction Prediction Challenge Synapse export: local source bundle imported from `C:\Users\Richard\Desktop\MRES\Data\Dream\Synapse`

## Local layout

- `raw/`: downloaded or imported source files
- `raw/dream_synapse/`: imported local Synapse challenge bundle, including the raw `train_set.mat` mirror
- `curated/`: deterministic subsets prepared from the raw sources for repeatable tests
- `configs/`: TSEL configs for the sourced datasets

## Preparation

Run:

```powershell
python tools/prepare_sourced_data.py
python tools/import_synapse_dream_data.py --source-dir "<path-to-synapse-export>"
```

If the Synapse raw bundle has already been imported into `raw/dream_synapse/`, you can rerun only the curated build step with:

```powershell
python tools/import_synapse_dream_data.py
```

This creates or refreshes:

- `curated/olfactory_gas_batch1_sample.csv`
- `curated/dream_reports_sample.csv`
- `curated/dream_synapse_train_sample.tsv`
- `curated/dream_synapse_leaderboard_individual_sample.tsv`
- `curated/dream_synapse_lbs1_individual_sample.tsv`
- `curated/dream_synapse_lbs2_aggregate_sample.tsv`
- `curated/dream_synapse_molecular_sample.tsv`
- `curated/dream_synapse_split_registry.tsv`

The Sleep-EDF files are used directly, with bounded EDF ingestion configured in `configs/source_sleep_edf.json`.

## Notes

- The user's `Dream` Synapse folder contains DREAM challenge olfaction data, not dream-report text.
- The incomplete `Unconfirmed 97736.crdownload` file was ignored and is not part of the imported raw bundle.
- The imported `train_set.mat` file is preserved as raw provenance, but the current normalized workflow uses the tabular text exports because they are directly ingestible in the current environment.