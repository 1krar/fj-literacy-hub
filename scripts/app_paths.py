"""Public assets beside the executable; never use the user's current directory."""
from pathlib import Path
import sys

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
