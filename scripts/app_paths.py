"""Public assets beside the executable; never use the user's current directory."""
from pathlib import Path
import sys
import os

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
API_ONLY = os.environ.get('LITERACY_ASSISTANT_API_ONLY') == '1' or (ROOT / 'api-only.json').is_file()
