from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tsel.balance_diagnostics import run_balance_diagnostics


if __name__ == "__main__":
    payload = run_balance_diagnostics()
    print(json.dumps(payload["balance_metrics"], indent=2))
    print(json.dumps(payload["outputs"], indent=2))
