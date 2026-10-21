"""Console encoding helpers.

Windows consoles often default to a legacy code page (cp950 / cp1252), which
makes ``print()`` of Chinese text or emoji raise ``UnicodeEncodeError`` and kill
a long-running server before it even starts. Switch the console to UTF-8 and make
both streams forgiving instead of crashing.
"""

from __future__ import annotations

import os
import sys


def setup_console() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - best effort, never fatal
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - redirected streams may not support it
            pass
