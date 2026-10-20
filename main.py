"""Run Pedro_Agent.

    python main.py
    python main.py --init
    python main.py --voice
"""

try:
    import crash_reports

    crash_reports.install()
except Exception:
    pass
from agent_core import main

if __name__ == "__main__":
    raise SystemExit(main())
