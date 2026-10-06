"""Общие пути lamodamarketing.

Скрипты автономны, но Python venv, data-lake (COGS) и notify_telegram
остаются в wb-ad-agents — задаётся WB_AGENTS_ROOT.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
WB_AGENTS = Path(os.environ.get(
    "WB_AGENTS_ROOT",
    r"C:\Users\yablonskaya.o.n\Desktop\reznikowaol\wb-ad-agents",
))
PYTHON = Path(os.environ.get(
    "LAMODA_PYTHON",
    WB_AGENTS / "portal" / ".venv" / "Scripts" / "python.exe",
))
NOTIFY_PS = WB_AGENTS / "scripts" / "notify_telegram.ps1"
NOTIFY_PS1 = NOTIFY_PS  # alias for auto_pricer
DATALAKE_DIR = WB_AGENTS / "scripts" / "datalake"


def load_cfg() -> dict:
    for p in creds_paths():
        if p.is_file():
            cfg = {}
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
            return cfg
    raise SystemExit("нет ключей Ламоды (creds\\Ламода\\lamoda_api.txt)")


def creds_paths():
    yield Path.home() / "Desktop" / "creds" / "Ламода" / "lamoda_api.txt"
    yield ROOT / "secrets" / "lamoda_api.txt"
    yield WB_AGENTS / "creds" / "Ламода" / "lamoda_api.txt"
