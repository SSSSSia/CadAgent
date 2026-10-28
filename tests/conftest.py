"""Shared pytest configuration for the CadAgent test suite.

Puts the project root on sys.path once, so every test module can
`import agent.*` / `import core.*` / `from tests.helpers import ...`
without repeating its own sys.path bootstrap.

Intentionally minimal: no autouse fixtures, no global sys.modules
mutation — mock installation stays explicit in the test files that
need it (see tests/helpers.py for reusable mechanisms).
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
