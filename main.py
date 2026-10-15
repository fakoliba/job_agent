"""Run from project root: `streamlit run main.py` (same UI as `streamlit run ui/app.py`)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_app = ROOT / "ui" / "app.py"
_globals = {
    "__name__": "__main__",
    "__file__": str(_app),
    "__builtins__": __builtins__,
    "__doc__": None,
}
exec(compile(_app.read_text(), str(_app), "exec"), _globals)
