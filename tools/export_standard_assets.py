from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tsel.standards import write_standard_assets


if __name__ == "__main__":
    target = ROOT / "standards"
    written = write_standard_assets(target)
    for path in written:
        print(path)