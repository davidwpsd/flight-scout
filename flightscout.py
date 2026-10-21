#!/usr/bin/env python3
"""Entry point:  python flightscout.py [providers|search|serve]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flight_scout.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
