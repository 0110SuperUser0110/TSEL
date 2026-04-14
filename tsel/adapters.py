from __future__ import annotations

import csv
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from .config import EdfConfig, RecordMapping, TimeSeriesJsonConfig, TimeSeriesMapping, cast_value
from .edf import iter_edf_measurements
from .models import JSONValue, TemporalEvent, TemporalEventCollection, TemporalExtent, coerce_timestamp, serialize_timestamp


_SYNTHETIC_TIME_ORIGIN = "1970-01-01T00:00:00Z"
_INTERNAL_SEQUENCE_COLUMN = "__tsel_sequence_index"
_INTERNAL_ROW_NUMBER_COLUMN = "__tsel_row_number"


def _sample_extent(timestamp, sample_rate_hz: float | None) -> TemporalExtent:
    if sample_rate_hz is None:
        return TemporalExtent.from_timestamp(timestamp, time_scale="sample")
    resolution_seconds = 1.0 / sample_rate_hz
    return TemporalExtent.from_timestamp(timestamp, resolution_seconds=resolution_seconds, anchor="start", time_scale="sample")


def _sync_group(modality: str, source: str, timestamp, *, label: str = "sync") -> str:
    return f"{modality}::{source}::{label}::{serialize_timestamp(coerce_timestamp(timestamp))}"


def _augment_record(record: dict[str, Any], index: int, internal_columns: set[str]) -> dict[str, Any]:
    if not internal_columns:
        return record
    augmented = dict(record)
    if _INTERNAL_SEQUENCE_COLUMN in internal_columns:
        augmented[_INTERNAL_SEQUENCE_COLUMN] = index - 1
    if _INTERNAL_ROW_NUMBER_COLUMN in internal_columns:
        augmented[_INTERNAL_ROW_NUMBER_COLUMN] = index
    return augmented


def _record_mapping_internal_columns(mapping: RecordMapping) -> set[str]:
    internal_names = {_INTERNAL_SEQUENCE_COLUMN, _INTERNAL_ROW_NUMBER_COLUMN}
    return (
        mapping.timestamp.mapped_columns()
        | mapping.modality.mapped_columns()
        | mapping.source.mapped_columns()
        | mapping.signal_type.mapped_columns()
        | mapping.value.mapped_columns()
        | mapping.unit.mapped_columns()
        | mapping.temporal.mapped_columns()
    ) & internal_names


def _timeseries_mapping_internal_columns(mapping: TimeSeriesMapping) -> set[str]:
    internal_names = {_INTERNAL_SEQUENCE_COLUMN, _INTERNAL_ROW_NUMBER_COLUMN}
    mapped_columns = mapping.timestamp.mapped_columns() | mapping.modality.mapped_columns() | mapping.source.mapped_columns()
    if mapping.sample_rate is not None:
        mapped_columns.update(mapping.sample_rate.mapped_columns())
    return mapped_columns & internal_names


def _resolve_timeseries_csv_timestamp(mapping: TimeSeriesMapping, row: dict[str, Any], sample_rate_hz: float | None):
    raw_timestamp = mapping.timestamp.resolve(row)
    if mapping.timestamp.column == _INTERNAL_SEQUENCE_COLUMN and mapping.timestamp.unit == "samples":
        effective_sample_rate = 1.0 if sample_rate_hz is None else float(sample_rate_hz)
        origin = mapping.timestamp.origin or _SYNTHETIC_TIME_ORIGIN
        return coerce_timestamp(origin) + timedelta(seconds=float(raw_timestamp) / effective_sample_rate)
    return coerce_timestamp(raw_timestamp, origin=mapping.timestamp.origin, unit=mapping.timestamp.unit)


def _source_basis_from_metadata(metadata: dict[str, JSONValue]) -> dict[str, str]:
    basis: dict[str, str] = {}
    for key, value in metadata.items():
        if isinstance(value, dict):
            for nested_key in value.keys():
                basis[f"{key}.{nested_key}"] = "source_provided"
        else:
            basis[str(key)] = "source_provided"
    return basis


class CsvAdapter:
    def __init__(self, mapping: RecordMapping, *, delimiter: str = ",") -> None:
        self.mapping = mapping
        self.delimiter = delimiter

    def ingest(self, input_path: str | Path) -> TemporalEventCollection:
        path = Path(input_path)
        collection = TemporalEventCollection()
        internal_columns = _record_mapping_internal_columns(self.mapping)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            for index, row in enumerate(reader, start=1):
                mapped_row = _augment_record(row, index, internal_columns)
                collection.append(
                    self.mapping.transform(
                        mapped_row,
                        extra_context={"provenance": {"adapter": "csv", "record_index": index}},
                    )
                )
        collection.sort_in_place()
        return collection


class JsonAdapter:
    def __init__(self, mapping: RecordMapping) -> None:
        self.mapping = mapping

    def ingest(self, input_path: str | Path) -> TemporalEventCollection:
        path = Path(input_path)
        records = _load_json_records(path)
        collection = TemporalEventCollection()
        internal_columns = _record_mapping_internal_columns(self.mapping)
        for index, record in enumerate(records, start=1):
            mapped_record = _augment_record(record, index, internal_columns)
            collection.append(
                self.mapping.transform(
                    mapped_record,
                    extra_context={"provenance": {"adapter": "json", "record_index": index}},
                )
            )
        collection.sort_in_place()
        return collection


class TimeSeriesCsvAdapter:
    def __init__(self, mapping: TimeSeriesMapping, *, delimiter: str = ",") -> None:
        self.mapping = mapping
        self.delimiter = delimiter

    def ingest(self, input_path: str | Path) -> TemporalEventCollection:
        path = Path(input_path)
        collection = TemporalEventCollection()
        internal_columns = _timeseries_mapping_internal_columns(self.mapping)

        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            for index, row in enumerate(reader, start=1):
                mapped_row = _augment_record(row, index, internal_columns)
                channel_specs = self.mapping.resolve_channels(mapped_row)
                shared_mapped_columns = (
                    self.mapping.timestamp.mapped_columns()
                    | self.mapping.modality.mapped_columns()
                    | self.mapping.source.mapped_columns()
                    | set(channel_specs.keys())
                )
                if self.mapping.sample_rate is not None:
                    shared_mapped_columns.update(self.mapping.sample_rate.mapped_columns())
                sample_rate_hz = self.mapping.resolve_sample_rate(mapped_row)
                timestamp = _resolve_timeseries_csv_timestamp(self.mapping, mapped_row, sample_rate_hz)
                modality = str(self.mapping.modality.resolve(mapped_row))
                source = str(self.mapping.source.resolve(mapped_row))
                sync_group = _sync_group(modality, source, timestamp)
                base_context = self.mapping.context.resolve(
                    mapped_row,
                    shared_mapped_columns,
                    extra_context={"provenance": {"adapter": "timeseries_csv", "record_index": index}},
                )
                if sample_rate_hz is not None:
                    base_context["sample_rate_hz"] = sample_rate_hz
                for channel_name, channel in channel_specs.items():
                    raw_value = mapped_row.get(channel_name)
                    if raw_value in (None, ""):
                        continue
                    event_context: dict[str, JSONValue] = dict(base_context)
                    event_context[self.mapping.channel_context_key] = channel_name
                    event_context.update(channel.context)
                    collection.append(
                        TemporalEvent(
                            timestamp=timestamp,
                            modality=modality,
                            source=source,
                            signal_type=channel.signal_type,
                            value=channel.resolve_value(raw_value),
                            unit=channel.unit,
                            contextual_metadata=event_context,
                            extent=_sample_extent(timestamp, sample_rate_hz),
                            event_kind="sample",
                            sequence_index=index - 1,
                            sync_group=sync_group,
                        )
                    )
        collection.sort_in_place()
        return collection


class TimeSeriesJsonAdapter:
    def __init__(self, config: TimeSeriesJsonConfig) -> None:
        self.config = config

    def ingest(self, input_path: str | Path) -> TemporalEventCollection:
        path = Path(input_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("timeseries_json input must be a JSON object")

        channels = payload.get(self.config.channels_field)
        if not isinstance(channels, dict) or not channels:
            raise ValueError("timeseries_json input must contain a non-empty channels object")

        normalized_channels: dict[str, list[Any]] = {}
        sample_count: int | None = None
        for channel_name, samples in channels.items():
            if not isinstance(samples, list):
                raise TypeError(f"channel '{channel_name}' must contain a list of values")
            if sample_count is None:
                sample_count = len(samples)
            elif len(samples) != sample_count:
                raise ValueError("all channel arrays must have the same sample count")
            normalized_channels[str(channel_name)] = samples
        if sample_count is None:
            sample_count = 0

        timestamps = None
        if self.config.timestamps_field is not None and self.config.timestamps_field in payload:
            raw_timestamps = payload[self.config.timestamps_field]
            if not isinstance(raw_timestamps, list):
                raise TypeError("timestamps_field must point to a list")
            if len(raw_timestamps) != sample_count:
                raise ValueError("timestamp list length must match the channel sample count")
            timestamps = list(raw_timestamps)

        start_time = None
        if self.config.start_time_field is not None and self.config.start_time_field in payload:
            start_time = str(payload[self.config.start_time_field])

        sample_rate_hz = self.config.default_sample_rate_hz
        if self.config.sample_rate_field is not None and self.config.sample_rate_field in payload:
            sample_rate_hz = float(payload[self.config.sample_rate_field])

        modality = self.config.resolve_modality(payload)
        source = self.config.resolve_source(payload, fallback=path.stem)

        metadata: dict[str, JSONValue] = {}
        if self.config.metadata_field is not None and self.config.metadata_field in payload:
            raw_metadata = payload[self.config.metadata_field]
            if not isinstance(raw_metadata, dict):
                raise TypeError("metadata_field must point to a JSON object")
            metadata.update(raw_metadata)

        base_context: dict[str, JSONValue] = dict(self.config.context)
        base_context.update(metadata)
        source_basis = _source_basis_from_metadata(metadata)
        if source_basis:
            existing_basis = base_context.get("assertion_basis")
            merged_basis = dict(existing_basis) if isinstance(existing_basis, dict) else {}
            merged_basis.update(source_basis)
            base_context["assertion_basis"] = merged_basis
        base_context["provenance"] = {"adapter": "timeseries_json", "file": path.name}
        if sample_rate_hz is not None:
            base_context["sample_rate_hz"] = sample_rate_hz
        timing_origin = start_time
        if timestamps is None and timing_origin is None and sample_rate_hz is not None:
            timing_origin = _SYNTHETIC_TIME_ORIGIN

        collection = TemporalEventCollection()
        for sample_index in range(sample_count):
            timestamp = self._resolve_sample_timestamp(
                sample_index=sample_index,
                timestamps=timestamps,
                start_time=timing_origin,
                sample_rate_hz=sample_rate_hz,
            )
            extent = _sample_extent(timestamp, sample_rate_hz)
            sync_group = _sync_group(modality, source, timestamp)
            for channel_name, samples in normalized_channels.items():
                value = samples[sample_index]
                if value is None:
                    continue
                event_context: dict[str, JSONValue] = dict(base_context)
                event_context[self.config.channel_context_key] = channel_name
                event_context["sample_index"] = sample_index
                event_context.update(self.config.resolve_channel_context(channel_name))
                collection.append(
                    TemporalEvent(
                        timestamp=timestamp,
                        modality=modality,
                        source=source,
                        signal_type=self.config.resolve_signal_type(channel_name),
                        value=cast_value(value, self.config.value_cast),
                        unit=self.config.resolve_unit(channel_name),
                        contextual_metadata=event_context,
                        extent=extent,
                        event_kind="sample",
                        sequence_index=sample_index,
                        sync_group=sync_group,
                    )
                )

        if self.config.emit_annotations and self.config.annotations_field is not None and self.config.annotations_field in payload:
            raw_annotations = payload[self.config.annotations_field]
            if not isinstance(raw_annotations, list):
                raise TypeError("annotations_field must point to a list")
            for annotation_index, annotation in enumerate(raw_annotations, start=1):
                if not isinstance(annotation, dict):
                    raise TypeError("annotation entries must be JSON objects")
                timestamp = self._resolve_annotation_timestamp(
                    annotation=annotation,
                    start_time=timing_origin,
                    sample_rate_hz=sample_rate_hz,
                )
                duration_seconds = None
                if self.config.annotation_duration_field is not None and self.config.annotation_duration_field in annotation:
                    duration_seconds = float(annotation[self.config.annotation_duration_field])
                end = None if duration_seconds is None else timestamp + timedelta(seconds=duration_seconds)
                label = str(annotation.get(self.config.annotation_label_field, "annotation"))
                if self.config.annotation_value_field is not None and self.config.annotation_value_field in annotation:
                    value = annotation[self.config.annotation_value_field]
                else:
                    value = label
                event_context = dict(base_context)
                event_context["annotation_index"] = annotation_index
                event_context["annotation_label"] = label
                for key, extra_value in annotation.items():
                    if key in {
                        self.config.annotation_label_field,
                        self.config.annotation_value_field,
                        self.config.annotation_timestamp_field,
                        self.config.annotation_offset_field,
                        self.config.annotation_duration_field,
                    }:
                        continue
                    event_context[key] = extra_value
                collection.append(
                    TemporalEvent(
                        timestamp=timestamp,
                        modality=modality,
                        source=source,
                        signal_type=self.config.annotation_signal_type,
                        value=value,
                        unit=self.config.annotation_unit,
                        contextual_metadata=event_context,
                        extent=TemporalExtent(start=timestamp, end=end, anchor="start" if end is not None else "instant", time_scale="second"),
                        event_kind="marker",
                        sequence_index=annotation_index,
                        sync_group=_sync_group(modality, source, timestamp, label="annotation"),
                    )
                )

        collection.sort_in_place()
        return collection

    def _resolve_sample_timestamp(
        self,
        *,
        sample_index: int,
        timestamps: list[Any] | None,
        start_time: str | None,
        sample_rate_hz: float | None,
    ):
        if timestamps is not None:
            raw_timestamp = timestamps[sample_index]
            if isinstance(raw_timestamp, (int, float)):
                return coerce_timestamp(raw_timestamp, origin=start_time, unit="seconds") if start_time else coerce_timestamp(raw_timestamp)
            return coerce_timestamp(raw_timestamp)
        if start_time is None or sample_rate_hz is None:
            raise ValueError("timeseries_json requires either explicit timestamps or both start_time and sample_rate_hz")
        return coerce_timestamp(start_time) + timedelta(seconds=sample_index / sample_rate_hz)

    def _resolve_annotation_timestamp(
        self,
        *,
        annotation: dict[str, Any],
        start_time: str | None,
        sample_rate_hz: float | None,
    ):
        if self.config.annotation_timestamp_field is not None and self.config.annotation_timestamp_field in annotation:
            raw_timestamp = annotation[self.config.annotation_timestamp_field]
            if isinstance(raw_timestamp, (int, float)) and start_time is not None:
                return coerce_timestamp(raw_timestamp, origin=start_time, unit="seconds")
            return coerce_timestamp(raw_timestamp)
        if self.config.annotation_offset_field is not None and self.config.annotation_offset_field in annotation:
            if start_time is None or sample_rate_hz is None:
                raise ValueError("annotation offsets require start_time and sample_rate_hz")
            offset_samples = float(annotation[self.config.annotation_offset_field])
            return coerce_timestamp(start_time) + timedelta(seconds=offset_samples / sample_rate_hz)
        raise ValueError("annotation entry requires a timestamp or offset")


class EdfAdapter:
    def __init__(self, config: EdfConfig) -> None:
        self.config = config

    def ingest(self, input_path: str | Path) -> TemporalEventCollection:
        path = Path(input_path)
        header, measurements, annotations = iter_edf_measurements(
            path,
            include_signals=None if not self.config.include_channels else set(self.config.include_channels),
            exclude_signals=set(self.config.exclude_channels),
            max_duration_seconds=self.config.max_duration_seconds,
            max_records=self.config.max_records,
        )
        source = self.config.resolve_source(header.as_context(), fallback=path.stem)
        base_context: dict[str, JSONValue] = dict(self.config.context)
        base_context["provenance"] = {"adapter": "edf", "file": path.name}
        if self.config.include_header_context:
            base_context.update(header.as_context())

        collection = TemporalEventCollection()
        for measurement in measurements:
            signal = measurement.signal
            event_context: dict[str, JSONValue] = dict(base_context)
            event_context[self.config.channel_context_key] = signal.label
            event_context["sample_rate_hz"] = signal.sample_rate
            event_context["record_index"] = measurement.record_index
            event_context["sample_index"] = measurement.sample_index
            event_context["global_sample_index"] = measurement.global_sample_index
            if signal.transducer:
                event_context["transducer"] = signal.transducer
            if signal.prefiltering:
                event_context["prefiltering"] = signal.prefiltering
            event_context.update(self.config.resolve_channel_context(signal.label))
            collection.append(
                TemporalEvent(
                    timestamp=measurement.timestamp,
                    modality=self.config.modality,
                    source=source,
                    signal_type=self.config.resolve_signal_type(signal.label),
                    value=measurement.value,
                    unit=self.config.resolve_unit(signal.label, fallback=signal.physical_dimension),
                    contextual_metadata=event_context,
                    extent=_sample_extent(measurement.timestamp, signal.sample_rate),
                    event_kind="sample",
                    sequence_index=measurement.global_sample_index,
                    sync_group=_sync_group(self.config.modality, source, measurement.timestamp),
                )
            )

        if self.config.emit_annotations:
            for annotation_index, annotation in enumerate(annotations, start=1):
                event_context = dict(base_context)
                event_context["annotation_index"] = annotation_index
                event_context["annotation_label"] = annotation.label
                if annotation.duration is not None:
                    event_context["duration_seconds"] = annotation.duration
                event_context["record_index"] = annotation.record_index
                end = None if annotation.duration is None else annotation.timestamp + timedelta(seconds=annotation.duration)
                collection.append(
                    TemporalEvent(
                        timestamp=annotation.timestamp,
                        modality=self.config.modality,
                        source=source,
                        signal_type=self.config.annotation_signal_type,
                        value=annotation.label,
                        unit=self.config.annotation_unit,
                        contextual_metadata=event_context,
                        extent=TemporalExtent(start=annotation.timestamp, end=end, anchor="start" if end is not None else "instant", time_scale="second"),
                        event_kind="marker",
                        sequence_index=annotation_index,
                        sync_group=_sync_group(self.config.modality, source, annotation.timestamp, label="annotation"),
                    )
                )

        collection.sort_in_place()
        return collection


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return []
    if raw_text.startswith("["):
        payload = json.loads(raw_text)
        if not isinstance(payload, list):
            raise ValueError("JSON array input must contain a list of records")
        return _validate_records(payload)

    records = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    return _validate_records(records)


def _validate_records(records: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("each input record must be a JSON object")
        normalized.append(record)
    return normalized