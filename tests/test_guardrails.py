from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tsel.autorouting import AutoRoutingError, build_auto_ingest_plan
from tsel.experience import enrich_experience
from tsel.models import TemporalEvent, TemporalEventCollection, TemporalExtent
from tsel.pipeline import TSELPipeline

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output' / '_guardrails'
BASE_TIME = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)


def _time(offset_seconds: int | float) -> datetime:
    return BASE_TIME + timedelta(seconds=float(offset_seconds))



def _test_file(name: str) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    return OUTPUT / name



def _sample(
    second: int | float,
    value: float,
    *,
    source: str = 'SESSION-01',
    channel: str = 'Fp1',
    sequence_index: int | None = None,
) -> TemporalEvent:
    return TemporalEvent(
        timestamp=_time(second),
        modality='eeg',
        source=source,
        signal_type='voltage',
        value=value,
        unit='uV',
        contextual_metadata={'channel': channel, 'sample_rate_hz': 1.0},
        extent=TemporalExtent.from_timestamp(_time(second), resolution_seconds=1.0, time_scale='sample'),
        event_kind='sample',
        sequence_index=sequence_index,
        stream_id=f'eeg::{source}::{channel}::voltage',
    )



def _marker(
    second: int | float,
    label: str,
    *,
    source: str = 'SESSION-01',
    marker_type: str = 'stimulus',
) -> TemporalEvent:
    return TemporalEvent(
        timestamp=_time(second),
        modality='eeg',
        source=source,
        signal_type='marker',
        value=label,
        unit='event',
        contextual_metadata={'annotation_label': label, 'marker_type': marker_type},
        event_kind='marker',
        stream_id=f'eeg::{source}::marker',
    )



def test_pipeline_defaults_to_strict_mode() -> None:
    pipeline = TSELPipeline()

    assert pipeline.strict_mode is True



def test_null_structure_does_not_invent_phase_or_experience_claims() -> None:
    collection = TemporalEventCollection(
        [
            _sample(0, 0.1, sequence_index=0),
            _sample(1, 0.2, sequence_index=1),
            _sample(2, 0.15, sequence_index=2),
        ]
    )

    enriched = enrich_experience(collection)

    assert all(event.phase is None for event in enriched.events)
    assert all('experience' not in event.contextual_metadata for event in enriched.events)
    assert all('stimulus' not in event.contextual_metadata for event in enriched.events)



def test_ambiguous_route_does_not_guess_between_eeg_and_olfaction() -> None:
    input_path = _test_file('ambiguous_route.csv')
    input_path.write_text(
        'timestamp,source,sample_rate_hz,Fp1,odor_intensity\n'
        '2026-03-15T12:00:00Z,SESSION-01,4,10.0,0.8\n',
        encoding='utf-8',
    )

    with pytest.raises(AutoRoutingError, match='ambiguous deterministic route evidence'):
        build_auto_ingest_plan(input_path, 'generic')



def test_missing_context_does_not_fabricate_stimulus_blocks() -> None:
    collection = TemporalEventCollection(
        [
            _sample(0, 0.1, sequence_index=0),
            _marker(1, 'task_onset', marker_type='behavior'),
            _sample(1, 0.2, sequence_index=1),
            _sample(2, 0.3, sequence_index=2),
            _marker(3, 'task_offset', marker_type='behavior'),
        ]
    )

    enriched = enrich_experience(collection)

    assert all('stimulus' not in event.contextual_metadata for event in enriched.events)



def test_broken_continuity_is_not_labeled_continuous() -> None:
    collection = TemporalEventCollection(
        [
            _sample(0, 0.1, sequence_index=0),
            _marker(1, 'odor_onset'),
            _sample(1, 0.3, sequence_index=1),
            _sample(2, 0.7, sequence_index=2),
            _sample(5, 0.2, sequence_index=3),
            _marker(5, 'odor_offset'),
        ]
    )

    enriched = enrich_experience(collection)
    continuity_states = {
        event.contextual_metadata['experience']['continuity_state']
        for event in enriched.events
        if isinstance(event.contextual_metadata.get('experience'), dict)
        and isinstance(event.contextual_metadata['experience'].get('continuity_state'), str)
    }

    assert continuity_states
    assert 'continuous' not in continuity_states
    assert continuity_states <= {'interrupted', 'fragmented'}



def test_cross_event_relations_are_restrained_without_experience_evidence() -> None:
    collection = TemporalEventCollection(
        [
            _sample(0, 0.1, sequence_index=0),
            _sample(1, 0.2, sequence_index=1),
            _marker(2, 'verbal_report', marker_type='behavior'),
        ]
    )

    enriched = enrich_experience(collection)
    report_event = next(event for event in enriched.events if event.signal_type == 'marker')
    relations = report_event.contextual_metadata.get('relations', [])

    assert report_event.phase == 'report'
    assert 'experience' not in report_event.contextual_metadata
    assert all(relation['relation_type'] != 'describes' for relation in relations)
    assert all(relation.get('target_type') not in {'experience', 'window', 'continuity'} for relation in relations)



def test_noise_only_input_does_not_generate_meaningful_phase_claims() -> None:
    collection = TemporalEventCollection(
        [
            _sample(0, 0.1, sequence_index=0),
            _marker(1, 'odor_onset'),
            _sample(1, 0.4, sequence_index=1),
            _sample(2, 0.9, sequence_index=2),
            _sample(3, 0.6, sequence_index=3),
            _sample(4, 0.8, sequence_index=4),
            _marker(5, 'odor_offset'),
        ]
    )

    enriched = enrich_experience(collection)
    active_samples = [event for event in enriched.events if event.event_kind == 'sample' and event.extent.start >= _time(1)]
    active_phases = {event.phase for event in active_samples if event.phase is not None}
    unresolved_reasons = {
        event.contextual_metadata.get('unresolved', {}).get('temporal.phase')
        for event in active_samples
    }

    assert not (active_phases & {'rise', 'peak', 'sustain', 'decay', 'offset'})
    assert unresolved_reasons == {'non_monotonic_decay'}



def test_malformed_input_fails_safely_without_guessing() -> None:
    input_path = _test_file('broken.json')
    input_path.write_text('{"channels": [}', encoding='utf-8')

    with pytest.raises(AutoRoutingError, match='invalid JSON input'):
        build_auto_ingest_plan(input_path, 'generic')


