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

sys.path.insert(0, str(Path(__file__).parent))

from parser import parse_directory
from renderer import build_network

st.set_page_config(
    page_title="dbt ER Diagram",
    page_icon="📦",
    layout="wide",
)

# ── Sidebar — path input ──────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("---")

    default_path = str(Path.cwd())
    project_path = st.text_input(
        "dbt project directory",
        value=st.session_state.get("project_path", default_path),
        help="Absolute path to the root of your dbt project. Press Enter or click Reload.",
        key="path_input",
    )

    reload = st.button("🔄 Reload", use_container_width=True)

# ── Reload when path changes (Enter) or button clicked ───────────────────────
path_changed = project_path != st.session_state.get("loaded_path")
if "models" not in st.session_state or reload or path_changed:
    path = Path(project_path)
    if path.is_dir():
        st.session_state["models"] = parse_directory(path)
        st.session_state["path_ok"] = True
    else:
        st.session_state["models"] = []
        st.session_state["path_ok"] = False
    st.session_state["loaded_path"] = project_path

models = st.session_state.get("models", [])

# ── Sidebar — two-level filter (folder → individual models) ──────────────────
with st.sidebar:
    st.markdown("---")
    st.subheader("Filter models")

    visible: set[str] = set()

    if models:
        folders: dict[str, list[str]] = defaultdict(list)
        for m in models:
            folders[m.folder].append(m.name)

        col1, col2 = st.columns(2)
        if col1.button("All", use_container_width=True):
            for names in folders.values():
                for n in names:
                    st.session_state[f"mdl_{n}"] = True
        if col2.button("None", use_container_width=True):
            for names in folders.values():
                for n in names:
                    st.session_state[f"mdl_{n}"] = False

        for folder in sorted(folders):
            model_names = sorted(folders[folder])

            # Folder-level toggle: checks/unchecks all models in the folder
            all_on  = all(st.session_state.get(f"mdl_{n}", True) for n in model_names)
            some_on = any(st.session_state.get(f"mdl_{n}", True) for n in model_names)
            folder_val = st.checkbox(
                f"📁 {folder} ({len(model_names)})",
                value=all_on,
                key=f"folder_{folder}",
            )
            # Propagate folder toggle to individual models when it changes
            prev_folder_val = st.session_state.get(f"folder_prev_{folder}", all_on)
            if folder_val != prev_folder_val:
                for n in model_names:
                    st.session_state[f"mdl_{n}"] = folder_val
            st.session_state[f"folder_prev_{folder}"] = folder_val

            # Individual model checkboxes, indented
            for name in model_names:
                checked = st.checkbox(
                    f"  {name}",
                    value=st.session_state.get(f"mdl_{name}", True),
                    key=f"mdl_{name}",
                )
                if checked:
                    visible.add(name)

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("📦 dbt ER Diagram")

if not st.session_state.get("path_ok", True):
    st.error(f"Directory not found: `{project_path}`")
elif not models:
    st.warning("No dbt models found. Make sure the directory contains `*.yml` files with a `models:` key.")
else:
    st.caption(f"Found **{len(models)}** model(s) — showing **{len(visible)}** selected.")

    if not visible:
        st.info("Select at least one model in the sidebar to display the diagram.")
    else:
        html_content = build_network(models, visible_models=visible)
        components.html(html_content, height=780, scrolling=False)

    with st.expander("🔍 Raw model details", expanded=False):
        import pandas as pd

        for model in sorted(models, key=lambda m: (m.folder, m.name)):
            st.markdown(f"### `{model.name}` <small>— {model.folder}</small>", unsafe_allow_html=True)
            if model.description:
                st.markdown(f"*{model.description}*")

            if model.columns:
                rows = []
                for col in model.columns:
                    fk_info = f"{col.foreign_key.to_model}.{col.foreign_key.to_column}" if col.foreign_key else ""
                    rows.append({
                        "Column": col.name,
                        "Type": col.data_type or "",
                        "PK": "🔑" if col.is_primary_key else "",
                        "FK →": fk_info,
                        "Description": col.description,
                    })
                st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
            else:
                st.write("*No columns defined.*")


