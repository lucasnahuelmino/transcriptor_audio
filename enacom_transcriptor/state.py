import streamlit as st


def ensure_session_state():
    if "procesado" not in st.session_state:
        st.session_state.procesado = False
    if "resultados" not in st.session_state:
        st.session_state.resultados = []
