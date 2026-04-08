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

# ── Folder-tree helpers ───────────────────────────────────────────────────────

def _split(folder_path: str) -> list[str]:
    """Split a folder path into parts regardless of separator."""
    return folder_path.replace("\\", "/").split("/")


def _make_tree(folder_paths: list[str]) -> dict:
    """Build a nested dict from folder paths. Leaves are empty dicts."""
    tree: dict = {}
    for fp in folder_paths:
        node = tree
        for part in _split(fp):
            node = node.setdefault(part, {})
    return tree


def _fkey(parts: list[str]) -> str:
    """Stable session-state key for a folder node."""
    return "folder__" + "__".join(parts)


def _folder_toggle(folder_key: str, model_names: list[str]) -> None:
    """on_change callback: push folder checkbox value down to its models."""
    val = st.session_state[folder_key]
    for n in model_names:
        st.session_state[f"mdl_{n}"] = val


def _all_models_under(parts: list[str], folders_by_path: dict[str, list[str]]) -> list[str]:
    """Collect every model name under a folder node (including descendants)."""
    prefix = "/".join(parts)
    names: list[str] = []
    for fp, ms in folders_by_path.items():
        norm = fp.replace("\\", "/")
        if norm == prefix or norm.startswith(prefix + "/"):
            names.extend(ms)
    return names


def _render_tree(
    node: dict,
    path_parts: list[str],
    folders_by_path: dict[str, list[str]],
    visible: set[str],
    depth: int = 0,
) -> None:
    """Recursively render folder checkboxes + model checkboxes with indentation."""
    STEP = 0.07  # indent ratio per depth level

    for seg in sorted(node):
        child_parts = path_parts + [seg]
        child_key_norm = "/".join(child_parts)

        # Models that live directly in this folder
        direct_models = sorted(
            folders_by_path.get(child_key_norm)
            or folders_by_path.get("\\".join(child_parts))
            or []
        )
        # All models under this subtree (for folder toggle propagation)
        all_models = sorted(_all_models_under(child_parts, folders_by_path))

        fkey = _fkey(child_parts)
        if fkey not in st.session_state:
            st.session_state[fkey] = True

        label = f"📁 {seg}" + (f" ({len(all_models)})" if all_models else "")

        # Indent via columns (depth > 0 only)
        if depth > 0:
            _, cont = st.columns([depth * STEP, 1 - depth * STEP])
        else:
            cont = st.sidebar

        cont.checkbox(
            label,
            key=fkey,
            on_change=_folder_toggle,
            args=(fkey, all_models),
        )

        # Individual model checkboxes under this folder
        if direct_models:
            m_depth = depth + 1
            for name in direct_models:
                _, mc = st.columns([m_depth * STEP, 1 - m_depth * STEP])
                with mc:
                    if st.checkbox(
                        name,
                        key=f"mdl_{name}",
                        value=st.session_state.get(f"mdl_{name}", True),
                    ):
                        visible.add(name)

        # Recurse into sub-folders
        if node[seg]:
            _render_tree(node[seg], child_parts, folders_by_path, visible, depth + 1)


# ── Sidebar — path input ──────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    st.markdown("---")

    default_path = str(Path.cwd())
    project_path = st.text_input(
        "dbt project directory",
        value=st.session_state.get("loaded_path", default_path),
        help="Absolute path to the root of your dbt project. Press Enter or click Reload.",
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

# ── Sidebar — two-level filter ────────────────────────────────────────────────
with st.sidebar:
    st.markdown("---")
    st.subheader("Filter models")

    visible: set[str] = set()

    if models:
        folders_by_path: dict[str, list[str]] = defaultdict(list)
        for m in models:
            folders_by_path[m.folder.replace("\\", "/")].append(m.name)

        all_model_names = [m.name for m in models]

        col1, col2 = st.columns(2)
        if col1.button("All", use_container_width=True):
            for n in all_model_names:
                st.session_state[f"mdl_{n}"] = True
            # Also update every folder key so checkboxes reflect state
            for fp in folders_by_path:
                for depth in range(1, len(_split(fp)) + 1):
                    st.session_state[_fkey(_split(fp)[:depth])] = True
        if col2.button("None", use_container_width=True):
            for n in all_model_names:
                st.session_state[f"mdl_{n}"] = False
            for fp in folders_by_path:
                for depth in range(1, len(_split(fp)) + 1):
                    st.session_state[_fkey(_split(fp)[:depth])] = False

        tree = _make_tree(list(folders_by_path.keys()))
        _render_tree(tree, [], folders_by_path, visible, depth=0)

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
            st.markdown(
                f"### `{model.name}` <small>— {model.folder}</small>",
                unsafe_allow_html=True,
            )
            if model.description:
                st.markdown(f"*{model.description}*")

            if model.columns:
                rows = []
                for col in model.columns:
                    fk_info = (
                        f"{col.foreign_key.to_model}.{col.foreign_key.to_column}"
                        if col.foreign_key else ""
                    )
                    rows.append({
                        "Column": col.name,
                        "Type": col.data_type or "",
                        "PK": "🔑" if col.is_primary_key else "",
                        "FK →": fk_info,
                        "Description": col.description,
                    })
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            else:
                st.write("*No columns defined.*")



