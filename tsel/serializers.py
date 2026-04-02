from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import TemporalEventCollection, TemporalSegment, ValidationReport


def write_events(output_path: str | Path, collection: TemporalEventCollection, *, fmt: str = "jsonl") -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        path.write_text(json.dumps(collection.to_records(), indent=2), encoding="utf-8")
        return
    if fmt == "bundle":
        path.write_text(json.dumps(collection.to_bundle(), indent=2), encoding="utf-8")
        return
    if fmt == "jsonl":
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in collection.to_records():
                handle.write(json.dumps(record))
                handle.write("\n")
        return
    raise ValueError(f"unsupported output format: {fmt}")


def load_events(input_path: str | Path) -> TemporalEventCollection:
    records = _load_records(Path(input_path))
    return TemporalEventCollection.from_records(records)


def write_segments(output_path: str | Path, segments: list[TemporalSegment]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [segment.to_record() for segment in segments]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_validation_report(output_path: str | Path, report: ValidationReport) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_record(), indent=2), encoding="utf-8")


def _load_records(path: Path) -> list[dict[str, Any]]:
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    if raw_text.startswith("["):
        payload = json.loads(raw_text)
        if not isinstance(payload, list):
            raise ValueError("JSON event file must contain a list")
        return _validate_record_list(payload)

    if raw_text.startswith("{"):
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
            return _validate_record_list(payload["events"])
        if isinstance(payload, dict) and {"timestamp", "modality", "source", "signal_type", "value", "unit"}.issubset(payload.keys()):
            return _validate_record_list([payload])

    records = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    return _validate_record_list(records)


def _validate_record_list(records: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("normalized event payloads must contain JSON objects")
        normalized.append(record)
    return normalized