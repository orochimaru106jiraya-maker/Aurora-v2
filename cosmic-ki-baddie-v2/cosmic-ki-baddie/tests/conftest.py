"""Pytest configuration and shared fixtures for Project Nova automated tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tests.discord_shim import install_discord_shim_if_needed

install_discord_shim_if_needed()
