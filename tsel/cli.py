from __future__ import annotations

import argparse
import json

from .pipeline import TSELPipeline
from .serializers import load_events, write_events, write_segments, write_validation_report
from .standards import evaluate_conformance, vocabulary_snapshot, write_standard_assets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Temporal Sensory Encoding Layer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest one dataset using one adapter config")
    ingest_parser.add_argument("input", help="Path to the input dataset")
    ingest_parser.add_argument("config", help="Path to the adapter config JSON")
    ingest_parser.add_argument("output", help="Path to the output JSON, bundle, or JSONL file")
    ingest_parser.add_argument("--format", choices=("json", "jsonl", "bundle"), default="jsonl")
    ingest_parser.add_argument("--profile", help="Optional sensory profile switch overriding config inference")

    auto_ingest_parser = subparsers.add_parser("auto-ingest", help="Ingest one raw dataset using only a sensory profile switch")
    auto_ingest_parser.add_argument("input", help="Path to the raw input dataset")
    auto_ingest_parser.add_argument("profile", help="Sensory profile to apply to the raw input")
    auto_ingest_parser.add_argument("output", help="Path to the output JSON, bundle, or JSONL file")
    auto_ingest_parser.add_argument("--format", choices=("json", "jsonl", "bundle"), default="jsonl")

    batch_parser = subparsers.add_parser("batch", help="Ingest multiple datasets from a manifest")
    batch_parser.add_argument("manifest", help="Path to a JSON manifest")
    batch_parser.add_argument("output", help="Path to the output JSON, bundle, or JSONL file")
    batch_parser.add_argument("--format", choices=("json", "jsonl", "bundle"), default="jsonl")

    summarize_parser = subparsers.add_parser("summarize", help="Summarize a normalized TSEL file or a raw source with config")
    summarize_parser.add_argument("input", help="Path to a normalized TSEL JSON/JSONL/bundle file or a raw source file")
    summarize_parser.add_argument("--config", help="Optional adapter config for raw source ingestion")
    summarize_parser.add_argument("--profile", help="Optional sensory profile switch overriding config inference")
    summarize_parser.add_argument("--json", action="store_true", dest="as_json", help="Print summary as JSON")

    validate_parser = subparsers.add_parser("validate", help="Validate a normalized TSEL file or a raw source with config")
    validate_parser.add_argument("input", help="Path to a normalized TSEL JSON/JSONL/bundle file or a raw source file")
    validate_parser.add_argument("--config", help="Optional adapter config for raw source ingestion")
    validate_parser.add_argument("--profile", help="Optional sensory profile switch overriding config inference")
    validate_parser.add_argument("--output", help="Optional path to write the validation report as JSON")
    validate_parser.add_argument("--json", action="store_true", dest="as_json", help="Print validation report as JSON")
    validate_parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code on validation errors")

    conformance_parser = subparsers.add_parser("conformance", help="Check normalized events against the TSEL standard")
    conformance_parser.add_argument("input", help="Path to a normalized TSEL JSON/JSONL/bundle file or a raw source file")
    conformance_parser.add_argument("--config", help="Optional adapter config for raw source ingestion")
    conformance_parser.add_argument("--profile", help="Optional sensory profile switch overriding config inference")
    conformance_parser.add_argument("--json", action="store_true", dest="as_json", help="Print conformance report as JSON")
    conformance_parser.add_argument("--strict", action="store_true", help="Return a non-zero exit code on conformance errors")

    standard_parser = subparsers.add_parser("standard", help="Describe or export the current TSEL standard assets")
    standard_parser.add_argument("--json", action="store_true", dest="as_json", help="Print the standard vocabulary snapshot as JSON")
    standard_parser.add_argument("--output-dir", help="Optional directory to write schema and vocabulary assets")

    segment_parser = subparsers.add_parser("segment", help="Create marker-centered temporal segments from a normalized TSEL file or raw source")
    segment_parser.add_argument("input", help="Path to a normalized TSEL JSON/JSONL/bundle file or a raw source file")
    segment_parser.add_argument("output", help="Path to the output JSON file containing temporal segments")
    segment_parser.add_argument("--config", help="Optional adapter config for raw source ingestion")
    segment_parser.add_argument("--profile", help="Optional sensory profile switch overriding config inference")
    segment_parser.add_argument("--marker-signal", action="append", required=True, help="Signal type to use as a segmentation anchor; repeatable")
    segment_parser.add_argument("--pre-seconds", type=float, default=0.0, help="Seconds to include before each marker")
    segment_parser.add_argument("--post-seconds", type=float, default=0.0, help="Seconds to include after each marker")
    segment_parser.add_argument("--limit", type=int, help="Optional maximum number of segments to emit")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pipeline = TSELPipeline()

    if args.command == "ingest":
        collection = pipeline.ingest(args.input, args.config, sensory_profile=args.profile)
        write_events(args.output, collection, fmt=args.format)
        _print_summary(collection.summary(), output_path=args.output)
        return 0

    if args.command == "auto-ingest":
        collection = pipeline.ingest_auto(args.input, args.profile)
        write_events(args.output, collection, fmt=args.format)
        _print_summary(collection.summary(), output_path=args.output)
        return 0

    if args.command == "batch":
        jobs = pipeline.load_manifest(args.manifest)
        collection = pipeline.ingest_many(jobs)
        write_events(args.output, collection, fmt=args.format)
        _print_summary(collection.summary(), output_path=args.output)
        return 0

    if args.command == "standard":
        snapshot = vocabulary_snapshot()
        if args.output_dir:
            paths = write_standard_assets(args.output_dir)
            if args.as_json:
                print(json.dumps({"snapshot": snapshot, "written": [str(path) for path in paths]}, indent=2))
            else:
                print(f"TSEL standard {snapshot['spec_version']}")
                for path in paths:
                    print(path)
            return 0
        if args.as_json:
            print(json.dumps(snapshot, indent=2))
        else:
            print(f"TSEL standard {snapshot['spec_version']}")
            print(f"Modalities: {', '.join(snapshot['modalities'])}")
            print(f"Event kinds: {', '.join(snapshot['event_kinds'])}")
            print(f"Signal types: {', '.join(snapshot['signal_types'])}")
            print(f"Time scales: {', '.join(snapshot['time_scales'])}")
            print(f"Units: {', '.join(snapshot['units'])}")
            print(f"Sensory profiles: {', '.join(snapshot['sensory_profiles'].keys())}")
        return 0

    collection = _load_collection(pipeline, args.input, getattr(args, "config", None), getattr(args, "profile", None))

    if args.command == "summarize":
        summary = collection.summary()
        if args.as_json:
            print(json.dumps(summary, indent=2))
        else:
            _print_summary(summary)
        return 0

    if args.command == "validate":
        report = collection.validate()
        if args.output:
            write_validation_report(args.output, report)
        if args.as_json:
            print(json.dumps(report.to_record(), indent=2))
        else:
            _print_validation(report, output_path=args.output)
        if args.strict and not report.is_valid:
            return 1
        return 0

    if args.command == "conformance":
        temporal_report = collection.validate()
        report = evaluate_conformance(collection.to_records(), temporal_validation=temporal_report)
        if args.as_json:
            print(json.dumps(report.to_record(), indent=2))
        else:
            _print_conformance(report)
        if args.strict and not report.is_conformant:
            return 1
        return 0

    segments = collection.segment_around_markers(
        marker_signal_types=args.marker_signal,
        pre_seconds=args.pre_seconds,
        post_seconds=args.post_seconds,
        limit=args.limit,
    )
    write_segments(args.output, segments)
    print(f"Wrote {len(segments)} temporal segments to {args.output}")
    return 0


def _load_collection(pipeline: TSELPipeline, input_path: str, config_path: str | None, profile: str | None):
    if config_path:
        return pipeline.ingest(input_path, config_path, sensory_profile=profile)
    return pipeline.ingest_file(input_path, sensory_profile=profile)


def _print_summary(summary: dict[str, object], *, output_path: str | None = None) -> None:
    destination = f" to {output_path}" if output_path else ""
    print(f"Events: {summary['event_count']}{destination}")
    print(f"Modalities: {', '.join(summary['modalities'])}")
    print(f"Sources: {', '.join(summary['sources'])}")
    print(f"Event kinds: {', '.join(summary['event_kinds'])}")
    if summary.get('time_scales'):
        print(f"Time scales: {', '.join(summary['time_scales'])}")
    print(f"Streams: {summary['stream_count']}")
    print(f"Time range: {summary['time_start']} -> {summary['time_end']}")


def _print_validation(report, *, output_path: str | None = None) -> None:
    record = report.to_record()
    destination = f" and wrote report to {output_path}" if output_path else ""
    print(f"Validation: {'valid' if record['is_valid'] else 'invalid'}{destination}")
    print(f"Errors: {record['error_count']}")
    print(f"Warnings: {record['warning_count']}")
    print(f"Streams: {record['stream_count']}")
    print(f"Sync groups: {record.get('sync_group_count', 0)}")
    if record['issues']:
        first_issue = record['issues'][0]
        print(f"First issue: {first_issue['severity']} {first_issue['code']} - {first_issue['message']}")


def _print_conformance(report) -> None:
    record = report.to_record()
    print(f"Conformance: {'conformant' if record['is_conformant'] else 'non-conformant'}")
    print(f"Spec version: {record['spec_version']}")
    print(f"Errors: {record['error_count']}")
    print(f"Warnings: {record['warning_count']}")
    if record['issues']:
        first_issue = record['issues'][0]
        print(f"First issue: {first_issue['severity']} {first_issue['code']} - {first_issue['message']}")


if __name__ == "__main__":
    raise SystemExit(main())