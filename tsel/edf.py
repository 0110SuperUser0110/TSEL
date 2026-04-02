from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct


@dataclass(slots=True)
class EdfSignalHeader:
    label: str
    transducer: str
    physical_dimension: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    prefiltering: str
    samples_per_record: int
    reserved: str
    record_duration: float

    @property
    def sample_rate(self) -> float:
        if self.record_duration <= 0:
            raise ValueError("EDF record duration must be positive")
        return self.samples_per_record / self.record_duration

    @property
    def is_annotation(self) -> bool:
        return self.label.lower().startswith("edf annotations")

    def scale(self, digital_value: int) -> float:
        digital_span = self.digital_max - self.digital_min
        if digital_span == 0:
            return float(self.physical_min)
        physical_span = self.physical_max - self.physical_min
        return ((digital_value - self.digital_min) * physical_span / digital_span) + self.physical_min


@dataclass(slots=True)
class EdfHeader:
    version: str
    patient_id: str
    recording_id: str
    start_datetime: datetime
    header_bytes: int
    reserved: str
    data_records: int
    record_duration: float
    signals: list[EdfSignalHeader]

    @property
    def bytes_per_record(self) -> int:
        return sum(signal.samples_per_record * 2 for signal in self.signals)

    def as_context(self) -> dict[str, str | float | int]:
        return {
            "edf_version": self.version,
            "patient_id": self.patient_id,
            "recording_id": self.recording_id,
            "record_duration_seconds": self.record_duration,
            "data_records": self.data_records,
        }


@dataclass(slots=True)
class EdfMeasurement:
    signal: EdfSignalHeader
    timestamp: datetime
    value: float
    record_index: int
    sample_index: int
    global_sample_index: int


@dataclass(slots=True)
class EdfAnnotation:
    timestamp: datetime
    label: str
    duration: float | None
    record_index: int


def read_edf_header(path: str | Path) -> EdfHeader:
    input_path = Path(path)
    with input_path.open("rb") as handle:
        version = _read_ascii(handle, 8)
        patient_id = _read_ascii(handle, 80)
        recording_id = _read_ascii(handle, 80)
        start_date = _read_ascii(handle, 8)
        start_time = _read_ascii(handle, 8)
        header_bytes = _parse_int(_read_ascii(handle, 8))
        reserved = _read_ascii(handle, 44)
        data_records = _parse_int(_read_ascii(handle, 8))
        record_duration = _parse_float(_read_ascii(handle, 8))
        signal_count = _parse_int(_read_ascii(handle, 4))

        labels = _read_ascii_array(handle, 16, signal_count)
        transducers = _read_ascii_array(handle, 80, signal_count)
        physical_dimensions = _read_ascii_array(handle, 8, signal_count)
        physical_mins = _read_float_array(handle, 8, signal_count)
        physical_maxes = _read_float_array(handle, 8, signal_count)
        digital_mins = _read_int_array(handle, 8, signal_count)
        digital_maxes = _read_int_array(handle, 8, signal_count)
        prefilterings = _read_ascii_array(handle, 80, signal_count)
        samples_per_record = _read_int_array(handle, 8, signal_count)
        reserves = _read_ascii_array(handle, 32, signal_count)

        start_datetime = _parse_start_datetime(start_date, start_time)
        signals = [
            EdfSignalHeader(
                label=labels[index],
                transducer=transducers[index],
                physical_dimension=physical_dimensions[index],
                physical_min=physical_mins[index],
                physical_max=physical_maxes[index],
                digital_min=digital_mins[index],
                digital_max=digital_maxes[index],
                prefiltering=prefilterings[index],
                samples_per_record=samples_per_record[index],
                reserved=reserves[index],
                record_duration=record_duration,
            )
            for index in range(signal_count)
        ]

    return EdfHeader(
        version=version,
        patient_id=patient_id,
        recording_id=recording_id,
        start_datetime=start_datetime,
        header_bytes=header_bytes,
        reserved=reserved,
        data_records=data_records,
        record_duration=record_duration,
        signals=signals,
    )


def iter_edf_measurements(
    path: str | Path,
    *,
    include_signals: set[str] | None = None,
    exclude_signals: set[str] | None = None,
    max_duration_seconds: float | None = None,
    max_records: int | None = None,
) -> tuple[EdfHeader, list[EdfMeasurement], list[EdfAnnotation]]:
    input_path = Path(path)
    header = read_edf_header(input_path)
    record_count = header.data_records
    if record_count < 0:
        file_size = input_path.stat().st_size
        remaining_bytes = file_size - header.header_bytes
        if remaining_bytes < 0 or header.bytes_per_record == 0:
            raise ValueError("unable to infer EDF record count")
        record_count = remaining_bytes // header.bytes_per_record

    include_signal_set = None if include_signals is None else set(include_signals)
    exclude_signal_set = set() if exclude_signals is None else set(exclude_signals)
    cutoff = None if max_duration_seconds is None else header.start_datetime + timedelta(seconds=max_duration_seconds)

    measurements: list[EdfMeasurement] = []
    annotations: list[EdfAnnotation] = []
    with input_path.open("rb") as handle:
        handle.seek(header.header_bytes)
        global_indexes = {signal.label: 0 for signal in header.signals}
        for record_index in range(record_count):
            if max_records is not None and record_index >= max_records:
                break
            record_start = header.start_datetime + timedelta(seconds=record_index * header.record_duration)
            if cutoff is not None and record_start >= cutoff:
                break
            for signal in header.signals:
                raw_bytes = handle.read(signal.samples_per_record * 2)
                if len(raw_bytes) != signal.samples_per_record * 2:
                    raise ValueError("unexpected end of EDF file while reading signal data")
                if signal.is_annotation:
                    parsed_annotations = _parse_annotations(raw_bytes, record_start, record_index)
                    if cutoff is not None:
                        parsed_annotations = [annotation for annotation in parsed_annotations if annotation.timestamp < cutoff]
                    annotations.extend(parsed_annotations)
                    continue
                if include_signal_set is not None and signal.label not in include_signal_set:
                    continue
                if signal.label in exclude_signal_set:
                    continue

                for sample_index, (digital_value,) in enumerate(struct.iter_unpack("<h", raw_bytes)):
                    timestamp = record_start + timedelta(seconds=sample_index / signal.sample_rate)
                    if cutoff is not None and timestamp >= cutoff:
                        break
                    global_sample_index = global_indexes[signal.label]
                    measurements.append(
                        EdfMeasurement(
                            signal=signal,
                            timestamp=timestamp,
                            value=signal.scale(digital_value),
                            record_index=record_index,
                            sample_index=sample_index,
                            global_sample_index=global_sample_index,
                        )
                    )
                    global_indexes[signal.label] = global_sample_index + 1

    return header, measurements, annotations


def _parse_annotations(raw_bytes: bytes, record_start: datetime, record_index: int) -> list[EdfAnnotation]:
    text = raw_bytes.decode("latin-1", errors="ignore")
    chunks = [chunk for chunk in text.split("\x00") if chunk]
    annotations: list[EdfAnnotation] = []
    for chunk in chunks:
        parts = [part for part in chunk.split("\x14") if part]
        if not parts:
            continue
        onset_part = parts[0]
        duration: float | None = None
        if "\x15" in onset_part:
            onset_text, duration_text = onset_part.split("\x15", 1)
            duration = _safe_float(duration_text)
        else:
            onset_text = onset_part
        onset = _safe_float(onset_text)
        if onset is None:
            continue
        labels = parts[1:] if len(parts) > 1 else []
        for label in labels:
            annotations.append(
                EdfAnnotation(
                    timestamp=record_start + timedelta(seconds=onset),
                    label=label,
                    duration=duration,
                    record_index=record_index,
                )
            )
    return annotations


def _read_ascii(handle, width: int) -> str:
    return handle.read(width).decode("ascii", errors="ignore").strip()


def _read_ascii_array(handle, width: int, count: int) -> list[str]:
    return [_read_ascii(handle, width) for _ in range(count)]


def _read_int_array(handle, width: int, count: int) -> list[int]:
    return [_parse_int(_read_ascii(handle, width)) for _ in range(count)]


def _read_float_array(handle, width: int, count: int) -> list[float]:
    return [_parse_float(_read_ascii(handle, width)) for _ in range(count)]


def _parse_int(value: str) -> int:
    stripped = value.strip() or "0"
    return int(stripped)


def _parse_float(value: str) -> float:
    stripped = value.strip() or "0"
    return float(stripped)


def _safe_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return float(stripped)
    except ValueError:
        return None


def _parse_start_datetime(start_date: str, start_time: str) -> datetime:
    day, month, year = [int(part) for part in start_date.split(".")]
    hour, minute, second = [int(part) for part in start_time.split(".")]
    full_year = 1900 + year if year >= 85 else 2000 + year
    return datetime(full_year, month, day, hour, minute, second, tzinfo=timezone.utc)
