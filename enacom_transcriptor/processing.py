from __future__ import annotations

import datetime
import html
import json
import math
import os
import pickle
import tempfile
import time
import zipfile
from pathlib import Path

import pandas as pd
import soundfile as sf
import streamlit as st

from enacom_transcriptor.audio_ui import hhmmss, visualizar_audio, audio_player_with_jumps
from enacom_transcriptor.exporters import (
    append_to_excel,
    ensure_excel_file,
    generar_informe_word,
    write_infracciones_excel,
)
from enacom_transcriptor.infracciones import detectar_infracciones_en_texto
from enacom_transcriptor.model import load_model_cached
from enacom_transcriptor.paths import BACKUP_DIR
from enacom_transcriptor.runtime import ensure_ffmpeg


def _mktemp_wav() -> str:
    fd, p = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    return p


def render_live_transcript(container, text: str, height: int = 200) -> None:
    safe = html.escape(text or "")
    container.markdown(
        f"""
        <div class="enacom-card">
          <div style="
              height:{height}px;
              overflow:auto;
              white-space:pre-wrap;
              font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
              font-size: 0.85rem;
              line-height: 1.35;
          ">{safe}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _speaker_for(t: float, diar: list[dict] | None) -> str:
    if not diar:
        return ""
    for s in diar:
        if float(s.get("start", 0.0)) <= t <= float(s.get("end", 0.0)):
            return str(s.get("speaker", "") or "")
    return ""


def _make_run_zip(zip_path: str, meta: dict, paths: list[str]) -> str | None:
    try:
        zp = Path(zip_path)
        zp.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(zp), "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            for p in paths:
                if p and os.path.exists(p):
                    zf.write(p, arcname=Path(p).name)

        return str(zp) if zp.exists() else None
    except Exception:
        return None


def run_processing(cfg: dict, sidebar: dict) -> None:
    st.session_state.setdefault("procesado", False)
    st.session_state.setdefault("resultados", [])
    st.session_state.setdefault("lote_result", None)
    st.session_state.setdefault("run_meta", None)
    st.session_state.setdefault("run_package", None)

    audio_files = sidebar.get("audio_files") or []
    query_busqueda = (sidebar.get("query_busqueda") or "").strip()
    coincidencia_parcial = bool(sidebar.get("coincidencia_parcial", True))

    infracciones_cfg = cfg.get("infracciones") or []
    segment_duration = int(cfg.get("segment_duration", 30))
    modo_lote = cfg.get("modo_lote", "Individual")

    export_zip = bool(cfg.get("export_zip", True))
    diarization = bool(cfg.get("diarization", False))

    model_size = (cfg.get("model_size") or "small").strip().lower()
    if model_size not in ("small", "medium"):
        model_size = "small"

    lang = cfg.get("lang")  # None => auto

    if audio_files:
        st.markdown("#### 📊 Panel de control del procesamiento")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Archivos cargados", len(audio_files))
        c2.metric("Modo", modo_lote)
        c3.metric("Duración segmento (s)", segment_duration)
        c4.metric("Términos de infracción", len(infracciones_cfg))

    iniciar = st.button("Iniciar procesamiento de audios", use_container_width=True)
    if iniciar and not audio_files:
        st.warning("Subí al menos un audio antes de iniciar el procesamiento.")
        return
    if not iniciar:
        return

    if not ensure_ffmpeg():
        st.error("No se encontró ffmpeg.exe para Whisper. Instalá imageio-ffmpeg o agregá ffmpeg al PATH.")
        return

    model = load_model_cached(model_size)
    if model is None:
        st.stop()

    st.session_state.resultados = []
    st.session_state.procesado = False
    st.session_state.lote_result = None
    st.session_state.run_meta = None
    st.session_state.run_package = None

    total_files = len(audio_files)

    st.markdown("#### 📊 Progreso global")
    s1, s2 = st.columns([1, 3])
    files_status = s1.empty()
    files_bar = s2.progress(0.0)
    files_status.metric("Archivos procesados", f"0 / {total_files}")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_base = f"corrida_{timestamp}"
    lote_base = f"lote_{timestamp}"

    L_TXT_PATH = str(BACKUP_DIR / f"{lote_base}.txt")
    L_XLSX_PATH = str(BACKUP_DIR / f"{lote_base}.xlsx")
    L_DOCX_PATH = str(BACKUP_DIR / f"{lote_base}.docx")
    RUN_ZIP_PATH = str(BACKUP_DIR / f"{run_base}.zip")

    infracciones_lote: list[dict] = []
    files_info: list[dict] = []
    generated_paths: list[str] = []

    IND_HEADERS = ("Inicio", "Fin", "Hablante", "Texto")
    LOTE_HEADERS = ("Archivo", "Inicio", "Fin", "Hablante", "Texto")

    if modo_lote == "Combinado":
        ensure_excel_file(L_XLSX_PATH, {"Transcripción": LOTE_HEADERS})
        with open(L_TXT_PATH, "w", encoding="utf-8") as f:
            f.write(f"Transcripción consolidada ENACOM — {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
        generated_paths.extend([L_TXT_PATH, L_XLSX_PATH])

    for idx, audio_file in enumerate(audio_files):
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown(
            f"<div class='enacom-card'><b>🎧 Archivo {idx+1}/{total_files}:</b> {audio_file.name}</div>",
            unsafe_allow_html=True,
        )

        suffix = Path(audio_file.name).suffix or ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_file.read())
            tmp_path = tmp.name

        try:
            data, samplerate = sf.read(tmp_path)
        except Exception as e:
            st.error(f"No se pudo leer el audio {audio_file.name}: {e}")
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            files_status.metric("Archivos procesados", f"{idx+1} / {total_files}")
            files_bar.progress((idx + 1) / total_files)
            continue

        total_duration = len(data) / samplerate if samplerate else 0.0
        num_segments = max(1, math.ceil(total_duration / segment_duration))

        diar = None
        if diarization:
            try:
                from enacom_transcriptor.diarization import diarize_audio

                with st.spinner("Diarización (experimental)…"):
                    diar = diarize_audio(data, samplerate)

                if diar is None:
                    st.info("Diarización no disponible. Se continúa sin hablantes.")
            except Exception:
                diar = None
                st.info("Diarización no disponible. Se continúa sin hablantes.")

        col_left, col_right = st.columns([2.3, 1.2], gap="large")

        with col_right:
            with st.container(border=True):
                visualizar_audio(samplerate, data, title=f"📈 Forma de onda — {audio_file.name}")
                audio_player_with_jumps(tmp_path, key_suffix=f"_{idx}")

                st.divider()
                st.markdown("#### 🔎 Coincidencias")
                search_box = st.empty()

        with col_left:
            with st.container(border=True):
                st.markdown("#### Estado")
                st.caption(f"Duración: {hhmmss(int(total_duration))} • Segmentos: {num_segments}")

                chip_c1, chip_c2, chip_c3 = st.columns(3)
                chip_seg = chip_c1.empty()
                chip_speed = chip_c2.empty()
                chip_err = chip_c3.empty()

                progress_bar = st.progress(0.0)
                progress_caption = st.empty()

                st.divider()
                st.markdown("#### 📝 Transcripción en vivo")
                live_box = st.empty()
              

        file_base = os.path.splitext(audio_file.name)[0]
        TXT_PATH = str(BACKUP_DIR / f"{file_base}.txt")
        EXCEL_PATH = str(BACKUP_DIR / f"{file_base}.xlsx")
        DOCX_PATH = str(BACKUP_DIR / f"{file_base}.docx")
        PROGRESS_PATH = str(BACKUP_DIR / f"{file_base}_progreso.pkl")

        ensure_excel_file(EXCEL_PATH, {"Transcripción": IND_HEADERS})

        Path(TXT_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(TXT_PATH, "w", encoding="utf-8") as f:
            f.write(f"Transcripción iniciada: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Archivo: {audio_file.name}\n\n")

        generated_paths.extend([TXT_PATH, EXCEL_PATH])

        if modo_lote == "Combinado":
            with open(L_TXT_PATH, "a", encoding="utf-8") as f:
                f.write("\n\n" + "=" * 70 + "\n")
                f.write(f"ARCHIVO: {audio_file.name}\n")
                f.write("=" * 70 + "\n\n")

        segments_done: list[dict] = []
        infracciones_encontradas: list[dict] = []
        segment_errors = 0

        t0 = time.time()
        chip_seg.metric("Segmento", f"0/{num_segments}")
        chip_speed.metric("Velocidad", "—")
        chip_err.metric("Errores", "0")
        progress_caption.caption("0.0% • 0/0 • ETA 0:00:00")

        for i in range(num_segments):
            start_sec = i * segment_duration
            end_sec = min((i + 1) * segment_duration, total_duration)

            seg_path = _mktemp_wav()
            result = {}

            try:
                seg = data[int(start_sec * samplerate) : int(end_sec * samplerate)]
                sf.write(seg_path, seg, samplerate)

                result = model.transcribe(
                    seg_path,
                    language=lang,
                    verbose=False,
                    fp16=False,
                )

            except Exception as e:
                segment_errors += 1
                st.error(f"Error en el segmento {i+1} del archivo {audio_file.name}: {e}")
                try:
                    with open(PROGRESS_PATH, "wb") as f:
                        pickle.dump({"next_segment": i + 1, "segments_done": segments_done}, f)
                except Exception:
                    pass

            finally:
                try:
                    os.remove(seg_path)
                except Exception:
                    pass

            for s in result.get("segments", []) if isinstance(result, dict) else []:
                s_start = float(s.get("start", 0)) + start_sec
                s_end = float(s.get("end", 0)) + start_sec
                s_text = (s.get("text") or "").strip()
                if not s_text:
                    continue

                mid = (s_start + s_end) / 2.0
                spk = _speaker_for(mid, diar)

                segments_done.append({"start": s_start, "end": s_end, "text": s_text, "speaker": spk})

                tail = segments_done[-60:]
                live_text = "\n".join(
                    [
                        f"[{hhmmss(int(x['start']))} → {hhmmss(int(x['end']))}]"
                        + (f" [{x['speaker']}]" if x.get("speaker") else "")
                        + f" {x['text']}"
                        for x in tail
                    ]
                )
                render_live_transcript(live_box, live_text, height=200)

                if query_busqueda:
                    q = query_busqueda.lower()
                    hits = [x for x in segments_done if q in (x.get("text", "").lower())]
                    if hits:
                        out_lines = []
                        for h in hits[-6:]:
                            ini = hhmmss(int(h.get("start", 0)))
                            fin = hhmmss(int(h.get("end", 0)))
                            out_lines.append(f"- [{ini} → {fin}] {h.get('text','')}")
                        search_box.markdown("#### 🔎 Coincidencias\n" + "\n".join(out_lines))
                    else:
                        search_box.markdown("_Sin coincidencias hasta el momento._")
                else:
                    search_box.empty()

                ini_h = hhmmss(int(s_start))
                fin_h = hhmmss(int(s_end))

                line = f"[{ini_h} → {fin_h}]"
                if spk:
                    line += f" [{spk}]"
                line += f" {s_text}\n"

                with open(TXT_PATH, "a", encoding="utf-8") as f:
                    f.write(line)

                append_to_excel(
                    EXCEL_PATH,
                    [ini_h, fin_h, spk, s_text],
                    sheet_name="Transcripción",
                    headers=IND_HEADERS,
                )

                if modo_lote == "Combinado":
                    with open(L_TXT_PATH, "a", encoding="utf-8") as f:
                        f.write(line)

                    append_to_excel(
                        L_XLSX_PATH,
                        [audio_file.name, ini_h, fin_h, spk, s_text],
                        sheet_name="Transcripción",
                        headers=LOTE_HEADERS,
                    )

                nuevos = detectar_infracciones_en_texto(
                    archivo=audio_file.name,
                    texto=s_text,
                    inicio=ini_h,
                    fin=fin_h,
                    infracciones_cfg=infracciones_cfg,
                    coincidencia_parcial=coincidencia_parcial,
                )
                for inf in nuevos:
                    inf["speaker"] = spk
                infracciones_encontradas.extend(nuevos)

            try:
                with open(PROGRESS_PATH, "wb") as f:
                    pickle.dump({"next_segment": i + 1, "segments_done": segments_done}, f)
            except Exception:
                pass

            percent = (i + 1) / num_segments
            elapsed = time.time() - t0
            seg_rate = (i + 1) / elapsed if elapsed > 0 else 0.0
            eta = int((num_segments - (i + 1)) / seg_rate) if seg_rate > 0 else 0

            chip_seg.metric("Segmento", f"{i+1}/{num_segments}")
            chip_speed.metric("Velocidad", f"{seg_rate:.2f} seg/s" if seg_rate > 0 else "—")
            chip_err.metric("Errores", str(segment_errors))

            progress_bar.progress(percent)
            progress_caption.caption(f"{percent*100:.1f}% • {i+1}/{num_segments} • ETA {hhmmss(eta)}")

        try:
            os.remove(tmp_path)
        except Exception:
            pass
        try:
            os.remove(PROGRESS_PATH)
        except Exception:
            pass

        files_status.metric("Archivos procesados", f"{idx+1} / {total_files}")
        files_bar.progress((idx + 1) / total_files)

        if len(segments_done) == 0 and segment_errors > 0:
            st.error(f"⚠️ {audio_file.name}: no se obtuvo texto (segmentos con error: {segment_errors}).")
        else:
            st.success(f"✅ Transcripción finalizada: {audio_file.name}")

        write_infracciones_excel(EXCEL_PATH, infracciones_encontradas or None)

        with st.expander("⚠️ Infracciones detectadas en este archivo", expanded=False):
            if infracciones_encontradas:
                st.dataframe(pd.DataFrame(infracciones_encontradas), use_container_width=True)
            else:
                st.info("No se detectaron infracciones (según la configuración).")

        word_path = None
        if modo_lote == "Individual":
            meta_ind = {
                "generado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "model_size": model_size,
                "lang": (lang or "auto"),
                "segment_duration": segment_duration,
                "total_files": 1,
                "total_duration_hhmmss": hhmmss(int(total_duration)),
                "diarization": diarization and bool(diar),
                "zip": export_zip,
            }
            try:
                word_path = generar_informe_word(
                    titulo=audio_file.name,
                    docx_out_path=DOCX_PATH,
                    combinado=False,
                    meta=meta_ind,
                    txt_path=TXT_PATH,
                    infracciones=infracciones_encontradas or None,
                )
                if word_path and os.path.exists(word_path):
                    generated_paths.append(word_path)
            except Exception as e:
                st.warning(f"No se pudo generar el DOCX (individual) para {audio_file.name}: {e}")

        files_info.append(
            {
                "archivo": audio_file.name,
                "txt_path": TXT_PATH,
                "duracion_sec": total_duration,
                "duracion_hhmmss": hhmmss(int(total_duration)),
            }
        )
        infracciones_lote.extend(infracciones_encontradas)

        st.session_state.resultados.append(
            {
                "archivo": audio_file.name,
                "file_base": file_base,
                "txt": TXT_PATH if os.path.exists(TXT_PATH) else None,
                "xlsx": EXCEL_PATH if os.path.exists(EXCEL_PATH) else None,
                "docx": word_path if word_path and os.path.exists(word_path) else None,
            }
        )

    total_dur = sum(float(i.get("duracion_sec", 0.0)) for i in files_info) if files_info else 0.0
    archivos_con_inf = len({i.get("archivo") for i in infracciones_lote}) if infracciones_lote else 0

    run_meta = {
        "modo": modo_lote,
        "generado": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model_size": model_size,
        "lang": (lang or "auto"),
        "segment_duration": segment_duration,
        "total_files": len(files_info),
        "total_duration_hhmmss": hhmmss(int(total_dur)),
        "infracciones_total": len(infracciones_lote),
        "archivos_con_infracciones": archivos_con_inf,
        "diarization": diarization,
        "zip": export_zip,
    }
    st.session_state.run_meta = run_meta

    if modo_lote == "Combinado" and audio_files:
        write_infracciones_excel(L_XLSX_PATH, infracciones_lote or None)

        meta_lote = {
            **run_meta,
            "total_files": len(files_info),
            "total_duration_hhmmss": hhmmss(int(total_dur)),
        }

        word_path_lote = None
        try:
            word_path_lote = generar_informe_word(
                titulo=lote_base,
                docx_out_path=L_DOCX_PATH,
                combinado=True,
                meta=meta_lote,
                infracciones=infracciones_lote or None,
                files_info=files_info,
            )
            if word_path_lote and os.path.exists(word_path_lote):
                generated_paths.append(word_path_lote)
        except Exception as e:
            st.warning(f"No se pudo generar el DOCX (lote): {e}")

        st.session_state.lote_result = {
            "archivo": f"LOTE — {lote_base}",
            "file_base": lote_base,
            "txt": L_TXT_PATH if os.path.exists(L_TXT_PATH) else None,
            "xlsx": L_XLSX_PATH if os.path.exists(L_XLSX_PATH) else None,
            "docx": word_path_lote if word_path_lote and os.path.exists(word_path_lote) else None,
        }

        st.success("🎉 Lote completo procesado.")

    if export_zip:
        generated_paths = [p for p in generated_paths if p and os.path.exists(p)]
        generated_paths = list(dict.fromkeys(generated_paths))
        zip_path = _make_run_zip(RUN_ZIP_PATH, run_meta, generated_paths)
        if zip_path and os.path.exists(zip_path):
            st.session_state.run_package = zip_path
            st.success("📦 Paquete ZIP de archivos generado.")

    st.session_state.procesado = True
