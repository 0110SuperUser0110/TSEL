from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .models import JSONValue, TemporalEvent, TemporalExtent, coerce_timestamp

_MISSING = object()


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    raise ValueError(f"cannot coerce {value!r} to bool")


def cast_value(value: Any, cast: str | None) -> Any:
    if cast is None:
        return value
    if cast == "float":
        return float(value)
    if cast == "int":
        return int(value)
    if cast == "str":
        return str(value)
    if cast == "bool":
        return coerce_bool(value)
    raise ValueError(f"unsupported cast: {cast}")


def _optional_string(payload: dict[str, Any], key: str, default: str | None = None) -> str | None:
    if key not in payload:
        return default
    value = payload[key]
    if value is None:
        return None
    return str(value)


def _optional_field_value(spec: FieldSpec | None, record: dict[str, Any]) -> Any:
    if spec is None:
        return None
    value = spec.resolve(record)
    if value in (None, ""):
        return None
    return value


@dataclass(slots=True)
class FieldSpec:
    column: str | None = None
    literal: JSONValue | None = None
    cast: str | None = None
    origin: str | None = None
    unit: str = "seconds"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FieldSpec":
        column = payload.get("column", _MISSING)
        literal = payload.get("value", _MISSING)
        if (column is _MISSING) == (literal is _MISSING):
            raise ValueError("field spec requires exactly one of 'column' or 'value'")
        return cls(
            column=None if column is _MISSING else str(column),
            literal=None if literal is _MISSING else literal,
            cast=payload.get("cast"),
            origin=payload.get("origin"),
            unit=str(payload.get("unit", "seconds")),
        )

    def mapped_columns(self) -> set[str]:
        return {self.column} if self.column is not None else set()

    def resolve(self, record: dict[str, Any]) -> Any:
        if self.column is not None:
            if self.column not in record:
                raise KeyError(f"missing column '{self.column}' in record")
            raw_value = record[self.column]
        else:
            raw_value = self.literal
        return cast_value(raw_value, self.cast)


@dataclass(slots=True)
class ContextSpec:
    include: list[str] = field(default_factory=list)
    rename: dict[str, str] = field(default_factory=dict)
    static: dict[str, JSONValue] = field(default_factory=dict)
    capture_remaining: bool = False
    include_nulls: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContextSpec":
        if payload is None:
            return cls()
        return cls(
            include=[str(item) for item in payload.get("include", [])],
            rename={str(key): str(value) for key, value in dict(payload.get("rename", {})).items()},
            static=dict(payload.get("static", {})),
            capture_remaining=bool(payload.get("capture_remaining", False)),
            include_nulls=bool(payload.get("include_nulls", False)),
        )

    def resolve(
        self,
        record: dict[str, Any],
        mapped_columns: set[str],
        *,
        extra_context: dict[str, JSONValue] | None = None,
    ) -> dict[str, JSONValue]:
        context: dict[str, JSONValue] = dict(self.static)
        if extra_context:
            context.update(extra_context)

        included_columns: set[str] = set()
        for field_name in self.include:
            if field_name not in record:
                continue
            value = record[field_name]
            if self._skip(value):
                continue
            included_columns.add(field_name)
            context[self.rename.get(field_name, field_name)] = value

        if self.capture_remaining:
            for key, value in record.items():
                if key in mapped_columns or key in included_columns:
                    continue
                if self._skip(value):
                    continue
                context[self.rename.get(key, key)] = value

        return context

    def _skip(self, value: Any) -> bool:
        if self.include_nulls:
            return False
        return value is None or value == ""


@dataclass(slots=True)
class TemporalSemanticsSpec:
    event_kind: FieldSpec | None = None
    stream_id: FieldSpec | None = None
    sequence_index: FieldSpec | None = None
    end: FieldSpec | None = None
    duration_seconds: FieldSpec | None = None
    resolution_seconds: FieldSpec | None = None
    uncertainty_seconds: FieldSpec | None = None
    confidence: FieldSpec | None = None
    time_scale: FieldSpec | None = None
    phase: FieldSpec | None = None
    sync_group: FieldSpec | None = None
    window_id: FieldSpec | None = None
    episode_id: FieldSpec | None = None
    transition_from: FieldSpec | None = None
    transition_to: FieldSpec | None = None
    anchor: str = "instant"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TemporalSemanticsSpec":
        if payload is None:
            return cls()
        return cls(
            event_kind=None if "event_kind" not in payload else FieldSpec.from_dict(payload["event_kind"]),
            stream_id=None if "stream_id" not in payload else FieldSpec.from_dict(payload["stream_id"]),
            sequence_index=None if "sequence_index" not in payload else FieldSpec.from_dict(payload["sequence_index"]),
            end=None if "end" not in payload else FieldSpec.from_dict(payload["end"]),
            duration_seconds=None if "duration_seconds" not in payload else FieldSpec.from_dict(payload["duration_seconds"]),
            resolution_seconds=None if "resolution_seconds" not in payload else FieldSpec.from_dict(payload["resolution_seconds"]),
            uncertainty_seconds=None if "uncertainty_seconds" not in payload else FieldSpec.from_dict(payload["uncertainty_seconds"]),
            confidence=None if "confidence" not in payload else FieldSpec.from_dict(payload["confidence"]),
            time_scale=None if "time_scale" not in payload else FieldSpec.from_dict(payload["time_scale"]),
            phase=None if "phase" not in payload else FieldSpec.from_dict(payload["phase"]),
            sync_group=None if "sync_group" not in payload else FieldSpec.from_dict(payload["sync_group"]),
            window_id=None if "window_id" not in payload else FieldSpec.from_dict(payload["window_id"]),
            episode_id=None if "episode_id" not in payload else FieldSpec.from_dict(payload["episode_id"]),
            transition_from=None if "transition_from" not in payload else FieldSpec.from_dict(payload["transition_from"]),
            transition_to=None if "transition_to" not in payload else FieldSpec.from_dict(payload["transition_to"]),
            anchor=str(payload.get("anchor", "instant")),
        )

    def mapped_columns(self) -> set[str]:
        mapped: set[str] = set()
        for spec in (
            self.event_kind,
            self.stream_id,
            self.sequence_index,
            self.end,
            self.duration_seconds,
            self.resolution_seconds,
            self.uncertainty_seconds,
            self.confidence,
            self.time_scale,
            self.phase,
            self.sync_group,
            self.window_id,
            self.episode_id,
            self.transition_from,
            self.transition_to,
        ):
            if spec is not None:
                mapped.update(spec.mapped_columns())
        return mapped

    def resolve(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_kind": "observation" if self.event_kind is None else str(self.event_kind.resolve(record)),
            "stream_id": None if self.stream_id is None else str(self.stream_id.resolve(record)),
            "sequence_index": None if self.sequence_index is None else int(self.sequence_index.resolve(record)),
            "end": _optional_field_value(self.end, record),
            "duration_seconds": None if _optional_field_value(self.duration_seconds, record) is None else float(_optional_field_value(self.duration_seconds, record)),
            "resolution_seconds": None if _optional_field_value(self.resolution_seconds, record) is None else float(_optional_field_value(self.resolution_seconds, record)),
            "uncertainty_seconds": None if _optional_field_value(self.uncertainty_seconds, record) is None else float(_optional_field_value(self.uncertainty_seconds, record)),
            "confidence": None if _optional_field_value(self.confidence, record) is None else float(_optional_field_value(self.confidence, record)),
            "time_scale": None if _optional_field_value(self.time_scale, record) is None else str(_optional_field_value(self.time_scale, record)),
            "phase": None if _optional_field_value(self.phase, record) is None else str(_optional_field_value(self.phase, record)),
            "sync_group": None if _optional_field_value(self.sync_group, record) is None else str(_optional_field_value(self.sync_group, record)),
            "window_id": None if _optional_field_value(self.window_id, record) is None else str(_optional_field_value(self.window_id, record)),
            "episode_id": None if _optional_field_value(self.episode_id, record) is None else str(_optional_field_value(self.episode_id, record)),
            "transition_from": _optional_field_value(self.transition_from, record),
            "transition_to": _optional_field_value(self.transition_to, record),
            "anchor": self.anchor,
        }


@dataclass(slots=True)
class RecordMapping:
    timestamp: FieldSpec
    modality: FieldSpec
    source: FieldSpec
    signal_type: FieldSpec
    value: FieldSpec
    unit: FieldSpec
    context: ContextSpec = field(default_factory=ContextSpec)
    temporal: TemporalSemanticsSpec = field(default_factory=TemporalSemanticsSpec)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecordMapping":
        return cls(
            timestamp=FieldSpec.from_dict(payload["timestamp"]),
            modality=FieldSpec.from_dict(payload["modality"]),
            source=FieldSpec.from_dict(payload["source"]),
            signal_type=FieldSpec.from_dict(payload["signal_type"]),
            value=FieldSpec.from_dict(payload["value"]),
            unit=FieldSpec.from_dict(payload["unit"]),
            context=ContextSpec.from_dict(payload.get("context")),
            temporal=TemporalSemanticsSpec.from_dict(payload.get("temporal")),
        )

    def transform(
        self,
        record: dict[str, Any],
        *,
        extra_context: dict[str, JSONValue] | None = None,
    ) -> TemporalEvent:
        mapped_columns = set()

        timestamp_value = self.timestamp.resolve(record)
        mapped_columns.update(self.timestamp.mapped_columns())

        modality = self.modality.resolve(record)
        mapped_columns.update(self.modality.mapped_columns())

        source = self.source.resolve(record)
        mapped_columns.update(self.source.mapped_columns())

        signal_type = self.signal_type.resolve(record)
        mapped_columns.update(self.signal_type.mapped_columns())

        value = self.value.resolve(record)
        mapped_columns.update(self.value.mapped_columns())

        unit = self.unit.resolve(record)
        mapped_columns.update(self.unit.mapped_columns())

        temporal = self.temporal.resolve(record)
        mapped_columns.update(self.temporal.mapped_columns())

        context = self.context.resolve(record, mapped_columns, extra_context=extra_context)

        start = coerce_timestamp(timestamp_value, origin=self.timestamp.origin, unit=self.timestamp.unit)
        end = None
        if temporal["end"] is not None:
            end = coerce_timestamp(temporal["end"])
        elif temporal["duration_seconds"] is not None:
            end = start + timedelta(seconds=temporal["duration_seconds"])
        elif temporal["resolution_seconds"] is not None:
            end = start + timedelta(seconds=temporal["resolution_seconds"])

        anchor = temporal["anchor"]
        if anchor == "instant" and end is not None:
            anchor = "start"

        extent = TemporalExtent(
            start=start,
            end=end,
            anchor=anchor,
            resolution_seconds=temporal["resolution_seconds"],
            uncertainty_seconds=temporal["uncertainty_seconds"],
            time_scale=temporal["time_scale"],
        )

        return TemporalEvent(
            timestamp=extent.timestamp,
            modality=str(modality),
            source=str(source),
            signal_type=str(signal_type),
            value=value,
            unit=str(unit),
            contextual_metadata=context,
            extent=extent,
            event_kind=str(temporal["event_kind"]),
            stream_id=temporal["stream_id"],
            sequence_index=temporal["sequence_index"],
            confidence=temporal["confidence"],
            phase=temporal["phase"],
            sync_group=temporal["sync_group"],
            window_id=temporal["window_id"],
            episode_id=temporal["episode_id"],
            transition_from=temporal["transition_from"],
            transition_to=temporal["transition_to"],
        )


@dataclass(slots=True)
class TimeSeriesChannelSpec:
    signal_type: str
    unit: str
    cast: str = "float"
    context: dict[str, JSONValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimeSeriesChannelSpec":
        return cls(
            signal_type=str(payload["signal_type"]),
            unit=str(payload["unit"]),
            cast=str(payload.get("cast", "float")),
            context=dict(payload.get("context", {})),
        )

    def resolve_value(self, raw_value: Any) -> Any:
        return cast_value(raw_value, self.cast)


@dataclass(slots=True)
class AutoChannelSpec:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    default_signal_type: str = "measurement"
    signal_type_strategy: str = "channel_name"
    default_unit: str = "a.u."
    channel_units: dict[str, str] = field(default_factory=dict)
    channel_signal_types: dict[str, str] = field(default_factory=dict)
    cast: str = "float"
    context: dict[str, JSONValue] = field(default_factory=dict)
    channel_context: dict[str, dict[str, JSONValue]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutoChannelSpec":
        return cls(
            include=[str(item) for item in payload.get("include", [])],
            exclude=[str(item) for item in payload.get("exclude", [])],
            default_signal_type=str(payload.get("default_signal_type", "measurement")),
            signal_type_strategy=str(payload.get("signal_type_strategy", "channel_name")),
            default_unit=str(payload.get("default_unit", "a.u.")),
            channel_units={str(key): str(value) for key, value in dict(payload.get("channel_units", {})).items()},
            channel_signal_types={str(key): str(value) for key, value in dict(payload.get("channel_signal_types", {})).items()},
            cast=str(payload.get("cast", "float")),
            context=dict(payload.get("context", {})),
            channel_context={str(key): dict(value) for key, value in dict(payload.get("channel_context", {})).items()},
        )

    def build_channels(self, record_keys: list[str], mapped_columns: set[str]) -> dict[str, TimeSeriesChannelSpec]:
        if self.include:
            channel_names = [name for name in self.include if name in record_keys]
        else:
            channel_names = [name for name in record_keys if name not in mapped_columns and name not in self.exclude]

        channels: dict[str, TimeSeriesChannelSpec] = {}
        for channel_name in channel_names:
            if channel_name in self.channel_signal_types:
                signal_type = self.channel_signal_types[channel_name]
            elif self.signal_type_strategy == "channel_name":
                signal_type = channel_name
            else:
                signal_type = self.default_signal_type

            channels[channel_name] = TimeSeriesChannelSpec(
                signal_type=signal_type,
                unit=self.channel_units.get(channel_name, self.default_unit),
                cast=self.cast,
                context={**self.context, **self.channel_context.get(channel_name, {})},
            )
        return channels


@dataclass(slots=True)
class TimeSeriesMapping:
    timestamp: FieldSpec
    modality: FieldSpec
    source: FieldSpec
    channels: dict[str, TimeSeriesChannelSpec] = field(default_factory=dict)
    auto_channels: AutoChannelSpec | None = None
    sample_rate: FieldSpec | None = None
    context: ContextSpec = field(default_factory=ContextSpec)
    channel_context_key: str = "channel"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimeSeriesMapping":
        raw_channels = payload.get("channels")
        raw_auto_channels = payload.get("auto_channels")
        if bool(raw_channels) == bool(raw_auto_channels):
            raise ValueError("timeseries config requires exactly one of 'channels' or 'auto_channels'")
        return cls(
            timestamp=FieldSpec.from_dict(payload["timestamp"]),
            modality=FieldSpec.from_dict(payload["modality"]),
            source=FieldSpec.from_dict(payload["source"]),
            channels={} if not raw_channels else {name: TimeSeriesChannelSpec.from_dict(config) for name, config in raw_channels.items()},
            auto_channels=None if not raw_auto_channels else AutoChannelSpec.from_dict(raw_auto_channels),
            sample_rate=None if "sample_rate" not in payload else FieldSpec.from_dict(payload["sample_rate"]),
            context=ContextSpec.from_dict(payload.get("context")),
            channel_context_key=str(payload.get("channel_context_key", "channel")),
        )

    def resolve_channels(self, record: dict[str, Any]) -> dict[str, TimeSeriesChannelSpec]:
        if self.channels:
            return self.channels
        if self.auto_channels is None:
            raise ValueError("timeseries mapping is missing channel definitions")
        mapped_columns = self.timestamp.mapped_columns() | self.modality.mapped_columns() | self.source.mapped_columns()
        if self.sample_rate is not None:
            mapped_columns.update(self.sample_rate.mapped_columns())
        return self.auto_channels.build_channels(list(record.keys()), mapped_columns)

    def resolve_sample_rate(self, record: dict[str, Any]) -> float | None:
        if self.sample_rate is None:
            return None
        return float(self.sample_rate.resolve(record))


@dataclass(slots=True)
class TimeSeriesJsonConfig:
    modality: str | None = None
    modality_field: str | None = None
    source: str | None = None
    source_field: str | None = "source"
    start_time_field: str | None = "start_time"
    timestamps_field: str | None = None
    sample_rate_field: str | None = "sample_rate_hz"
    default_sample_rate_hz: float | None = None
    metadata_field: str | None = "metadata"
    channels_field: str = "channels"
    annotations_field: str | None = "annotations"
    default_signal_type: str = "measurement"
    signal_type_strategy: str = "channel_name"
    default_unit: str = "a.u."
    channel_units: dict[str, str] = field(default_factory=dict)
    channel_signal_types: dict[str, str] = field(default_factory=dict)
    channel_context: dict[str, dict[str, JSONValue]] = field(default_factory=dict)
    context: dict[str, JSONValue] = field(default_factory=dict)
    channel_context_key: str = "channel"
    value_cast: str = "float"
    emit_annotations: bool = True
    annotation_signal_type: str = "annotation"
    annotation_unit: str = "label"
    annotation_label_field: str = "label"
    annotation_value_field: str | None = None
    annotation_timestamp_field: str | None = "timestamp"
    annotation_offset_field: str | None = "offset_samples"
    annotation_duration_field: str | None = "duration_seconds"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TimeSeriesJsonConfig":
        return cls(
            modality=_optional_string(payload, "modality"),
            modality_field=_optional_string(payload, "modality_field"),
            source=_optional_string(payload, "source"),
            source_field=_optional_string(payload, "source_field", "source"),
            start_time_field=_optional_string(payload, "start_time_field", "start_time"),
            timestamps_field=_optional_string(payload, "timestamps_field"),
            sample_rate_field=_optional_string(payload, "sample_rate_field", "sample_rate_hz"),
            default_sample_rate_hz=None if payload.get("default_sample_rate_hz") is None else float(payload.get("default_sample_rate_hz")),
            metadata_field=_optional_string(payload, "metadata_field", "metadata"),
            channels_field=str(payload.get("channels_field", "channels")),
            annotations_field=_optional_string(payload, "annotations_field", "annotations"),
            default_signal_type=str(payload.get("default_signal_type", "measurement")),
            signal_type_strategy=str(payload.get("signal_type_strategy", "channel_name")),
            default_unit=str(payload.get("default_unit", "a.u.")),
            channel_units={str(key): str(value) for key, value in dict(payload.get("channel_units", {})).items()},
            channel_signal_types={str(key): str(value) for key, value in dict(payload.get("channel_signal_types", {})).items()},
            channel_context={str(key): dict(value) for key, value in dict(payload.get("channel_context", {})).items()},
            context=dict(payload.get("context", {})),
            channel_context_key=str(payload.get("channel_context_key", "channel")),
            value_cast=str(payload.get("value_cast", "float")),
            emit_annotations=bool(payload.get("emit_annotations", True)),
            annotation_signal_type=str(payload.get("annotation_signal_type", "annotation")),
            annotation_unit=str(payload.get("annotation_unit", "label")),
            annotation_label_field=str(payload.get("annotation_label_field", "label")),
            annotation_value_field=_optional_string(payload, "annotation_value_field"),
            annotation_timestamp_field=_optional_string(payload, "annotation_timestamp_field", "timestamp"),
            annotation_offset_field=_optional_string(payload, "annotation_offset_field", "offset_samples"),
            annotation_duration_field=_optional_string(payload, "annotation_duration_field", "duration_seconds"),
        )

    def resolve_modality(self, payload: dict[str, Any]) -> str:
        if self.modality is not None:
            return self.modality
        if self.modality_field is not None and self.modality_field in payload:
            return str(payload[self.modality_field])
        raise ValueError("timeseries_json config requires 'modality' or 'modality_field'")

    def resolve_source(self, payload: dict[str, Any], *, fallback: str) -> str:
        if self.source is not None:
            return self.source
        if self.source_field is not None and self.source_field in payload:
            return str(payload[self.source_field])
        return fallback

    def resolve_signal_type(self, channel_name: str) -> str:
        if channel_name in self.channel_signal_types:
            return self.channel_signal_types[channel_name]
        if self.signal_type_strategy == "channel_name":
            return channel_name
        return self.default_signal_type

    def resolve_unit(self, channel_name: str) -> str:
        return self.channel_units.get(channel_name, self.default_unit)

    def resolve_channel_context(self, channel_name: str) -> dict[str, JSONValue]:
        return dict(self.channel_context.get(channel_name, {}))


@dataclass(slots=True)
class EdfConfig:
    modality: str = "eeg"
    source_strategy: str = "recording_id"
    source_value: str | None = None
    source_header_field: str | None = None
    default_signal_type: str = "voltage"
    signal_type_strategy: str = "literal"
    default_unit: str = "a.u."
    channel_units: dict[str, str] = field(default_factory=dict)
    channel_signal_types: dict[str, str] = field(default_factory=dict)
    channel_context: dict[str, dict[str, JSONValue]] = field(default_factory=dict)
    context: dict[str, JSONValue] = field(default_factory=dict)
    channel_context_key: str = "channel"
    include_header_context: bool = True
    emit_annotations: bool = True
    annotation_signal_type: str = "annotation"
    annotation_unit: str = "label"
    include_channels: list[str] = field(default_factory=list)
    exclude_channels: list[str] = field(default_factory=list)
    max_duration_seconds: float | None = None
    max_records: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EdfConfig":
        return cls(
            modality=str(payload.get("modality", "eeg")),
            source_strategy=str(payload.get("source_strategy", "recording_id")),
            source_value=_optional_string(payload, "source_value"),
            source_header_field=_optional_string(payload, "source_header_field"),
            default_signal_type=str(payload.get("default_signal_type", "voltage")),
            signal_type_strategy=str(payload.get("signal_type_strategy", "literal")),
            default_unit=str(payload.get("default_unit", "a.u.")),
            channel_units={str(key): str(value) for key, value in dict(payload.get("channel_units", {})).items()},
            channel_signal_types={str(key): str(value) for key, value in dict(payload.get("channel_signal_types", {})).items()},
            channel_context={str(key): dict(value) for key, value in dict(payload.get("channel_context", {})).items()},
            context=dict(payload.get("context", {})),
            channel_context_key=str(payload.get("channel_context_key", "channel")),
            include_header_context=bool(payload.get("include_header_context", True)),
            emit_annotations=bool(payload.get("emit_annotations", True)),
            annotation_signal_type=str(payload.get("annotation_signal_type", "annotation")),
            annotation_unit=str(payload.get("annotation_unit", "label")),
            include_channels=[str(value) for value in payload.get("include_channels", [])],
            exclude_channels=[str(value) for value in payload.get("exclude_channels", [])],
            max_duration_seconds=None if payload.get("max_duration_seconds") is None else float(payload.get("max_duration_seconds")),
            max_records=None if payload.get("max_records") is None else int(payload.get("max_records")),
        )

    def resolve_source(self, header: dict[str, Any], *, fallback: str) -> str:
        strategy = self.source_strategy
        if strategy == "literal":
            if self.source_value is None:
                raise ValueError("edf config with source_strategy='literal' requires source_value")
            return self.source_value
        if strategy == "file_name":
            return fallback
        if strategy == "patient_id":
            return str(header.get("patient_id") or fallback)
        if strategy == "header_field":
            if self.source_header_field is None:
                raise ValueError("edf config with source_strategy='header_field' requires source_header_field")
            return str(header.get(self.source_header_field) or fallback)
        return str(header.get("recording_id") or fallback)

    def resolve_signal_type(self, channel_name: str) -> str:
        if channel_name in self.channel_signal_types:
            return self.channel_signal_types[channel_name]
        if self.signal_type_strategy == "channel_name":
            return channel_name
        return self.default_signal_type

    def resolve_unit(self, channel_name: str, *, fallback: str) -> str:
        return self.channel_units.get(channel_name, fallback or self.default_unit)

    def resolve_channel_context(self, channel_name: str) -> dict[str, JSONValue]:
        return dict(self.channel_context.get(channel_name, {}))
