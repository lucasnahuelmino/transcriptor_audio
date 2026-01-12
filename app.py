from __future__ import annotations

from enacom_transcriptor.runtime import configure_runtime
configure_runtime()

from enacom_transcriptor.ui import (
    set_page,
    load_css,
    render_header,
    render_config,
    render_sidebar,
    render_downloads,
)
from enacom_transcriptor.processing import run_processing


def main() -> None:
    set_page()
    load_css()
    render_header()

    cfg = render_config()
    sidebar = render_sidebar()

    run_processing(cfg, sidebar)

    render_downloads()


if __name__ == "__main__":
    main()
