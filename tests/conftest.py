import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT_DIR / "agent"
EVAL_DIR = ROOT_DIR / "evaluations"
BACKEND_DIR = ROOT_DIR / "backend"

for p in [ROOT_DIR, AGENT_DIR, EVAL_DIR, BACKEND_DIR]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)
