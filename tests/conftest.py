"""1.9.2: older suites test features, not the plan, so they run as Pro. test_plan191 clears this itself."""
import os
os.environ.setdefault("PEDBOT_FORCE_PLAN", "pro")
