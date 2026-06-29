from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import CsvAdapter, EdfAdapter, JsonAdapter, TimeSeriesCsvAdapter, TimeSeriesJsonAdapter
from .autorouting import AutoIngestPlan, _read_json, _read_table, build_auto_ingest_plan, looks_like_normalized_tsel
from .eeg_profiles import merge_eeg_domain_profile_into_config, resolve_eeg_edf_profile, resolve_eeg_json_profile, resolve_eeg_table_profile
from .general_profiles import (
    merge_general_domain_profile_into_config,
    resolve_dream_json_profile,
    resolve_dream_table_profile,
    resolve_environment_json_profile,
    resolve_environment_table_profile,
    resolve_multisensory_json_profile,
    resolve_multisensory_table_profile,
)
from .olfactory_profiles import merge_domain_profile_into_config, resolve_olfactory_json_profile, resolve_olfactory_table_profile
from .config import EdfConfig, RecordMapping, TimeSeriesJsonConfig, TimeSeriesMapping
from .experience import enrich_experience
from .models import TemporalEventCollection
from .packet_profiles import plan_special_packet
from .standards import available_sensory_profiles, infer_sensory_profile, normalize_sensory_profile, validate_sensory_profile


_AUTO_PACKET_SUFFIXES = {".csv", ".tsv", ".txt", ".json", ".jsonl", ".edf"}


@dataclass(slots=True)
class InputJob:
    input_path: Path
    config_path: Path
    sensory_profile: str | None = None


class TSELPipeline:
    def __init__(self, *, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode

    def ingest(
        self,
        input_path: str | Path,
        config: dict[str, Any] | str | Path,
        *,
        sensory_profile: str | None = None,
    ) -> TemporalEventCollection:
        config_data = self._load_config(config)
        active_profile = normalize_sensory_profile(
            sensory_profile or str(config_data.get("sensory_profile") or infer_sensory_profile(config_data))
        )
        config_data = self._apply_domain_profile_layer(input_path, config_data, active_profile)
        validate_sensory_profile(config_data, active_profile)
        collection = self._ingest_with_config(input_path, config_data)
        return enrich_experience(collection, strict=self.strict_mode)

    def plan_auto_ingest(self, input_path: str | Path, sensory_profile: str) -> AutoIngestPlan:
        return build_auto_ingest_plan(input_path, sensory_profile)

    def discover_auto_inputs(self, input_path: str | Path) -> list[Path]:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"input path not found: {path}")
        if path.is_file():
            return [path]

        discovered = [
            candidate
            for candidate in sorted(path.rglob("*"))
            if candidate.is_file()
            and candidate.suffix.lower() in _AUTO_PACKET_SUFFIXES
            and not looks_like_normalized_tsel(candidate)
        ]
        if not discovered:
            raise ValueError(f"no supported raw sensory files were found in {path}")
        return discovered

    def plan_auto_packet(self, input_path: str | Path, sensory_profile: str) -> list[AutoIngestPlan]:
        normalized_profile = normalize_sensory_profile(sensory_profile)
        special_plans = plan_special_packet(input_path, normalized_profile)
        if special_plans is not None:
            return special_plans
        return [self.plan_auto_ingest(candidate, normalized_profile) for candidate in self.discover_auto_inputs(input_path)]

    def ingest_auto_plans(self, plans: list[AutoIngestPlan]) -> TemporalEventCollection:
        if not plans:
            raise ValueError("at least one automatic ingest plan is required")
        merged = TemporalEventCollection()
        for plan in plans:
            partial = self._ingest_with_config(plan.input_path, plan.config)
            merged.extend(partial.events)
        merged.sort_in_place()
        return enrich_experience(merged, strict=self.strict_mode)

    def ingest_auto(self, input_path: str | Path, sensory_profile: str) -> TemporalEventCollection:
        plans = self.plan_auto_packet(input_path, sensory_profile)
        return self.ingest_auto_plans(plans)

    def ingest_file(self, input_path: str | Path, *, sensory_profile: str | None = None) -> TemporalEventCollection:
        path = Path(input_path)
        if path.is_file() and looks_like_normalized_tsel(path):
            from .serializers import load_events

            return load_events(path)
        return self.ingest_auto(path, sensory_profile or "generic")

    def ingest_many(self, jobs: list[InputJob]) -> TemporalEventCollection:
        merged = TemporalEventCollection()
        for job in jobs:
            collection = self.ingest(job.input_path, job.config_path, sensory_profile=job.sensory_profile)
            merged.extend(collection.events)
        merged.sort_in_place()
        return merged

    def load_manifest(self, manifest_path: str | Path) -> list[InputJob]:
        path = Path(manifest_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_jobs = payload.get("jobs", [])
        if not isinstance(raw_jobs, list) or not raw_jobs:
            raise ValueError("manifest must contain a non-empty 'jobs' list")

        jobs: list[InputJob] = []
        for raw_job in raw_jobs:
            if not isinstance(raw_job, dict):
                raise TypeError("each manifest job must be an object")
            input_path = (path.parent / raw_job["input"]).resolve()
            config_path = (path.parent / raw_job["config"]).resolve()
            profile = raw_job.get("profile", raw_job.get("sensory_profile"))
            jobs.append(
                InputJob(
                    input_path=input_path,
                    config_path=config_path,
                    sensory_profile=None if profile is None else normalize_sensory_profile(str(profile)),
                )
            )
        return jobs

    def supported_sensory_profiles(self) -> list[str]:
        return available_sensory_profiles()

    def infer_sensory_profile(self, config: dict[str, Any] | str | Path) -> str:
        return infer_sensory_profile(self._load_config(config))

    def _apply_domain_profile_layer(self, input_path: str | Path, config_data: dict[str, Any], active_profile: str) -> dict[str, Any]:
        path = Path(input_path)
        if not path.exists() or path.is_dir():
            return config_data
        suffix = path.suffix.lower()
        resolution = None
        if active_profile == "olfaction":
            if suffix in {".csv", ".tsv", ".txt"}:
                preview = _read_table(path)
                resolution = resolve_olfactory_table_profile(path, preview.fieldnames, preview.rows)
            elif suffix in {".json", ".jsonl"}:
                resolution = resolve_olfactory_json_profile(path, _read_json(path))
            else:
                return config_data
            if resolution.profile_id is None or resolution.resolution_status in {"ambiguous", "unresolved"}:
                return config_data
            return merge_domain_profile_into_config(config_data, resolution)
        if active_profile == "eeg":
            if suffix in {".csv", ".tsv", ".txt"}:
                preview = _read_table(path)
                resolution = resolve_eeg_table_profile(path, preview.fieldnames, preview.rows)
            elif suffix in {".json", ".jsonl"}:
                resolution = resolve_eeg_json_profile(path, _read_json(path))
            elif suffix == ".edf":
                resolution = resolve_eeg_edf_profile(path)
            else:
                return config_data
            if resolution.profile_id is None or resolution.resolution_status in {"ambiguous", "unresolved"}:
                return config_data
            return merge_eeg_domain_profile_into_config(config_data, resolution)
        if active_profile == "dream":
            if suffix in {".csv", ".tsv", ".txt"}:
                preview = _read_table(path)
                resolution = resolve_dream_table_profile(path, preview.fieldnames)
            elif suffix in {".json", ".jsonl"}:
                resolution = resolve_dream_json_profile(path, _read_json(path))
            else:
                return config_data
            if resolution.profile_id is None or resolution.resolution_status in {"ambiguous", "unresolved"}:
                return config_data
            return merge_general_domain_profile_into_config(config_data, resolution)
        if active_profile == "environment":
            if suffix in {".csv", ".tsv", ".txt"}:
                preview = _read_table(path)
                resolution = resolve_environment_table_profile(path, preview.fieldnames, preview.rows)
            elif suffix in {".json", ".jsonl"}:
                resolution = resolve_environment_json_profile(path, _read_json(path))
            else:
                return config_data
            if resolution.profile_id is None or resolution.resolution_status in {"ambiguous", "unresolved"}:
                return config_data
            return merge_general_domain_profile_into_config(config_data, resolution)
        if active_profile == "multisensory":
            if suffix in {".csv", ".tsv", ".txt"}:
                preview = _read_table(path)
                resolution = resolve_multisensory_table_profile(path, preview.fieldnames, preview.rows)
            elif suffix in {".json", ".jsonl"}:
                resolution = resolve_multisensory_json_profile(path, _read_json(path))
            else:
                return config_data
            if resolution.profile_id is None or resolution.resolution_status in {"ambiguous", "unresolved"}:
                return config_data
            return merge_general_domain_profile_into_config(config_data, resolution)
        return config_data

    def _ingest_with_config(self, input_path: str | Path, config_data: dict[str, Any]) -> TemporalEventCollection:
        adapter_name = str(config_data["adapter"])

        if adapter_name == "csv":
            mapping = RecordMapping.from_dict(config_data["mapping"])
            adapter = CsvAdapter(mapping, delimiter=str(config_data.get("delimiter", ",")))
            return adapter.ingest(input_path)
        if adapter_name == "json":
            mapping = RecordMapping.from_dict(config_data["mapping"])
            adapter = JsonAdapter(mapping)
            return adapter.ingest(input_path)
        if adapter_name == "timeseries_csv":
            mapping = TimeSeriesMapping.from_dict(config_data)
            adapter = TimeSeriesCsvAdapter(mapping, delimiter=str(config_data.get("delimiter", ",")))
            return adapter.ingest(input_path)
        if adapter_name == "timeseries_json":
            adapter = TimeSeriesJsonAdapter(TimeSeriesJsonConfig.from_dict(config_data))
            return adapter.ingest(input_path)
        if adapter_name == "edf":
            adapter = EdfAdapter(EdfConfig.from_dict(config_data))
            return adapter.ingest(input_path)

        raise ValueError(f"unsupported adapter: {adapter_name}")

    def _load_config(self, config: dict[str, Any] | str | Path) -> dict[str, Any]:
        if isinstance(config, dict):
            return config
        path = Path(config)
        return json.loads(path.read_text(encoding="utf-8"))






