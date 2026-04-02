from __future__ import annotations

import argparse
import csv
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "external_data" / "raw" / "dream_synapse"
CURATED_ROOT = ROOT / "external_data" / "curated"

RAW_FILES = [
    "CID_leaderboard.txt",
    "CID_testset.txt",
    "dilution_leaderboard.txt",
    "dilution_testset.txt",
    "LBs1.txt",
    "LBs2.txt",
    "leaderboard_set.txt",
    "molecular_descriptors_data.txt",
    "train_set.mat",
    "TrainSet.txt",
]

TRAIN_METADATA_COLUMNS = [
    "timestamp",
    "subject_id",
    "compound_id",
    "odor_name",
    "replicate_label",
    "intensity_label",
    "dilution",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import and prepare DREAM Synapse olfaction challenge data for TSEL")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Optional source directory containing the original Synapse files",
    )
    parser.add_argument("--train-limit", type=int, default=20)
    parser.add_argument("--molecular-limit", type=int, default=2)
    parser.add_argument("--individual-descriptors", type=int, default=6)
    parser.add_argument("--individual-rows-per-descriptor", type=int, default=12)
    parser.add_argument("--aggregate-descriptors", type=int, default=6)
    parser.add_argument("--aggregate-rows-per-descriptor", type=int, default=8)
    args = parser.parse_args()

    ensure_raw_files(args.source_dir)
    CURATED_ROOT.mkdir(parents=True, exist_ok=True)

    prepare_train_sample(limit=args.train_limit)
    prepare_individual_sample(
        input_name="leaderboard_set.txt",
        output_name="dream_synapse_leaderboard_individual_sample.tsv",
        split_name="leaderboard_set",
        origin=datetime(2015, 6, 2, tzinfo=timezone.utc),
        descriptor_limit=args.individual_descriptors,
        rows_per_descriptor=args.individual_rows_per_descriptor,
    )
    prepare_individual_sample(
        input_name="LBs1.txt",
        output_name="dream_synapse_lbs1_individual_sample.tsv",
        split_name="LBs1",
        origin=datetime(2015, 6, 3, tzinfo=timezone.utc),
        descriptor_limit=args.individual_descriptors,
        rows_per_descriptor=args.individual_rows_per_descriptor,
    )
    prepare_aggregate_sample(
        descriptor_limit=args.aggregate_descriptors,
        rows_per_descriptor=args.aggregate_rows_per_descriptor,
    )
    prepare_molecular_sample(limit=args.molecular_limit)
    prepare_split_registry()
    print("Prepared DREAM Synapse curated datasets in", CURATED_ROOT)


def ensure_raw_files(source_dir: Path | None) -> None:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    missing = [name for name in RAW_FILES if not (RAW_ROOT / name).exists()]
    if not missing:
        return
    if source_dir is None:
        raise FileNotFoundError(f"missing raw Synapse files in {RAW_ROOT}: {missing}")

    for name in RAW_FILES:
        source_path = source_dir / name
        if not source_path.exists():
            raise FileNotFoundError(f"required source file is missing: {source_path}")
        shutil.copy2(source_path, RAW_ROOT / name)


def prepare_train_sample(*, limit: int) -> None:
    input_path = RAW_ROOT / "TrainSet.txt"
    output_path = CURATED_ROOT / "dream_synapse_train_sample.tsv"
    origin = datetime(2015, 6, 1, tzinfo=timezone.utc)

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError("TrainSet.txt does not contain a header row")
        descriptor_columns = [field for field in reader.fieldnames if field not in {
            "Compound Identifier",
            "Odor",
            "Replicate",
            "Intensity",
            "Dilution",
            "subject #",
        }]
        fieldnames = TRAIN_METADATA_COLUMNS + descriptor_columns

        with output_path.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.DictWriter(output_handle, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            for row_index, row in enumerate(reader, start=1):
                if row_index > limit:
                    break
                writer.writerow(
                    {
                        "timestamp": iso_timestamp(origin, row_index - 1),
                        "subject_id": f"synapse-subject-{clean_text(row['subject #'])}",
                        "compound_id": clean_text(row["Compound Identifier"]),
                        "odor_name": clean_text(row["Odor"]),
                        "replicate_label": clean_text(row["Replicate"]),
                        "intensity_label": clean_text(row["Intensity"]),
                        "dilution": clean_text(row["Dilution"]),
                        **{column: clean_numeric_text(row[column]) for column in descriptor_columns},
                    }
                )


def prepare_individual_sample(
    *,
    input_name: str,
    output_name: str,
    split_name: str,
    origin: datetime,
    descriptor_limit: int,
    rows_per_descriptor: int,
) -> None:
    input_path = RAW_ROOT / input_name
    output_path = CURATED_ROOT / output_name
    selected_rows = select_long_rows(input_path, descriptor_limit=descriptor_limit, rows_per_descriptor=rows_per_descriptor)
    fieldnames = ["timestamp", "sequence_index", "subject_id", "compound_id", "descriptor", "value", "challenge_split"]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for sequence_index, row in enumerate(selected_rows, start=1):
            compound_key = "#oID" if "#oID" in row else "oID"
            writer.writerow(
                {
                    "timestamp": iso_timestamp(origin, sequence_index - 1),
                    "sequence_index": sequence_index - 1,
                    "subject_id": f"synapse-individual-{clean_text(row['individual'])}",
                    "compound_id": clean_text(row[compound_key]),
                    "descriptor": clean_text(row["descriptor"]),
                    "value": clean_numeric_text(row["value"]),
                    "challenge_split": split_name,
                }
            )


def prepare_aggregate_sample(*, descriptor_limit: int, rows_per_descriptor: int) -> None:
    input_path = RAW_ROOT / "LBs2.txt"
    output_path = CURATED_ROOT / "dream_synapse_lbs2_aggregate_sample.tsv"
    origin = datetime(2015, 6, 4, tzinfo=timezone.utc)
    selected_rows = select_long_rows(input_path, descriptor_limit=descriptor_limit, rows_per_descriptor=rows_per_descriptor)
    fieldnames = ["timestamp", "sequence_index", "compound_id", "descriptor", "value", "sigma", "challenge_split"]

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for sequence_index, row in enumerate(selected_rows, start=1):
            compound_key = "#oID" if "#oID" in row else "oID"
            writer.writerow(
                {
                    "timestamp": iso_timestamp(origin, sequence_index - 1),
                    "sequence_index": sequence_index - 1,
                    "compound_id": clean_text(row[compound_key]),
                    "descriptor": clean_text(row["descriptor"]),
                    "value": clean_numeric_text(row["value"]),
                    "sigma": clean_numeric_text(row["sigma"]),
                    "challenge_split": "LBs2",
                }
            )


def prepare_molecular_sample(*, limit: int) -> None:
    input_path = RAW_ROOT / "molecular_descriptors_data.txt"
    output_path = CURATED_ROOT / "dream_synapse_molecular_sample.tsv"
    origin = datetime(2015, 6, 5, tzinfo=timezone.utc)

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader, None)
        if header is None:
            raise ValueError("molecular_descriptors_data.txt does not contain a header row")
        descriptor_columns = make_unique_columns(header[1:])
        fieldnames = ["timestamp", "compound_id"] + descriptor_columns

        with output_path.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.DictWriter(output_handle, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            for row_index, row in enumerate(reader, start=1):
                if row_index > limit:
                    break
                writer.writerow(
                    {
                        "timestamp": iso_timestamp(origin, row_index - 1),
                        "compound_id": clean_text(row[0]),
                        **{column: clean_numeric_text(value) for column, value in zip(descriptor_columns, row[1:])},
                    }
                )


def prepare_split_registry() -> None:
    output_path = CURATED_ROOT / "dream_synapse_split_registry.tsv"
    origin = datetime(2015, 6, 6, tzinfo=timezone.utc)
    rows: list[dict[str, str]] = []

    for partition, cid_name, dilution_name in [
        ("leaderboard", "CID_leaderboard.txt", "dilution_leaderboard.txt"),
        ("test", "CID_testset.txt", "dilution_testset.txt"),
    ]:
        dilution_map = read_dilution_map(RAW_ROOT / dilution_name)
        for compound_id in read_id_list(RAW_ROOT / cid_name):
            rows.append(
                {
                    "compound_id": compound_id,
                    "challenge_partition": partition,
                    "dilution": dilution_map.get(compound_id, ""),
                }
            )

    fieldnames = ["timestamp", "sequence_index", "compound_id", "challenge_partition", "dilution"]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for sequence_index, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "timestamp": iso_timestamp(origin, sequence_index - 1),
                    "sequence_index": sequence_index - 1,
                    **row,
                }
            )


def select_long_rows(path: Path, *, descriptor_limit: int, rows_per_descriptor: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    counts: dict[str, int] = defaultdict(int)
    descriptor_order: list[str] = []

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            descriptor = clean_text(row["descriptor"])
            if descriptor not in counts:
                if len(descriptor_order) >= descriptor_limit:
                    continue
                descriptor_order.append(descriptor)
            if counts[descriptor] >= rows_per_descriptor:
                if len(descriptor_order) == descriptor_limit and all(counts[name] >= rows_per_descriptor for name in descriptor_order):
                    break
                continue
            counts[descriptor] += 1
            rows.append(row)
            if len(descriptor_order) == descriptor_limit and all(counts[name] >= rows_per_descriptor for name in descriptor_order):
                break
    return rows


def make_unique_columns(columns: list[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    unique: list[str] = []
    for column in columns:
        name = clean_text(column) or "unnamed"
        counts[name] += 1
        if counts[name] == 1:
            unique.append(name)
        else:
            unique.append(f"{name}__{counts[name]}")
    return unique


def read_id_list(path: Path) -> list[str]:
    values: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            value = clean_text(line)
            if not value or value.lower() in {"oid", "cid", "#oid"}:
                continue
            values.append(value)
    return values


def read_dilution_map(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        compound_key = "oID" if reader.fieldnames and "oID" in reader.fieldnames else "#oID"
        for row in reader:
            mapping[clean_text(row[compound_key])] = clean_text(row["dilution"])
    return mapping


def iso_timestamp(origin: datetime, offset_seconds: int) -> str:
    return (origin + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def clean_text(value: object) -> str:
    text = str(value).strip()
    text = text.strip('"').strip("'").strip()
    if text in {"NaN", "nan", "None"}:
        return ""
    return text


def clean_numeric_text(value: object) -> str:
    text = clean_text(value)
    if text == "NaN":
        return ""
    return text


if __name__ == "__main__":
    main()


