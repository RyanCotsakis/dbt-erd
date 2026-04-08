"""
app.py — Streamlit app for the dbt ER Diagram Viewer.

Usage:
    streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Allow running from the project directory
sys.path.insert(0, str(Path(__file__).parent))

from parser import parse_directory
from renderer import build_network

st.set_page_config(
    page_title="dbt ER Diagram",
    page_icon="📦",
    layout="wide",
)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("---")

    default_path = str(Path.cwd())
    project_path = st.text_input(
        "dbt project directory",
        value=default_path,
        help="Absolute or relative path to the root of your dbt project.",
    )

    reload = st.button("🔄 Reload", use_container_width=True)

# ── Session state ─────────────────────────────────────────────────────────────
if "models" not in st.session_state or reload:
    path = Path(project_path)
    if path.is_dir():
        st.session_state["models"] = parse_directory(path)
        st.session_state["path_ok"] = True
    else:
        st.session_state["models"] = []
        st.session_state["path_ok"] = False

models = st.session_state.get("models", [])

# ── Sidebar — model filter ────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.subheader("Filter models")

    if models:
        all_names = sorted(m.name for m in models)
        selected = {}
        if st.button("Select all", use_container_width=True):
            for n in all_names:
                st.session_state[f"chk_{n}"] = True
        if st.button("Deselect all", use_container_width=True):
            for n in all_names:
                st.session_state[f"chk_{n}"] = False

        for name in all_names:
            selected[name] = st.checkbox(name, value=st.session_state.get(f"chk_{name}", True), key=f"chk_{name}")

        visible = {n for n, v in selected.items() if v}
    else:
        visible = set()

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("📦 dbt ER Diagram")

if not st.session_state.get("path_ok", True):
    st.error(f"Directory not found: `{project_path}`")
elif not models:
    st.warning("No dbt models found. Make sure the directory contains `*.yml` files with a `models:` key.")
else:
    st.caption(
        f"Found **{len(models)}** model(s) in `{project_path}` — "
        f"showing **{len(visible)}** selected."
    )

    if not visible:
        st.info("Select at least one model in the sidebar to display the diagram.")
    else:
        html_content = build_network(models, visible_models=visible)
        components.html(html_content, height=780, scrolling=False)

    # ── Raw model details ─────────────────────────────────────────────────────
    with st.expander("🔍 Raw model details", expanded=False):
        for model in models:
            st.markdown(f"### `{model.name}`")
            if model.description:
                st.markdown(f"*{model.description}*")
            st.caption(f"Source: `{model.source_file}`")

            if model.columns:
                import pandas as pd

                rows = []
                for col in model.columns:
                    fk_info = ""
                    if col.foreign_key:
                        fk_info = f"{col.foreign_key.to_model}.{col.foreign_key.to_column}"
                    rows.append(
                        {
                            "Column": col.name,
                            "Type": col.data_type or "",
                            "PK": "🔑" if col.is_primary_key else "",
                            "FK → ": fk_info,
                            "Tests": ", ".join(col.tests),
                            "Description": col.description,
                        }
                    )
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.write("*No columns defined.*")
