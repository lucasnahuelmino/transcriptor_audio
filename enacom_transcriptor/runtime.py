from __future__ import annotations

import os
import shutil
from pathlib import Path

from enacom_transcriptor.paths import BIN_DIR, ensure_dirs


def configure_runtime() -> None:
    """
    Configura el entorno de ejecución:
    - Crea directorios requeridos.
    - Agrega /bin al PATH del proceso.
    - Asegura disponibilidad de ffmpeg para Whisper.
    """
    ensure_dirs()
    _prepend_bin_to_path(BIN_DIR)
    ensure_ffmpeg()


def ensure_ffmpeg() -> str | None:
    """
    Obtiene una ruta usable a ffmpeg para Whisper.

    Orden de preferencia:
    1) ffmpeg disponible en PATH.
    2) Copiar el ffmpeg provisto por imageio-ffmpeg a /bin/ffmpeg.exe.
    """
    ensure_dirs()

    ff = shutil.which("ffmpeg")
    if ff:
        return ff

    try:
        import imageio_ffmpeg  # type: ignore
    except Exception:
        return None

    try:
        src = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if not src.exists():
            return None

        dst = BIN_DIR / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if not dst.exists():
            shutil.copy2(str(src), str(dst))

        return str(dst)
    except Exception:
        return None


def _prepend_bin_to_path(bin_dir: Path) -> None:
    """Agrega bin_dir al inicio del PATH del proceso (idempotente)."""
    bin_str = str(bin_dir)
    current = os.environ.get("PATH", "")

    parts = [p for p in current.split(os.pathsep) if p]
    if bin_str not in parts:
        os.environ["PATH"] = bin_str + os.pathsep + current
