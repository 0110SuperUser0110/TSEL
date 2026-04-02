from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tsel.pipeline import TSELPipeline
from viewer.app import (
    available_sensory_type_labels,
    build_layer_summary,
    build_temporal_layer,
    describe_event_record,
    infer_acquisition_profile,
    preview_input_text,
    resolve_sensory_type,
    resolve_system_output_path,
)


ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / 'external_data' / 'curated'
TEST_OUTPUT_DIR = ROOT / 'output' / '_viewer_test'


def _reset_test_output_dir() -> Path:
    if TEST_OUTPUT_DIR.exists():
        shutil.rmtree(TEST_OUTPUT_DIR)
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_OUTPUT_DIR


def test_available_sensory_type_labels_expose_base_senses_only() -> None:
    labels = available_sensory_type_labels()

    assert labels == [
        'Vision / sight',
        'Hearing / audition',
        'Smell / olfaction',
        'Taste / gustation',
        'Touch / somatosensation',
    ]


def test_resolve_sensory_type_maps_selector_label_to_storage_key() -> None:
    option = resolve_sensory_type('Vision / sight')

    assert option.key == 'vision'
    assert option.label == 'Vision / sight'


def test_resolve_sensory_type_rejects_non_sensory_labels() -> None:
    with pytest.raises(ValueError, match='Select a sensory type'):
        resolve_sensory_type('')

    with pytest.raises(ValueError, match='explicit sensory classes'):
        resolve_sensory_type('generic')

    with pytest.raises(ValueError, match='explicit sensory classes'):
        resolve_sensory_type('dream')

    with pytest.raises(ValueError, match='explicit sensory classes'):
        resolve_sensory_type('eeg')


def test_infer_acquisition_profile_detects_eeg_measurement_route() -> None:
    profile = infer_acquisition_profile(ROOT / 'examples' / 'data' / 'eeg_direct.json')

    assert profile == 'eeg'


def test_infer_acquisition_profile_detects_olfaction_measurement_route() -> None:
    profile = infer_acquisition_profile(ROOT / 'examples' / 'data' / 'olfaction_trials.csv')

    assert profile == 'olfaction'


def test_infer_acquisition_profile_rejects_text_report_input() -> None:
    with pytest.raises(ValueError, match='not raw sensory data'):
        infer_acquisition_profile(EXTERNAL / 'dream_reports_sample.csv')


def test_preview_input_text_shows_json_source_structure() -> None:
    preview = preview_input_text(str(ROOT / 'examples' / 'data' / 'eeg_direct.json'))

    assert 'start_time' in preview
    assert 'Fp1' in preview
    assert 'odor_onset' in preview


def test_preview_input_text_shows_tabular_source_rows() -> None:
    preview = preview_input_text(str(ROOT / 'examples' / 'data' / 'olfaction_trials.csv'))

    assert 'elapsed_ms' in preview
    assert 'sensor-alpha' in preview
    assert 'trial_id' in preview


def test_describe_event_record_separates_envelope_temporal_and_context() -> None:
    pipeline = TSELPipeline()
    collection = pipeline.ingest(ROOT / 'examples' / 'data' / 'eeg_direct.json', ROOT / 'examples' / 'configs' / 'eeg_direct.json')
    record = collection.to_records()[0]

    envelope, temporal, context = describe_event_record(record)

    assert envelope == {
        'timestamp': '2026-03-15T15:30:00Z',
        'modality': 'eeg',
        'source': 'EEG-RAW-01',
        'signal_type': 'voltage',
        'value': 12.1,
        'unit': 'uV',
    }
    assert temporal['event_kind'] == 'sample'
    assert temporal['resolution_seconds'] == 0.25
    assert temporal['stream_id'] == 'eeg::EEG-RAW-01::Fp1::voltage'
    assert 'temporal' not in context
    assert context['channel'] == 'Fp1'
    assert context['sample_rate_hz'] == 4.0


def test_build_layer_summary_describes_sense_and_acquisition_separately() -> None:
    pipeline = TSELPipeline()
    input_path = ROOT / 'examples' / 'data' / 'eeg_direct.json'
    collection = pipeline.ingest_file(input_path, sensory_profile='eeg')
    sensory_type = resolve_sensory_type('Vision / sight')

    summary = build_layer_summary(str(input_path), collection, 'eeg', sensory_type)

    assert summary['adapter'] == 'timeseries_json'
    assert summary['acquisition_profile'] == 'eeg'
    assert summary['sensory_type'] == 'vision'
    assert summary['summary']['event_count'] == 10
    assert summary['phase_summary']['phases']
    assert summary['phase_summary']['experience_count'] == 1
    assert any('recording tools' in line.lower() for line in summary['explanation'])


def test_resolve_system_output_path_uses_sense_specific_directory() -> None:
    output_dir = _reset_test_output_dir()
    output_path = resolve_system_output_path(output_dir, 'vision')

    assert output_path == output_dir / 'vision' / 'current_temporal_layer.bundle.json'


def test_build_temporal_layer_stores_by_selected_sense_and_infers_eeg() -> None:
    input_path = ROOT / 'examples' / 'data' / 'eeg_direct.json'
    output_dir = _reset_test_output_dir()
    output_path = resolve_system_output_path(output_dir, 'vision')

    result = build_temporal_layer(str(input_path), 'Vision / sight', output_path=output_path)

    written_payload = json.loads(output_path.read_text(encoding='utf-8'))
    first_event = written_payload['events'][0]
    assert result.sensory_type == 'vision'
    assert result.sensory_type_label == 'Vision / sight'
    assert result.acquisition_profile == 'eeg'
    assert result.adapter == 'timeseries_json'
    assert result.output_path == str(output_path.resolve())
    assert written_payload['event_count'] == 10
    assert written_payload['summary']['stream_count'] == 3
    assert written_payload['summary']['phases']
    assert written_payload['summary']['experience_count'] == 1
    assert written_payload['summary']['primary_senses'] == ['vision']
    assert 'eeg' in written_payload['summary']['acquisition_profiles']
    assert first_event['contextual_metadata']['sensory_class'] == 'vision'
    assert first_event['contextual_metadata']['sensory']['primary_sense'] == 'vision'
    assert first_event['contextual_metadata']['acquisition_profile'] == 'eeg'
    assert first_event['contextual_metadata']['acquisition']['acquisition_profile'] == 'eeg'
    assert first_event['contextual_metadata']['temporal']['event_kind'] == 'sample'


def test_build_temporal_layer_rejects_text_report_input_in_gui_flow() -> None:
    output_dir = _reset_test_output_dir()
    output_path = resolve_system_output_path(output_dir, 'vision')

    with pytest.raises(ValueError, match='not raw sensory data'):
        build_temporal_layer(str(EXTERNAL / 'dream_reports_sample.csv'), 'Vision / sight', output_path=output_path)


def test_build_temporal_layer_rejects_wrong_sense_for_olfactory_data() -> None:
    output_dir = _reset_test_output_dir()
    output_path = resolve_system_output_path(output_dir, 'vision')

    with pytest.raises(ValueError, match='identified as olfactory data'):
        build_temporal_layer(str(ROOT / 'examples' / 'data' / 'olfaction_trials.csv'), 'Vision / sight', output_path=output_path)


@pytest.mark.parametrize(
    ('input_name', 'selector_label', 'expected_sense', 'expected_profile'),
    [
        ('vision_episode.json', 'Vision / sight', 'vision', 'multisensory'),
        ('audition_episode.json', 'Hearing / audition', 'audition', 'multisensory'),
        ('olfaction_episode.json', 'Smell / olfaction', 'olfaction', 'olfaction'),
        ('gustation_episode.json', 'Taste / gustation', 'gustation', 'multisensory'),
        ('somatosensation_episode.json', 'Touch / somatosensation', 'somatosensation', 'multisensory'),
    ],
)
def test_build_temporal_layer_supports_all_five_senses(
    input_name: str,
    selector_label: str,
    expected_sense: str,
    expected_profile: str,
) -> None:
    input_path = ROOT / 'examples' / 'data' / input_name
    output_dir = _reset_test_output_dir()
    output_path = resolve_system_output_path(output_dir, expected_sense)

    result = build_temporal_layer(str(input_path), selector_label, output_path=output_path)

    written_payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert result.sensory_type == expected_sense
    assert result.acquisition_profile == expected_profile
    assert written_payload['summary']['primary_senses'] == [expected_sense]
    assert 'onset' in written_payload['summary']['phases']
    assert 'peak' in written_payload['summary']['phases']
    assert written_payload['summary']['experience_count'] == 1
    assert written_payload['summary']['relation_count'] > 0


def test_build_temporal_layer_accepts_sequence_only_multisensory_table() -> None:
    output_dir = _reset_test_output_dir()
    input_path = output_dir / 'sequence_multisensory.csv'
    input_path.write_text(
        "source,subject_id,sample_rate_hz,vision_signal,auditory_signal\n"
        + "SESSION-02,SUB-09,4,0.1,0.2\n"
        + "SESSION-02,SUB-09,4,0.3,0.4\n",
        encoding='utf-8',
    )
    output_path = resolve_system_output_path(output_dir, 'vision')

    result = build_temporal_layer(str(input_path), 'Vision / sight', output_path=output_path)
    written_payload = json.loads(output_path.read_text(encoding='utf-8'))
    first_event = written_payload['events'][0]

    assert result.acquisition_profile == 'multisensory'
    assert written_payload['event_count'] == 4
    assert written_payload['summary']['primary_senses'] == ['vision']
    assert first_event['timestamp'] == '1970-01-01T00:00:00Z'
    assert first_event['contextual_metadata']['completeness']['missing_dimensions'] == ['absolute_time']
    assert first_event['contextual_metadata']['temporal']['resolution_seconds'] == 0.25


def test_preview_input_text_lists_packet_directory_members() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = output_dir / 'packet_preview'
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / 'vision_episode.json').write_text((ROOT / 'examples' / 'data' / 'vision_episode.json').read_text(encoding='utf-8'), encoding='utf-8')
    (packet_dir / 'vision_sequence.csv').write_text(
        "source,subject_id,sample_rate_hz,vision_signal,auditory_signal\n"
        + "SESSION-02,SUB-09,4,0.1,0.2\n"
        + "SESSION-02,SUB-09,4,0.3,0.4\n",
        encoding='utf-8',
    )

    preview = preview_input_text(str(packet_dir))

    assert '"format": "packet"' in preview
    assert 'vision_episode.json' in preview
    assert 'vision_sequence.csv' in preview


def test_build_temporal_layer_accepts_packet_directory() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = output_dir / 'vision_packet'
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / 'vision_episode.json').write_text((ROOT / 'examples' / 'data' / 'vision_episode.json').read_text(encoding='utf-8'), encoding='utf-8')
    (packet_dir / 'vision_sequence.csv').write_text(
        "source,subject_id,sample_rate_hz,vision_signal,auditory_signal\n"
        + "SESSION-02,SUB-09,4,0.1,0.2\n"
        + "SESSION-02,SUB-09,4,0.3,0.4\n",
        encoding='utf-8',
    )
    output_path = resolve_system_output_path(output_dir, 'vision')

    result = build_temporal_layer(str(packet_dir), 'Vision / sight', output_path=output_path)
    written_payload = json.loads(output_path.read_text(encoding='utf-8'))

    assert result.acquisition_profile == 'packet'
    assert result.adapter == 'packet'
    assert result.summary['input_kind'] == 'packet'
    assert result.summary['input_count'] == 2
    assert result.summary['planned_profiles'] == ['multisensory']
    assert written_payload['build']['input_count'] == 2
    assert written_payload['event_count'] > 4
    assert written_payload['summary']['primary_senses'] == ['vision']
