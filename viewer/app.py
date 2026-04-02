from __future__ import annotations

import csv
import json
import re
import traceback
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from tsel.autorouting import AutoIngestPlan, AutoRoutingError, infer_acquisition_profile as infer_deterministic_acquisition_profile, looks_like_normalized_tsel
from tsel.packet_profiles import describe_special_packet, plan_special_packet
from tsel.models import TemporalEventCollection
from tsel.pipeline import TSELPipeline


RAW_PREVIEW_ROWS = 12
RAW_PREVIEW_CHARS = 6000
OUTPUT_PREVIEW_CHARS = 160000
DEFAULT_OUTPUT_NAME = "current_temporal_layer.bundle.json"
ROOT_DIR = Path(__file__).resolve().parents[1]
ERROR_LOG_PATH = ROOT_DIR / "output" / "viewer_error.log"
_TABLE_SUFFIXES = {".csv", ".tsv", ".txt"}
_JSON_SUFFIXES = {".json", ".jsonl"}
_RAW_PACKET_SUFFIXES = _TABLE_SUFFIXES | _JSON_SUFFIXES | {".edf"}
_TEXT_HINTS = {"dream_text", "report_text", "text", "narrative", "transcript", "question", "survey_name"}
_OLFACTION_HINTS = {"odor", "odour", "olfaction", "olfactory", "compound", "cid", "dilution", "gas", "smell"}
_ENVIRONMENT_HINTS = {"temperature", "humidity", "station", "weather", "measurement", "reading", "apparatus", "rig"}
_EEG_HINT_PATTERN = re.compile(
    r"^(fp[0-9z]+|af[0-9z]+|f[0-9z]+|fc[0-9z]+|c[0-9z]+|cp[0-9z]+|p[0-9z]+|po[0-9z]+|o[0-9z]+|t[0-9z]+|tp[0-9z]+|ft[0-9z]+|cz|pz|fz|oz)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SensoryTypeOption:
    key: str
    label: str
    description: str


@dataclass(slots=True)
class TemporalLayerBuildResult:
    collection: TemporalEventCollection
    input_path: str
    sensory_type: str
    sensory_type_label: str
    acquisition_profile: str
    adapter: str
    output_path: str
    raw_preview: str
    output_payload: dict[str, object]
    summary: dict[str, object]

    @property
    def output_text(self) -> str:
        return render_output_text(self.output_payload)


SENSORY_TYPE_OPTIONS = (
    SensoryTypeOption(
        key="vision",
        label="Vision / sight",
        description="Visual sensory inputs and experiments stored under the vision layer.",
    ),
    SensoryTypeOption(
        key="audition",
        label="Hearing / audition",
        description="Auditory sensory inputs and experiments stored under the audition layer.",
    ),
    SensoryTypeOption(
        key="olfaction",
        label="Smell / olfaction",
        description="Olfactory sensory inputs and experiments stored under the olfaction layer.",
    ),
    SensoryTypeOption(
        key="gustation",
        label="Taste / gustation",
        description="Gustatory sensory inputs and experiments stored under the gustation layer.",
    ),
    SensoryTypeOption(
        key="somatosensation",
        label="Touch / somatosensation",
        description="Somatosensory inputs and experiments stored under the touch layer.",
    ),
)

SENSORY_TYPE_BY_KEY = {option.key: option for option in SENSORY_TYPE_OPTIONS}
SENSORY_TYPE_BY_LABEL = {option.label.lower(): option for option in SENSORY_TYPE_OPTIONS}


def available_sensory_type_labels() -> list[str]:
    return [option.label for option in SENSORY_TYPE_OPTIONS]


def resolve_sensory_type(value: str | None) -> SensoryTypeOption:
    if value is None or not value.strip():
        raise ValueError("Select a sensory type before building the temporal layer.")
    stripped = value.strip()
    by_label = SENSORY_TYPE_BY_LABEL.get(stripped.lower())
    if by_label is not None:
        return by_label
    by_key = SENSORY_TYPE_BY_KEY.get(stripped.lower())
    if by_key is not None:
        return by_key
    raise ValueError(
        f"unsupported sensory type: {value}. Select one of the explicit sensory classes shown in the GUI."
    )


def resolve_system_output_path(output_dir: str | Path | None = None, sensory_type_key: str | None = None) -> Path:
    base_dir = ROOT_DIR / "output" if output_dir is None else Path(output_dir)
    if sensory_type_key:
        base_dir = base_dir / sensory_type_key
    return base_dir / DEFAULT_OUTPUT_NAME


def _canonical_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _relative_member_label(root: Path, member: Path) -> str:
    try:
        return str(member.relative_to(root))
    except ValueError:
        return member.name


def _collect_input_tokens(input_path: str | Path) -> set[str]:
    path = Path(input_path)
    if path.is_dir():
        raise ValueError("packet inputs are classified per file")

    tokens = {_canonical_token(path.stem)}
    suffix = path.suffix.lower()

    if suffix in _TABLE_SUFFIXES:
        with path.open("r", encoding="utf-8", newline="") as handle:
            first_line = handle.readline()
            handle.seek(0)
            delimiter = "	" if "	" in first_line and suffix in {".tsv", ".txt"} else ","
            reader = csv.DictReader(handle, delimiter=delimiter)
            for fieldname in reader.fieldnames or []:
                tokens.add(_canonical_token(fieldname))
        return tokens

    if suffix in _JSON_SUFFIXES:
        raw_text = path.read_text(encoding="utf-8").strip()
        if not raw_text:
            return tokens
        payload = [json.loads(line) for line in raw_text.splitlines() if line.strip()] if suffix == ".jsonl" else json.loads(raw_text)
        if isinstance(payload, dict):
            for key in payload.keys():
                tokens.add(_canonical_token(str(key)))
            channels = payload.get("channels")
            if isinstance(channels, dict):
                for key in channels.keys():
                    tokens.add(_canonical_token(str(key)))
            records = payload.get("records")
            if isinstance(records, list) and records and isinstance(records[0], dict):
                for key in records[0].keys():
                    tokens.add(_canonical_token(str(key)))
        elif isinstance(payload, list) and payload and isinstance(payload[0], dict):
            for key in payload[0].keys():
                tokens.add(_canonical_token(str(key)))
        return tokens

    return tokens


def _has_text_hints(tokens: set[str]) -> bool:
    return any(token in _TEXT_HINTS for token in tokens)


def _has_olfaction_hints(tokens: set[str]) -> bool:
    return any(any(hint in token for hint in _OLFACTION_HINTS) for token in tokens)


def _has_environment_hints(tokens: set[str]) -> bool:
    for token in tokens:
        for hint in _ENVIRONMENT_HINTS:
            if token == hint or token.startswith(f"{hint}_") or token.endswith(f"_{hint}"):
                return True
    return False


def _has_eeg_hints(input_path: str | Path, tokens: set[str]) -> bool:
    path = Path(input_path)
    if path.suffix.lower() == ".edf":
        return True
    if any("eeg" in token for token in tokens):
        return True
    if "sample_rate_hz" in tokens or "sampling_rate_hz" in tokens or "channels" in tokens:
        if any(_EEG_HINT_PATTERN.match(token) for token in tokens):
            return True
    return any(_EEG_HINT_PATTERN.match(token) for token in tokens)


def infer_acquisition_profile(input_path: str | Path) -> str:
    path = Path(input_path)
    if path.is_dir():
        raise ValueError("Input packets are classified per file during the build step.")
    if looks_like_normalized_tsel(path):
        raise ValueError("The viewer expects raw sensory input, not an existing TSEL temporal-layer file.")

    try:
        profile = infer_deterministic_acquisition_profile(path)
    except AutoRoutingError as exc:
        message = str(exc)
        if "dream" in message or "text-report" in message or "text report" in message:
            raise ValueError("This input looks like a text report or narrative record, not raw sensory data.") from exc
        if "environment" in message:
            raise ValueError("This input looks like environment or apparatus data, not one of the base sensory classes in the GUI.") from exc
        raise ValueError(message) from exc

    if profile == "dream":
        raise ValueError("This input looks like a text report or narrative record, not raw sensory data.")
    if profile == "environment":
        raise ValueError("This input looks like environment or apparatus data, not one of the base sensory classes in the GUI.")
    return profile

def preview_input_text(input_path: str, *, max_rows: int = RAW_PREVIEW_ROWS, max_chars: int = RAW_PREVIEW_CHARS) -> str:
    path = Path(input_path)
    if not path.exists():
        return f"Input path not found: {input_path}"

    if path.is_dir():
        special_packet = describe_special_packet(path)
        if special_packet is not None:
            return json.dumps(special_packet, indent=2)[:max_chars]
        pipeline = TSELPipeline()
        try:
            members = pipeline.discover_auto_inputs(path)
        except Exception as exc:  # noqa: BLE001
            return f"Unable to inspect packet: {exc}"
        preview_files = []
        for member in members[:max_rows]:
            status = "accepted"
            profile = None
            try:
                profile = infer_acquisition_profile(member)
            except Exception as exc:  # noqa: BLE001
                status = str(exc)
            preview_files.append(
                {
                    "path": _relative_member_label(path, member),
                    "profile": profile,
                    "status": status,
                    "size_bytes": member.stat().st_size,
                }
            )
        return json.dumps(
            {
                "format": "packet",
                "root": str(path.resolve()),
                "file_count": len(members),
                "preview_files": preview_files,
            },
            indent=2,
        )[:max_chars]

    suffix = path.suffix.lower()
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".json", ".jsonl"}:
        if suffix == ".jsonl":
            rows = [json.loads(line) for line in raw_text.splitlines() if line.strip()][:max_rows]
            return json.dumps({"format": "jsonl", "preview_rows": rows}, indent=2)[:max_chars]
        payload = json.loads(raw_text)
        if isinstance(payload, list):
            payload = payload[:max_rows]
        return json.dumps(payload, indent=2)[:max_chars]

    if suffix in _TABLE_SUFFIXES:
        lines = raw_text.splitlines()
        if not lines:
            return ""
        delimiter = "	" if "	" in lines[0] else ","
        reader = csv.DictReader(lines, delimiter=delimiter)
        rows = []
        for index, row in enumerate(reader, start=1):
            rows.append({"row": index, "values": row})
            if index >= max_rows:
                break
        return json.dumps({"format": "table", "delimiter": delimiter, "preview_rows": rows}, indent=2)[:max_chars]

    return raw_text[:max_chars]


def describe_event_record(record: dict[str, object]) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    contextual_metadata = dict(record.get("contextual_metadata", {}))
    temporal = dict(contextual_metadata.pop("temporal", {}))
    envelope = {
        "timestamp": record.get("timestamp"),
        "modality": record.get("modality"),
        "source": record.get("source"),
        "signal_type": record.get("signal_type"),
        "value": record.get("value"),
        "unit": record.get("unit"),
    }
    return envelope, temporal, contextual_metadata


def build_layer_summary(
    input_path: str,
    collection: TemporalEventCollection,
    acquisition_profile: str,
    sensory_type: SensoryTypeOption | None = None,
    *,
    plans: list[AutoIngestPlan] | None = None,
    rejected_inputs: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    pipeline = TSELPipeline()
    path = Path(input_path)
    rejected = [] if rejected_inputs is None else rejected_inputs

    if path.is_file() and looks_like_normalized_tsel(path):
        adapter = "normalized_tsel"
        adapters = [adapter]
        planned_profiles = [acquisition_profile]
        input_count = 1
    elif plans is not None:
        adapters = sorted({plan.adapter for plan in plans})
        planned_profiles = sorted({plan.sensory_profile for plan in plans})
        input_count = len(plans)
        adapter = adapters[0] if input_count == 1 and len(adapters) == 1 else "packet"
    else:
        plan = pipeline.plan_auto_ingest(input_path, acquisition_profile)
        adapter = plan.adapter
        adapters = [plan.adapter]
        planned_profiles = [plan.sensory_profile]
        input_count = 1

    records = collection.to_records()
    first_event = None
    if records:
        envelope, temporal, context = describe_event_record(records[0])
        first_event = {
            "envelope": envelope,
            "temporal_fields": temporal,
            "context_without_temporal": context,
        }

    input_kind = "packet" if path.is_dir() or input_count > 1 else "file"
    summary = collection.summary()
    return {
        "input": str(path.resolve()),
        "input_kind": input_kind,
        "input_count": input_count,
        "planned_profiles": planned_profiles,
        "adapters": adapters,
        "rejected_inputs": rejected,
        "rejected_input_count": len(rejected),
        "sensory_type": None if sensory_type is None else sensory_type.key,
        "sensory_type_label": None if sensory_type is None else sensory_type.label,
        "acquisition_profile": acquisition_profile,
        "adapter": adapter,
        "summary": summary,
        "phase_summary": {
            "phases": summary.get("phases", []),
            "experience_count": summary.get("experience_count", 0),
            "continuity_count": summary.get("continuity_count", 0),
        },
        "first_event_preview": first_event,
        "explanation": [
            "TSEL performs one operation: it converts raw sensory data into the unified temporal layer.",
            "The selector exposes base sensory classes, not data types or recording tools.",
            "EEG is treated as an internal acquisition route when the raw file indicates neural measurement.",
            "The selected sensory class determines storage and system routing, while the acquisition profile describes how the raw input was read.",
            "Directories are treated as raw data packets and are unified into one temporal bundle when they contain compatible sensory files.",
            "The temporal code preserves continuous experience through derived phases such as baseline, onset, rise, peak, decay, offset, and aftereffect when the data supports them.",
        ],
    }


def render_output_text(payload: dict[str, object], *, max_chars: int = OUTPUT_PREVIEW_CHARS) -> str:
    text = json.dumps(payload, indent=2)
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return (
        text[:max_chars].rstrip()
        + f"\n\n... output truncated in the viewer ({omitted} characters omitted). The full unified temporal code is stored on disk."
    )


def _resolve_event_acquisition_profile(event, fallback: str) -> str:
    acquisition = event.contextual_metadata.get("acquisition")
    if isinstance(acquisition, dict):
        raw_profile = acquisition.get("acquisition_profile")
        if isinstance(raw_profile, str) and raw_profile.strip():
            return raw_profile.strip()
    for key in ("acquisition_profile", "sensory_profile"):
        raw_profile = event.contextual_metadata.get(key)
        if isinstance(raw_profile, str) and raw_profile.strip():
            return raw_profile.strip()
    return fallback


def _annotate_collection(
    collection: TemporalEventCollection,
    sensory_type: SensoryTypeOption,
    acquisition_profile: str,
) -> None:
    for event in collection.events:
        event_profile = _resolve_event_acquisition_profile(event, acquisition_profile)
        event.contextual_metadata["sensory_class"] = sensory_type.key
        event.contextual_metadata["sensory_label"] = sensory_type.label
        event.contextual_metadata["acquisition_profile"] = event_profile
        sensory = event.contextual_metadata.get("sensory")
        sensory_context = dict(sensory) if isinstance(sensory, dict) else {}
        sensory_context["primary_sense"] = sensory_type.key
        event.contextual_metadata["sensory"] = sensory_context
        acquisition = event.contextual_metadata.get("acquisition")
        acquisition_context = dict(acquisition) if isinstance(acquisition, dict) else {}
        acquisition_context["acquisition_profile"] = event_profile
        acquisition_context.setdefault("transform_stage", "normalized")
        event.contextual_metadata["acquisition"] = acquisition_context


def _prepare_input_plans(
    input_path: str | Path,
    sensory_type: SensoryTypeOption,
) -> tuple[list[AutoIngestPlan], list[dict[str, str]]]:
    path = Path(input_path)
    pipeline = TSELPipeline()
    special_plans = plan_special_packet(path, sensory_type.key)
    if special_plans is not None:
        return special_plans, []
    members = pipeline.discover_auto_inputs(path)
    plans: list[AutoIngestPlan] = []
    rejected_inputs: list[dict[str, str]] = []

    for member in members:
        try:
            acquisition_profile = infer_acquisition_profile(member)
            if acquisition_profile == "olfaction" and sensory_type.key != "olfaction":
                raise ValueError("This raw input was identified as olfactory data. Select Smell / olfaction.")
            plans.append(pipeline.plan_auto_ingest(member, acquisition_profile))
        except Exception as exc:  # noqa: BLE001
            if path.is_file():
                raise
            rejected_inputs.append(
                {
                    "input": _relative_member_label(path, member),
                    "reason": str(exc),
                }
            )

    if plans:
        return plans, rejected_inputs
    if rejected_inputs:
        details = "\n".join(f"{item['input']}: {item['reason']}" for item in rejected_inputs[:5])
        raise ValueError(f"No raw sensory files in the selected packet could be unified.\n{details}")
    raise ValueError(f"No supported raw sensory files were found in {path}")


def _build_bundle_payload(
    collection: TemporalEventCollection,
    *,
    summary: dict[str, object],
) -> dict[str, object]:
    payload = collection.to_bundle()
    payload["build"] = {
        "input": summary.get("input"),
        "input_kind": summary.get("input_kind"),
        "input_count": summary.get("input_count"),
        "planned_profiles": summary.get("planned_profiles", []),
        "adapters": summary.get("adapters", []),
        "rejected_inputs": summary.get("rejected_inputs", []),
    }
    return payload


def _write_bundle_payload(output_path: str | Path, payload: dict[str, object]) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_temporal_layer(
    input_path: str,
    sensory_type: str,
    *,
    output_path: str | Path | None = None,
) -> TemporalLayerBuildResult:
    selected_type = resolve_sensory_type(sensory_type)
    pipeline = TSELPipeline()
    plans, rejected_inputs = _prepare_input_plans(input_path, selected_type)
    packet_profile = plans[0].sensory_profile if len(plans) == 1 and Path(input_path).is_file() else "packet"
    collection = pipeline.ingest_auto_plans(plans)
    _annotate_collection(collection, selected_type, packet_profile)
    summary = build_layer_summary(
        input_path,
        collection,
        packet_profile,
        selected_type,
        plans=plans,
        rejected_inputs=rejected_inputs,
    )
    payload = _build_bundle_payload(collection, summary=summary)
    target_path = resolve_system_output_path(sensory_type_key=selected_type.key) if output_path is None else Path(output_path)
    _write_bundle_payload(target_path, payload)
    return TemporalLayerBuildResult(
        collection=collection,
        input_path=str(Path(input_path).resolve()),
        sensory_type=selected_type.key,
        sensory_type_label=selected_type.label,
        acquisition_profile=packet_profile,
        adapter=str(summary["adapter"]),
        output_path=str(target_path.resolve()),
        raw_preview=preview_input_text(input_path),
        output_payload=payload,
        summary=summary,
    )


class TSELViewer:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("TSEL Unified Temporal Layer")
        self.root.geometry("1500x920")
        self.root.minsize(1220, 760)
        self.root.report_callback_exception = self._report_callback_exception

        self.build_result: TemporalLayerBuildResult | None = None

        self.input_var = tk.StringVar()
        self.sensory_type_var = tk.StringVar()
        self.route_var = tk.StringVar(value="Awaiting raw sensory input")
        self.count_var = tk.StringVar(value="0 events | 0 streams")
        self.phase_var = tk.StringVar(value="No experience phases derived yet")
        self.experience_var = tk.StringVar(value="0 experiences | 0 continuity tracks")
        self.ontology_var = tk.StringVar(value="No sensory ontology derived yet")
        self.acquisition_var = tk.StringVar(value="No acquisition ontology derived yet")
        self.output_path_var = tk.StringVar(value=str(resolve_system_output_path()))
        self.status_var = tk.StringVar(
            value="Select raw sensory data or a packet directory, choose a sensory type, and build the unified temporal layer."
        )

        self._apply_theme()
        self._build_layout()

    def _apply_theme(self) -> None:
        self.root.configure(bg="#ebe5dc")
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("Shell.TFrame", background="#ebe5dc")
        style.configure("Hero.TFrame", background="#143042")
        style.configure(
            "HeroTitle.TLabel",
            background="#143042",
            foreground="#f8f2e8",
            font=("Bahnschrift SemiBold", 24),
        )
        style.configure(
            "HeroBody.TLabel",
            background="#143042",
            foreground="#d6e1e8",
            font=("Segoe UI", 10),
        )
        style.configure("Panel.TFrame", background="#fffaf2")
        style.configure("Panel.TLabelframe", background="#fffaf2", borderwidth=1, relief="solid")
        style.configure(
            "Panel.TLabelframe.Label",
            background="#fffaf2",
            foreground="#173042",
            font=("Bahnschrift SemiBold", 11),
        )
        style.configure("Panel.TLabel", background="#fffaf2", foreground="#173042", font=("Segoe UI", 10))
        style.configure(
            "InfoLabel.TLabel",
            background="#fffaf2",
            foreground="#6d7a86",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "InfoValue.TLabel",
            background="#fffaf2",
            foreground="#173042",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Accent.TButton",
            background="#c25a31",
            foreground="#ffffff",
            padding=(18, 12),
            borderwidth=0,
            font=("Bahnschrift SemiBold", 10),
        )
        style.map("Accent.TButton", background=[("active", "#ab4d28")])
        style.configure("TButton", padding=(10, 8), font=("Segoe UI Semibold", 9))
        style.configure("TLabel", background="#ebe5dc", foreground="#173042", font=("Segoe UI", 10))
        style.configure("TEntry", fieldbackground="#fffdf8", padding=6)
        style.configure("TCombobox", fieldbackground="#fffdf8", padding=6)
        style.configure(
            "Status.TLabel",
            background="#ebe5dc",
            foreground="#173042",
            font=("Segoe UI Semibold", 10),
        )

    def _configure_text_widget(self, widget: ScrolledText) -> None:
        widget.configure(
            bg="#fffdf8",
            fg="#173042",
            insertbackground="#173042",
            relief=tk.FLAT,
            borderwidth=0,
            padx=14,
            pady=14,
            font=("Consolas", 10),
        )

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, style="Shell.TFrame", padding=18)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        hero = ttk.Frame(outer, style="Hero.TFrame", padding=(24, 20))
        hero.grid(row=0, column=0, sticky="ew")
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text="Temporal Sensory Encoding Layer", style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            hero,
            text=(
                "TSEL has one job: take raw sensory data or a raw data packet, apply the selected sensory type, and emit one unified temporal code "
                "that preserves the temporal biological experience for the rest of the system."
            ),
            style="HeroBody.TLabel",
            wraplength=1080,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        controls = ttk.LabelFrame(outer, text="Build Temporal Layer", style="Panel.TLabelframe", padding=14)
        controls.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Raw Input / Packet", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(controls, textvariable=self.input_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(controls, text="File", command=self._browse_input).grid(row=0, column=2, padx=(8, 8))
        ttk.Button(controls, text="Folder", command=self._browse_packet).grid(row=0, column=3, padx=(0, 12))

        ttk.Label(controls, text="Sensory Type", style="Panel.TLabel").grid(row=0, column=4, sticky="w", padx=(0, 8))
        ttk.Combobox(
            controls,
            textvariable=self.sensory_type_var,
            state="readonly",
            values=available_sensory_type_labels(),
            width=24,
        ).grid(row=0, column=5, sticky="w")
        ttk.Button(controls, text="Build Temporal Layer", style="Accent.TButton", command=self.load).grid(
            row=0,
            column=6,
            padx=(14, 0),
        )

        ttk.Label(
            controls,
            text=(
                "The selector uses explicit sensory classes only. EEG is treated as an internal measurement route when present in the raw file, "
                "and the selected sense controls where the temporal layer is stored. A folder is treated as one raw data packet and unified into one bundle."
            ),
            style="Panel.TLabel",
            wraplength=1160,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=7, sticky="w", pady=(12, 0))

        status = ttk.LabelFrame(outer, text="Current Layer Output", style="Panel.TLabelframe", padding=14)
        status.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        status.columnconfigure(1, weight=1)

        ttk.Label(status, text="Route", style="InfoLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(status, textvariable=self.route_var, style="InfoValue.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(status, text="Events", style="InfoLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.count_var, style="InfoValue.TLabel").grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(status, text="Experience Phases", style="InfoLabel.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.phase_var, style="InfoValue.TLabel").grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(status, text="Experience Tracks", style="InfoLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.experience_var, style="InfoValue.TLabel").grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Label(status, text="Sensory Ontology", style="InfoLabel.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.ontology_var, style="InfoValue.TLabel").grid(row=4, column=1, sticky="w", pady=(8, 0))
        ttk.Label(status, text="Acquisition Ontology", style="InfoLabel.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Label(status, textvariable=self.acquisition_var, style="InfoValue.TLabel").grid(row=5, column=1, sticky="w", pady=(8, 0))
        ttk.Label(status, text="Stored Output", style="InfoLabel.TLabel").grid(row=6, column=0, sticky="nw", pady=(8, 0))
        output_entry = ttk.Entry(status, textvariable=self.output_path_var, state="readonly")
        output_entry.grid(row=6, column=1, sticky="ew", pady=(8, 0))

        panes = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        panes.grid(row=3, column=0, sticky="nsew", pady=(14, 0))

        input_panel = ttk.LabelFrame(panes, text="Raw Sensory Input", style="Panel.TLabelframe", padding=10)
        output_panel = ttk.LabelFrame(panes, text="Unified Temporal Code", style="Panel.TLabelframe", padding=10)
        panes.add(input_panel, weight=2)
        panes.add(output_panel, weight=3)

        input_panel.rowconfigure(1, weight=1)
        input_panel.columnconfigure(0, weight=1)
        output_panel.rowconfigure(1, weight=1)
        output_panel.columnconfigure(0, weight=1)

        ttk.Label(
            input_panel,
            text="Preview of the incoming raw sensory source or packet before temporal normalization.",
            style="Panel.TLabel",
            wraplength=520,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.raw_input_text = ScrolledText(input_panel, wrap=tk.WORD)
        self.raw_input_text.grid(row=1, column=0, sticky="nsew")
        self._configure_text_widget(self.raw_input_text)

        ttk.Label(
            output_panel,
            text="The exact bundle written for system use, including derived experience phases when the data supports them. If the output is very large, the viewer shows a truncated preview and keeps the full file on disk.",
            style="Panel.TLabel",
            wraplength=720,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.output_text = ScrolledText(output_panel, wrap=tk.WORD)
        self.output_text.grid(row=1, column=0, sticky="nsew")
        self._configure_text_widget(self.output_text)

        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", wraplength=1280, justify=tk.LEFT).grid(
            row=4,
            column=0,
            sticky="w",
            pady=(12, 0),
        )

        self._set_text(self.raw_input_text, "Select a raw sensory file or packet directory to preview the incoming source data.")
        self._set_text(
            self.output_text,
            (
                "Build the temporal layer to write the unified code to a sense-specific storage path and display the stored bundle here.\n\n"
                f"Base output path: {ROOT_DIR / 'output'}"
            ),
        )

    def _browse_input(self) -> None:
        selected = filedialog.askopenfilename(title="Select raw sensory input file")
        if selected:
            self.input_var.set(selected)

    def _browse_packet(self) -> None:
        selected = filedialog.askdirectory(title="Select raw sensory packet directory")
        if selected:
            self.input_var.set(selected)

    def _record_error(self, details: str) -> Path:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ERROR_LOG_PATH.write_text(details, encoding="utf-8")
        return ERROR_LOG_PATH

    def _report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        error_path = self._record_error(details)
        self.status_var.set(f"Viewer error captured. Details written to {error_path}.")
        messagebox.showerror(
            "TSEL Viewer",
            f"Unexpected viewer error. Details were written to {error_path}.\n\n{exc_value}",
        )

    def load(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            messagebox.showerror("TSEL Viewer", "Select a raw input file or packet directory first.")
            return

        selected_sensory_type = self.sensory_type_var.get().strip()
        if not selected_sensory_type:
            messagebox.showerror("TSEL Viewer", "Select a sensory type before building the temporal layer.")
            return

        self.status_var.set("Building the unified temporal layer...")
        self.root.update_idletasks()
        try:
            result = build_temporal_layer(input_path, selected_sensory_type)
        except Exception as exc:  # noqa: BLE001
            error_path = self._record_error(traceback.format_exc())
            self.status_var.set(f"Build failed. Details written to {error_path}.")
            messagebox.showerror("TSEL Viewer", f"{exc}\n\nDetails were written to {error_path}.")
            return

        self.build_result = result
        summary = result.summary["summary"]
        input_count = int(result.summary.get("input_count", 1))
        planned_profiles = list(result.summary.get("planned_profiles", []))
        rejected_count = int(result.summary.get("rejected_input_count", 0))
        adapters = list(result.summary.get("adapters", []))
        if result.summary.get("input_kind") == "packet":
            route_profiles = ", ".join(planned_profiles) if planned_profiles else result.acquisition_profile
            adapter_label = ", ".join(adapters) if adapters else result.adapter
            self.route_var.set(f"{result.sensory_type_label} -> packet ({input_count} inputs) via {route_profiles} [{adapter_label}]")
        else:
            self.route_var.set(f"{result.sensory_type_label} -> {result.acquisition_profile} via {result.adapter}")
        self.count_var.set(f"{summary['event_count']} events | {summary['stream_count']} streams")
        phases = summary.get("phases", [])
        self.phase_var.set(", ".join(phases) if phases else "No phases derived")
        self.experience_var.set(f"{summary.get('experience_count', 0)} experiences | {summary.get('continuity_count', 0)} continuity tracks")
        primary_senses = summary.get("primary_senses", [])
        submodalities = summary.get("submodalities", [])
        ontology_bits = []
        if primary_senses:
            ontology_bits.append("senses: " + ", ".join(primary_senses))
        if submodalities:
            ontology_bits.append("submodalities: " + ", ".join(submodalities))
        ontology_bits.append(f"relations: {summary.get('relation_count', 0)}")
        self.ontology_var.set(" | ".join(ontology_bits))
        acquisition_profiles = summary.get("acquisition_profiles", [])
        acquisition_bits = [
            f"profiles: {', '.join(acquisition_profiles) if acquisition_profiles else 'none'}",
            f"inputs: {input_count}",
            f"skipped: {rejected_count}",
            f"windows: {summary.get('window_count', 0)}",
            f"stimuli: {summary.get('stimulus_count', 0)}",
        ]
        self.acquisition_var.set(" | ".join(acquisition_bits))
        self.output_path_var.set(result.output_path)
        skipped_text = f" with {rejected_count} skipped packet members" if rejected_count else ""
        self.status_var.set(
            f"Unified temporal code built from {Path(result.input_path).name}, stored at {result.output_path}, and phase-coded across the preserved sensory episode{skipped_text}."
        )
        self._set_text(self.raw_input_text, result.raw_preview)
        self._set_text(self.output_text, result.output_text)

    def _set_text(self, widget: ScrolledText, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        widget.configure(state=tk.DISABLED)


def main() -> None:
    root = tk.Tk()
    TSELViewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()




