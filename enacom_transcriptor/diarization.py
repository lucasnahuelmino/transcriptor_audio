from __future__ import annotations

from typing import List, Dict, Optional
import numpy as np

def diarize_audio(data: np.ndarray, samplerate: int) -> Optional[List[Dict]]:
    """
    Devuelve lista de segmentos: [{"start": float, "end": float, "speaker": str}, ...]
    Requiere pyannote. Si falla, devuelve None.
    """
    try:
        import torch
        from pyannote.audio import Pipeline
    except Exception:
        return None

    try:
        # soundfile suele devolver (time,) o (time, channels)
        if data.ndim == 1:
            wav = data[None, :]
        else:
            wav = data.T  # (channels, time)

        wav = wav.astype("float32", copy=False)
        waveform = torch.from_numpy(wav)

        # IMPORTANTE: acá podría requerir token si el modelo lo pide.
        # Si no tenés token / no hay conectividad, esto puede fallar.
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")

        diar = pipeline({"waveform": waveform, "sample_rate": int(samplerate)})

        out: List[Dict] = []
        for turn, _, speaker in diar.itertracks(yield_label=True):
            out.append({
                "start": float(turn.start),
                "end": float(turn.end),
                "speaker": str(speaker),
            })
        return out
    except Exception:
        return None
