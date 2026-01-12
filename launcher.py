from __future__ import annotations

import os
import sys
import time
import webbrowser

def _app_path() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "app.py")

def main() -> None:

    from streamlit.web import cli as stcli

    port = "8501"
    url = f"http://localhost:{port}"


    def _open_browser():
        time.sleep(0.8)
        webbrowser.open(url)

    import threading
    threading.Thread(target=_open_browser, daemon=True).start()

    sys.argv = [
        "streamlit",
        "run",
        _app_path(),
        "--server.headless=true",
        f"--server.port={port}",
    ]
    raise SystemExit(stcli.main())

if __name__ == "__main__":
    main()
