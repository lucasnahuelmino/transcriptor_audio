from __future__ import annotations

import base64
import datetime
import pathlib

import numpy as np
import plotly.graph_objects as go
import streamlit as st

def hhmmss(seconds: int) -> str:
    return str(datetime.timedelta(seconds=int(seconds)))

def audio_player_with_jumps(audio_path: str, key_suffix: str = "") -> None:
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    audio_base64 = base64.b64encode(audio_bytes).decode()

    ext = pathlib.Path(audio_path).suffix.lower()
    if ext == ".mp3":
        mime = "audio/mpeg"
    elif ext in [".m4a", ".mp4", ".aac"]:
        mime = "audio/mp4"
    else:
        mime = "audio/wav"

    audio_html = f"""
    <div class="enacom-card">
      <audio id="player{key_suffix}" controls style="width: 100%">
        <source src="data:{mime};base64,{audio_base64}" type="{mime}">
      </audio>
    </div>
    <script>
      function playFrom_{key_suffix}(seconds) {{
        var p = document.getElementById("player{key_suffix}");
        try {{ p.currentTime = seconds; p.play(); }} catch(e) {{ p.play(); }}
      }}
      window.playFrom_{key_suffix} = playFrom_{key_suffix};
    </script>
    """
    st.components.v1.html(audio_html, height=120)

def visualizar_audio(samplerate: int, data: np.ndarray, height: int = 220, title: str = "📈 Forma de onda"):
    if data.ndim == 2:
        data = data.mean(axis=1)

    dur = len(data) / samplerate if samplerate else 0.0

    if len(data) > 300_000 and samplerate:
        factor = len(data) // 300_000 + 1
        data = data[::factor]
        samplerate = int(samplerate / factor)
        dur = len(data) / samplerate if samplerate else 0.0

    t = np.linspace(0, dur, num=len(data)) if len(data) else np.array([0.0])
    a = np.abs(data)
    maxv = float(np.max(a)) if len(a) else 1.0
    if maxv == 0:
        maxv = 1.0
    a = a / maxv

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t, y=a, mode="lines", name="Amplitud", line=dict(width=1)))
    fig.update_layout(
        title=title,
        xaxis_title="Tiempo (s)",
        yaxis_title="Nivel normalizado",
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
