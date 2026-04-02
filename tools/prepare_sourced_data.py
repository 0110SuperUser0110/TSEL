from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "external_data" / "raw"
CURATED = ROOT / "external_data" / "curated"

GAS_CLASS_MAP = {
    "1": "ethanol",
    "2": "ethylene",
    "3": "ammonia",
    "4": "acetaldehyde",
    "5": "acetone",
    "6": "toluene",
}


def main() -> None:
    CURATED.mkdir(parents=True, exist_ok=True)
    prepare_dream_reports(limit=12)
    prepare_olfactory_gas(limit=8)
    print("Prepared sourced datasets in", CURATED)


def prepare_dream_reports(*, limit: int) -> None:
    raw_path = RAW / "dream_reports.csv"
    output_path = CURATED / "dream_reports_sample.csv"
    with raw_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [
            "row_number",
            "dream_report_id",
            "participant_id",
            "dream_timestamp",
            "raw_dream_date",
            "dream_text",
            "word_count",
            "survey_name",
            "survey_id",
            "question",
            "categories",
            "gender",
            "age",
        ]
        with output_path.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.DictWriter(output_handle, fieldnames=fieldnames)
            writer.writeheader()
            for row_number, row in enumerate(reader, start=1):
                if row_number > limit:
                    break
                dream_date = datetime.strptime(row["Dream Date"], "%m/%d/%Y").replace(tzinfo=timezone.utc)
                writer.writerow(
                    {
                        "row_number": row_number,
                        "dream_report_id": row["Dream Report ID"],
                        "participant_id": row["Participant ID"] or "unknown-participant",
                        "dream_timestamp": dream_date.isoformat().replace("+00:00", "Z"),
                        "raw_dream_date": row["Dream Date"],
                        "dream_text": row["Dream Text"],
                        "word_count": row["Word Count"],
                        "survey_name": row["Survey Name"],
                        "survey_id": row["Survey ID"],
                        "question": row["Question"],
                        "categories": row["Categories"],
                        "gender": row["Gender"],
                        "age": row["Age"],
                    }
                )


def prepare_olfactory_gas(*, limit: int) -> None:
    raw_path = RAW / "gas_sensor_array_drift" / "Dataset" / "batch1.dat"
    output_path = CURATED / "olfactory_gas_batch1_sample.csv"
    origin = datetime(2007, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    feature_names = [f"feature_{index:03d}" for index in range(1, 129)]
    fieldnames = ["timestamp", "source_batch", "batch_row", "gas_class"] + feature_names

    with raw_path.open("r", encoding="utf-8") as handle, output_path.open("w", encoding="utf-8", newline="") as output_handle:
        writer = csv.DictWriter(output_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row_number, line in enumerate(handle, start=1):
            if row_number > limit:
                break
            tokens = line.strip().split()
            if not tokens:
                continue
            class_label = GAS_CLASS_MAP.get(tokens[0], tokens[0])
            feature_values = {name: "0" for name in feature_names}
            for token in tokens[1:]:
                feature_index, feature_value = token.split(":", 1)
                feature_name = f"feature_{int(feature_index):03d}"
                feature_values[feature_name] = feature_value
            timestamp = origin + timedelta(seconds=row_number - 1)
            writer.writerow(
                {
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                    "source_batch": "uci-gas-batch1",
                    "batch_row": row_number,
                    "gas_class": class_label,
                    **feature_values,
                }
            )


if __name__ == "__main__":
    main()
