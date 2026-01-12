from __future__ import annotations

import streamlit as st
import whisper


ALLOWED_MODELS = ("small", "medium")


@st.cache_resource(show_spinner=False)
def load_model_cached(model_size: str):
    """
    Carga Whisper (cacheado). Solo permite small/medium.
    Si llega otro, lo corrige a 'small'.
    """
    model_size = (model_size or "small").strip().lower()
    if model_size not in ALLOWED_MODELS:
        model_size = "small"

    try:
        return whisper.load_model(model_size)
    except Exception as e:
        st.error(f"No se pudo cargar el modelo Whisper '{model_size}': {e}")
        return None
