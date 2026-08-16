"""Test-session safety net.

`Settings` reads KIS credentials and PAPER_TRADING from the environment at
import time via `load_dotenv()`. A developer machine with real credentials
in `.env` could otherwise let a test that forgets to pass explicit paper
settings construct a live executor and submit a real order. This module is
collected by pytest before any test module imports `src.config`, so it wins
the "first value sticks" race against `load_dotenv()` (which never
overrides an already-set variable).

Tests that intentionally exercise live-mode wiring pass explicit kwargs to
`Settings(...)` and are unaffected by this.
"""

import os

os.environ["PAPER_TRADING"] = "true"
os.environ["KIS_ENV"] = ""
os.environ["KIS_APPKEY"] = ""
os.environ["KIS_APPSECRET"] = ""
os.environ["KIS_CANO"] = ""
os.environ["TELEGRAM_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
