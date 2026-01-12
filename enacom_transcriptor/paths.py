from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

ASSETS_DIR = BASE_DIR / "assets"
STYLES_DIR = BASE_DIR / "styles"
BIN_DIR = BASE_DIR / "bin"
BACKUP_DIR = BASE_DIR / "transcripciones"
LOGO_PATH = ASSETS_DIR / "logo_enacom.png"
CSS_PATH = STYLES_DIR / "enacom.css"
TEMPLATE_PATH = ASSETS_DIR / "plantilla_enacom.docx"

def ensure_dirs() -> None:
    """Crea carpetas esperadas por la app (idempotente)."""
    for p in (ASSETS_DIR, STYLES_DIR, BIN_DIR, BACKUP_DIR):
        p.mkdir(parents=True, exist_ok=True)
