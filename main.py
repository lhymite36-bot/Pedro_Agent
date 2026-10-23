"""Run Pedro_Agent.

    python main.py
    python main.py --init
    python main.py --voice
"""

import sys

# pythonw / redirected logs on Windows default to cp1252: never crash on emoji or \ufeff.
for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import crash_reports

    crash_reports.install()
except Exception:
    pass
from agent_core import main

if __name__ == "__main__":
    raise SystemExit(main())
