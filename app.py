"""
app.py — Streamlit app for the dbt ER Diagram Viewer.

Usage:
    streamlit run app.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
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

# ── Sidebar ───────────────────────────────────────────────────────────────────
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

# ── Sidebar — folder filter ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.subheader("Filter by folder")

    visible: set[str] = set()

    if models:
        # Group models by folder
        folders: dict[str, list[str]] = defaultdict(list)
        for m in models:
            folders[m.folder].append(m.name)

        col1, col2 = st.columns(2)
        if col1.button("All", use_container_width=True):
            for folder in folders:
                st.session_state[f"folder_{folder}"] = True
        if col2.button("None", use_container_width=True):
            for folder in folders:
                st.session_state[f"folder_{folder}"] = False

        for folder in sorted(folders):
            label = f"📁 {folder} ({len(folders[folder])})"
            checked = st.checkbox(
                label,
                value=st.session_state.get(f"folder_{folder}", True),
                key=f"folder_{folder}",
            )
            if checked:
                visible.update(folders[folder])

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("📦 dbt ER Diagram")

if not st.session_state.get("path_ok", True):
    st.error(f"Directory not found: `{project_path}`")
elif not models:
    st.warning("No dbt models found. Make sure the directory contains `*.yml` files with a `models:` key.")
else:
    st.caption(
        f"Found **{len(models)}** model(s) — showing **{len(visible)}** selected."
    )

    if not visible:
        st.info("Select at least one folder in the sidebar to display the diagram.")
    else:
        html_content = build_network(models, visible_models=visible)
        components.html(html_content, height=780, scrolling=False)

    # ── Raw model details ─────────────────────────────────────────────────────
    with st.expander("🔍 Raw model details", expanded=False):
        import pandas as pd

        for model in sorted(models, key=lambda m: (m.folder, m.name)):
            st.markdown(f"### `{model.name}` <small>— {model.folder}</small>", unsafe_allow_html=True)
            if model.description:
                st.markdown(f"*{model.description}*")

            if model.columns:
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
                            "FK →": fk_info,
                            "Description": col.description,
                        }
                    )
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.write("*No columns defined.*")

