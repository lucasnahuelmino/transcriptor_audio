from __future__ import annotations

import io
import os
import json
import zipfile
import datetime as dt
from pathlib import Path

import streamlit as st

from enacom_transcriptor.paths import LOGO_PATH, CSS_PATH, BACKUP_DIR
from enacom_transcriptor.infracciones import parse_infracciones_text


WIDGET_VER = "v6"
_UI_NONCE_KEY = "ui_reset_nonce"


# -----------------------------
# Keys / nonce
# -----------------------------
def k(name: str) -> str:
    return f"{WIDGET_VER}_{name}"


def _ui_nonce() -> int:
    return int(st.session_state.get(_UI_NONCE_KEY, 0))


# -----------------------------
# Page / Style
# -----------------------------
def set_page() -> None:
    # Debe ser lo primero que se ejecute (antes de cualquier st.*)
    st.set_page_config(
        page_title="🎧 Transcriptor de audios a texto - ENACOM",
        layout="wide",
    )


def load_css() -> None:
    if CSS_PATH.exists():
        try:
            with open(CSS_PATH, "r", encoding="utf-8") as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
        except Exception:
            pass


# -----------------------------
# Clear current run
# -----------------------------
def _clear_current_run() -> None:
    """
    Limpia la corrida actual (panel de descargas/resultados/meta) y resetea widgets
    de entrada para evitar que queden audios/búsquedas “pegadas”.
    """
    st.session_state["procesado"] = False
    st.session_state["resultados"] = []
    st.session_state["lote_result"] = None
    st.session_state["run_meta"] = None
    st.session_state["run_package"] = None

    # Reset de widgets de entrada (file_uploader/search/etc.) usando nonce en las keys
    st.session_state[_UI_NONCE_KEY] = _ui_nonce() + 1


# -----------------------------
# Small helpers
# -----------------------------
def _dl_btn(col, label: str, path: str | None, mime: str, key: str) -> None:
    with col:
        if path and os.path.exists(path):
            st.download_button(
                label,
                Path(path).read_bytes(),
                file_name=Path(path).name,
                mime=mime,
                use_container_width=True,
                key=key,
            )
        else:
            # Mantenemos el “espacio” para que todo quede alineado
            st.caption("—")


def _meta_json_bytes(meta: dict | None) -> bytes:
    payload = meta or {}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _zip_fallback_bytes(resultados: list[dict], lote: dict | None, meta: dict | None) -> bytes:
    """
    Fallback: genera ZIP en memoria si no existe run_package en disco.
    (Normalmente processing.py ya genera run_package).
    """
    buf = io.BytesIO()
    ts = (meta or {}).get("generado", dt.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
    ts = str(ts).replace(":", "").replace(" ", "_")
    base_dir = f"transcripciones_{ts}"

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base_dir}/meta.json", _meta_json_bytes(meta))

        if lote:
            for ext in ("txt", "xlsx", "docx"):
                p = lote.get(ext)
                if p and os.path.exists(p):
                    z.write(p, arcname=f"{base_dir}/LOTE/{Path(p).name}")

        for r in resultados:
            arch = (r.get("archivo") or "archivo").strip()
            safe_dir = Path(arch).stem or "archivo"
            for ext in ("txt", "xlsx", "docx"):
                p = r.get(ext)
                if p and os.path.exists(p):
                    z.write(p, arcname=f"{base_dir}/IND/{safe_dir}/{Path(p).name}")

    return buf.getvalue()


def _render_lote_block(lote: dict) -> None:
    with st.container(border=True):
        st.markdown("### 📦 Lote consolidado")
        c1, c2, c3 = st.columns(3)
        _dl_btn(c1, "TXT (Lote)", lote.get("txt"), "text/plain", k("dl_lote_txt"))
        _dl_btn(
            c2,
            "XLSX (Lote)",
            lote.get("xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            k("dl_lote_xlsx"),
        )
        _dl_btn(
            c3,
            "DOCX (Lote)",
            lote.get("docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            k("dl_lote_docx"),
        )


def _render_individuals_table(resultados: list[dict]) -> None:
    with st.container(border=True):
        st.markdown("### 🎧 Archivos individuales")

        top1, top2, top3 = st.columns([2.2, 1.2, 1])
        with top1:
            q = st.text_input("Filtrar por nombre", "", key=k("run_filter")).strip().lower()
        with top2:
            page_size = st.selectbox("Por página", [10, 20, 40, 80], index=1, key=k("run_pagesize"))
        with top3:
            sort_mode = st.selectbox("Orden", ["Nombre (A→Z)", "Nombre (Z→A)"], index=0, key=k("run_sort"))

        items = resultados
        if q:
            items = [r for r in items if q in (r.get("archivo", "").lower())]

        # Orden
        items = sorted(items, key=lambda r: (r.get("archivo") or "").lower(), reverse=(sort_mode == "Nombre (Z→A)"))

        if not items:
            st.info("No hay archivos que coincidan con ese filtro.")
            return

        total = len(items)
        pages = max(1, (total + page_size - 1) // page_size)

        nav1, nav2, nav3 = st.columns([1, 1, 2])
        with nav1:
            page = st.number_input("Página", min_value=1, max_value=pages, value=1, step=1, key=k("run_page"))
        with nav2:
            st.caption(f"{total} archivo(s)")
        with nav3:
            st.caption("Tip: si querés todo junto, el ZIP es lo más cómodo")

        start = (int(page) - 1) * int(page_size)
        end = min(start + int(page_size), total)
        view = items[start:end]

        # Encabezado tipo tabla
        h1, h2, h3, h4 = st.columns([3.2, 1, 1, 1])
        with h1:
            st.markdown("**Archivo**")
        with h2:
            st.markdown("**TXT**")
        with h3:
            st.markdown("**XLSX**")
        with h4:
            st.markdown("**DOCX**")

        st.divider()

        for i, r in enumerate(view, start=start):
            archivo = r.get("archivo", f"archivo_{i}")

            row1, row2, row3, row4 = st.columns([3.2, 1, 1, 1])
            with row1:
                st.markdown(f"**{archivo}**")

            _dl_btn(row2, "TXT", r.get("txt"), "text/plain", k(f"dl_txt_{i}"))
            _dl_btn(
                row3,
                "XLSX",
                r.get("xlsx"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                k(f"dl_xlsx_{i}"),
            )
            _dl_btn(
                row4,
                "DOCX",
                r.get("docx"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                k(f"dl_docx_{i}"),
            )

            # Separador suave
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)


# -----------------------------
# Header / Config / Sidebar
# -----------------------------
def render_header() -> None:
    c1, c2 = st.columns([4, 1])

    with c2:
        if LOGO_PATH.exists():
            try:
                st.image(str(LOGO_PATH), use_container_width=True)
            except Exception:
                st.caption("ENACOM")
        else:
            st.caption("ENACOM")

 
    with c1:
        st.markdown("### 🎧 Transcriptor de audios a texto - ENACOM")


def render_config() -> dict:
    st.markdown("### Configuración del procesamiento")

    c1, c2, c3, c4, c5 = st.columns([1.2, 1.2, 1.2, 1.2, 1])

    with c1:
        model_size = st.selectbox(
            "Modelo Whisper",
            ["small", "medium"],
            index=0,
            key=k("cfg_model"),
            help="small = más rápido • medium = más calidad",
        )

    with c2:
        selected_language = st.selectbox(
            "Idioma del audio",
            ["es", "en", "pt", "auto"],
            index=0,
            key=k("cfg_lang"),
        )

    with c3:
        segment_duration = st.number_input(
            "Duración de segmento (s)",
            min_value=5,
            max_value=60,
            value=20,
            step=5,
            key=k("cfg_seg"),
            help="Duración de segmentos de transcripción.",
        )

    with c4:
        modo_lote = st.radio(
            "Informe final",
            ["Individual", "Combinado"],
            index=0,
            key=k("cfg_mode"),
            help="Informes finales individuales o combinando varios archivos de audio.",
        )

    with c5:
        st.caption("Opciones avanzadas")
        export_zip = st.toggle(
            "Generar ZIP",
            value=True,
            key=k("cfg_zip"),
            help="Incluye archivos generados y meta.json",
        )
        diarization = st.toggle(
            "Diarización (beta)",
            value=False,
            key=k("cfg_diar"),
            help="Detecta hablantes (experimental). Si faltan dependencias/token, continúa sin hablantes.",
        )

    st.markdown("##### Palabras/Frases de Infracción")
    raw = st.text_area(
        "Separá por comas",
        "mayday, emergencia, interferencia, desvío, alerta",
        key=k("cfg_inf_raw"),
        height=90,
        help="Ej.: mayday, emergencia, interferencia",
    )

    infracciones = parse_infracciones_text(raw)
    lang = None if selected_language == "auto" else selected_language

    return {
        "model_size": model_size,
        "lang": lang,
        "segment_duration": int(segment_duration),
        "modo_lote": modo_lote,
        "infracciones": infracciones,
        "export_zip": bool(export_zip),
        "diarization": bool(diarization),
    }


def render_sidebar() -> dict:
    nonce = _ui_nonce()

    st.sidebar.markdown("### 🎛️ Entrada")
    audio_files = st.sidebar.file_uploader(
        "🎧 Cargar uno o varios audios",
        type=["mp3", "wav", "m4a"],
        accept_multiple_files=True,
        key=f"{k('sb_files')}_{nonce}",
    )

    query_busqueda = st.sidebar.text_input(
        "🔍 Buscar palabra/frase (en vivo):",
        "",
        key=f"{k('sb_query')}_{nonce}",
    )

    coincidencia_parcial = st.sidebar.checkbox(
        "Coincidencia parcial (contiene)",
        value=True,
        key=f"{k('sb_partial')}_{nonce}",
    )

    return {
        "audio_files": audio_files,
        "query_busqueda": query_busqueda,
        "coincidencia_parcial": coincidencia_parcial,
    }


# -----------------------------
# Downloads + History (Tabs)
# -----------------------------
def render_downloads() -> None:
    resultados = st.session_state.get("resultados") or []
    lote = st.session_state.get("lote_result")
    meta = st.session_state.get("run_meta")
    run_zip = st.session_state.get("run_package")

    if not resultados and not lote:
        return

    tab1, tab2 = st.tabs(["📦 Transcripciones actuales", "🗂️ Historial"])

    with tab1:
        st.markdown("## 📥 Descargas disponibles")

        # Métricas arriba
        if meta:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Modo", str(meta.get("modo", "")))
            m2.metric("Modelo", str(meta.get("model_size", "")))
            m3.metric("Duración total", str(meta.get("total_duration_hhmmss", "")))
            m4.metric(
                "Infracciones",
                f"{meta.get('infracciones_total', 0)} (en {meta.get('archivos_con_infracciones', 0)} archivos)",
            )

        with st.container(border=True):
            a1, a2 = st.columns([1.6, 1])


            with a1:
                if run_zip and os.path.exists(run_zip):
                    st.download_button(
                        "📦 Descargar transcripción completa (ZIP)",
                        Path(run_zip).read_bytes(),
                        file_name=Path(run_zip).name,
                        mime="application/zip",
                        use_container_width=True,
                        key=k("dl_run_zip"),
                    )
                else:
                    
                    zip_bytes = _zip_fallback_bytes(resultados, lote, meta)
                    st.download_button(
                        "📦 Descargar transcripción completa (ZIP)",
                        zip_bytes,
                        file_name="corrida_transcripciones.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key=k("dl_run_zip_fallback"),
                    )

            with a2:
                st.button(
                    "🧹 Limpiar transcripciones actuales",
                    on_click=_clear_current_run,
                    use_container_width=True,
                    key=k("btn_clear_run"),
                )

    
        if lote and any([lote.get("txt"), lote.get("xlsx"), lote.get("docx")]):
            _render_lote_block(lote)

        if resultados:
            _render_individuals_table(resultados)

    with tab2:
        render_history()


def render_history() -> None:
    
    with st.expander("📁 Historial de transcripciones (agrupado por base)", expanded=False):
        try:
            os.makedirs(str(BACKUP_DIR), exist_ok=True)
            files = [
                Path(BACKUP_DIR) / f
                for f in os.listdir(str(BACKUP_DIR))
                if f.lower().endswith((".txt", ".xlsx", ".docx", ".zip"))
            ]
        except Exception:
            files = []

        if not files:
            st.info("Todavía no hay archivos generados en la carpeta de transcripciones.")
            return

        def human_size(n: int) -> str:
            x = float(n)
            for unit in ["B", "KB", "MB", "GB"]:
                if x < 1024:
                    return f"{x:.0f} {unit}" if unit == "B" else f"{x:.1f} {unit}"
                x /= 1024
            return f"{x:.1f} TB"

        
        groups: dict[str, dict] = {}
        for p in files:
            base = p.stem
            ext = p.suffix.lower().lstrip(".")  # txt/xlsx/docx/zip

            try:
                stt = p.stat()
                mtime = stt.st_mtime
                size = stt.st_size
            except Exception:
                mtime = 0
                size = 0

            tag = "📦 LOTE" if base.lower().startswith("lote_") else ("🧰 ZIP LOTE" if base.lower().startswith("corrida_") else "🎧 IND")

            g = groups.setdefault(
                base,
                {"base": base, "tag": tag, "mtime": 0, "size": 0, "paths": {}},
            )

            g["paths"][ext] = p
            g["mtime"] = max(g["mtime"], mtime)
            g["size"] += size

        items = list(groups.values())
        items.sort(key=lambda x: x["mtime"], reverse=True)

        c1, c2 = st.columns([2, 1])
        with c1:
            search = st.text_input("Buscar por nombre (base)", "", key=k("hist_search")).strip().lower()
        with c2:
            flt = st.selectbox("Filtro", ["Todos", "Solo LOTES", "Solo IND", "Solo CORRIDAS"], key=k("hist_filter"))

        def passes(it: dict) -> bool:
            if flt == "Solo LOTES" and it["tag"] != "📦 LOTE":
                return False
            if flt == "Solo IND" and it["tag"] != "🎧 IND":
                return False
            if flt == "Solo CORRIDAS" and it["tag"] != "🧰 ZIP":
                return False
            if search and search not in it["base"].lower():
                return False
            return True

        items = [it for it in items if passes(it)]
        if not items:
            st.warning("No hay resultados con ese filtro/búsqueda.")
            return

        def label(it: dict) -> str:
            t = dt.datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d %H:%M:%S") if it["mtime"] else "¿?"
            sz = human_size(int(it["size"]))
            has = [ext.upper() for ext in ("zip", "docx", "xlsx", "txt") if ext in it["paths"]]
            return f"{it['tag']} • {t} • {sz} • ({', '.join(has)}) — {it['base']}"

        selected = st.selectbox(
            "Elegí un ítem:",
            options=items,
            index=0,
            format_func=label,
            key=k("hist_select"),
        )

        t = dt.datetime.fromtimestamp(selected["mtime"]).strftime("%Y-%m-%d %H:%M:%S") if selected["mtime"] else ""
        st.caption(f"Última modificación: {t} • Tamaño total: {human_size(int(selected['size']))}")

        p_zip = selected["paths"].get("zip")
        p_docx = selected["paths"].get("docx")
        p_xlsx = selected["paths"].get("xlsx")
        p_txt = selected["paths"].get("txt")

        b1, b2, b3, b4 = st.columns(4)

        with b1:
            if p_zip and p_zip.exists():
                st.download_button(
                    "📦 ZIP",
                    p_zip.read_bytes(),
                    file_name=p_zip.name,
                    mime="application/zip",
                    key=k(f"hist_zip_{selected['base']}"),
                )
            else:
                st.caption("ZIP —")

        with b2:
            if p_docx and p_docx.exists():
                st.download_button(
                    "📄 DOCX",
                    p_docx.read_bytes(),
                    file_name=p_docx.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=k(f"hist_docx_{selected['base']}"),
                )
            else:
                st.caption("DOCX —")

        with b3:
            if p_xlsx and p_xlsx.exists():
                st.download_button(
                    "📊 XLSX",
                    p_xlsx.read_bytes(),
                    file_name=p_xlsx.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=k(f"hist_xlsx_{selected['base']}"),
                )
            else:
                st.caption("XLSX —")

        with b4:
            if p_txt and p_txt.exists():
                st.download_button(
                    "📝 TXT",
                    p_txt.read_bytes(),
                    file_name=p_txt.name,
                    mime="text/plain",
                    key=k(f"hist_txt_{selected['base']}"),
                )
            else:
                st.caption("TXT —")
