"""Vercel entrypoint.

Vercel's Python runtime looks for an ASGI application named ``app`` in this
file. All real logic lives in the ``inbound`` package so it can also be run locally
with ``uvicorn inbound.main:app``.
"""

import sys
from pathlib import Path

# Make the project root importable regardless of how the runtime sets sys.path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from inbound.main import app  # noqa: E402,F401  (re-exported for Vercel)
