from __future__ import annotations

import json
import shutil
from pathlib import Path

from tsel.packet_profiles import detect_special_packet_type, plan_special_packet
from tsel.pipeline import TSELPipeline
from viewer.app import build_temporal_layer, preview_input_text, resolve_system_output_path


ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUT_DIR = ROOT / 'output' / '_packet_profile_test'


def _reset_test_output_dir() -> Path:
    if TEST_OUTPUT_DIR.exists():
        shutil.rmtree(TEST_OUTPUT_DIR)
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_OUTPUT_DIR


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')


def _create_synapse_packet(root: Path) -> Path:
    packet_dir = root / 'synapse_packet'
    packet_dir.mkdir(parents=True, exist_ok=True)

    _write(
        packet_dir / 'TrainSet.txt',
        'Compound Identifier\tOdor\tReplicate\tIntensity\tDilution\tsubject #\tINTENSITY/STRENGTH\tSWEET\n'
        '101\todor-a\tlow\tlow\t1/10\t1\t10\t5\n'
        '102\todor-b\thigh\thigh\t1/100\t2\t20\t7\n',
    )
    _write(
        packet_dir / 'leaderboard_set.txt',
        '#oID\tindividual\tdescriptor\tvalue\n'
        '101\t1\tINTENSITY/STRENGTH\t22\n'
        '102\t1\tSWEET\t5\n',
    )
    _write(
        packet_dir / 'LBs1.txt',
        '#oID\tindividual\tdescriptor\tvalue\n'
        '101\t2\tINTENSITY/STRENGTH\t73\n'
        '102\t2\tSWEET\t9\n',
    )
    _write(
        packet_dir / 'LBs2.txt',
        '#oID\tdescriptor\tvalue\tsigma\n'
        '101\tINTENSITY/STRENGTH\t16.5\t2.1\n'
        '102\tSWEET\t8.5\t1.3\n',
    )
    _write(
        packet_dir / 'molecular_descriptors_data.txt',
        'CID\tcomplexity\tCID\tMW\n'
        '101\t1.5\t0\t58.1\n'
        '102\t2.5\t0\t72.2\n',
    )
    _write(packet_dir / 'CID_leaderboard.txt', '101\n')
    _write(packet_dir / 'CID_testset.txt', '102\n')
    _write(packet_dir / 'dilution_leaderboard.txt', 'oID\tdilution\n101\t1/10\n')
    _write(packet_dir / 'dilution_testset.txt', 'oID\tdilution\n102\t1/100\n')
    (packet_dir / 'train_set.mat').write_bytes(b'MATLAB 5.0 MAT-file')
    return packet_dir


def test_detect_special_packet_type_identifies_synapse_packet() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = _create_synapse_packet(output_dir)

    assert detect_special_packet_type(packet_dir) == 'dream_synapse'


def test_preview_input_text_describes_special_packet() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = _create_synapse_packet(output_dir)

    preview = preview_input_text(str(packet_dir))

    assert '"packet_type": "dream_synapse"' in preview
    assert 'molecular_descriptors_data.txt' in preview
    assert 'train_set.mat' in preview


def test_plan_special_packet_creates_compact_synapse_jsonl_plans() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = _create_synapse_packet(output_dir)

    plans = plan_special_packet(packet_dir, 'olfaction')

    assert plans is not None
    assert len(plans) == 6
    assert all(plan.adapter == 'json' for plan in plans)
    assert all(plan.sensory_profile == 'olfaction' for plan in plans)
    assert all(plan.input_path.exists() for plan in plans)


def test_pipeline_ingest_auto_accepts_raw_synapse_packet() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = _create_synapse_packet(output_dir)

    collection = TSELPipeline().ingest_auto(packet_dir, 'olfaction')
    records = collection.to_records()

    assert len(records) == 12
    assert any(record['signal_type'] == 'perception_profile' and isinstance(record['value'], dict) for record in records)
    assert any(record['modality'] == 'molecular_descriptor' and isinstance(record['value'], dict) for record in records)
    assert any(record['modality'] == 'olfaction_challenge_split' and record['unit'] == 'label' for record in records)


def test_build_temporal_layer_accepts_raw_synapse_packet_directory() -> None:
    output_dir = _reset_test_output_dir()
    packet_dir = _create_synapse_packet(output_dir)
    output_path = resolve_system_output_path(output_dir, 'olfaction')

    result = build_temporal_layer(str(packet_dir), 'Smell / olfaction', output_path=output_path)
    written_payload = json.loads(output_path.read_text(encoding='utf-8'))

    assert result.acquisition_profile == 'packet'
    assert result.adapter == 'packet'
    assert result.summary['input_kind'] == 'packet'
    assert result.summary['planned_profiles'] == ['olfaction']
    assert written_payload['event_count'] == 12
    assert any(event['signal_type'] == 'perception_profile' and isinstance(event['value'], dict) for event in written_payload['events'])
    assert any(event['modality'] == 'molecular_descriptor' and isinstance(event['value'], dict) for event in written_payload['events'])
