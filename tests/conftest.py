import sys
from pathlib import Path

# Make test_harness/ importable for tests that exercise the harness modules
# (features, assertions) under repo-root pytest collection (the CI unit job).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "test_harness"))
