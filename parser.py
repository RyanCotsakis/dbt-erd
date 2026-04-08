"""
parser.py — Parse dbt YAML schema files into structured model objects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ForeignKey:
    to_model: str  # referenced model name
    to_column: str  # referenced column


@dataclass
class Column:
    name: str
    data_type: Optional[str] = None
    description: str = ""
    tests: list[str] = field(default_factory=list)
    is_primary_key: bool = False
    foreign_key: Optional[ForeignKey] = None


@dataclass
class Model:
    name: str
    description: str = ""
    columns: list[Column] = field(default_factory=list)
    source_file: str = ""
    folder: str = ""  # relative folder path from the models root


def _extract_ref(ref_str: str) -> str:
    """Extract model name from ref('model_name') or 'model_name'."""
    match = re.search(r"ref\(['\"](.+?)['\"]\)", ref_str)
    if match:
        return match.group(1)
    return ref_str.strip().strip("'\"")


def _parse_column(col_data: dict) -> Column:
    col = Column(
        name=col_data.get("name", ""),
        data_type=col_data.get("data_type") or col_data.get("dtype"),
        description=col_data.get("description", ""),
    )

    # dbt ≥1.6 uses "data_tests"; older versions use "tests"
    raw_tests = col_data.get("data_tests") or col_data.get("tests") or []
    test_names: list[str] = []
    fk: Optional[ForeignKey] = None

    for t in raw_tests:
        if isinstance(t, str):
            test_names.append(t)
        elif isinstance(t, dict):
            for test_name, test_cfg in t.items():
                test_names.append(test_name)
                if test_name == "relationships" and isinstance(test_cfg, dict):
                    # Support both direct keys and keys nested under "arguments:"
                    cfg = test_cfg.get("arguments", test_cfg)
                    to_raw = cfg.get("to", "")
                    to_field = cfg.get("field", "")
                    if to_raw or to_field:
                        fk = ForeignKey(
                            to_model=_extract_ref(str(to_raw)),
                            to_column=str(to_field),
                        )

    col.tests = test_names
    col.foreign_key = fk

    # Detect primary key
    has_unique = "unique" in test_names
    has_not_null = "not_null" in test_names
    desc_lower = col.description.lower()
    col.is_primary_key = (has_unique and has_not_null) or "primary key" in desc_lower

    return col


def _parse_model(model_data: dict, source_file: str, folder: str) -> Model:
    model = Model(
        name=model_data.get("name", "unknown"),
        description=model_data.get("description", ""),
        source_file=source_file,
        folder=folder,
    )

    for col_data in model_data.get("columns", []):
        model.columns.append(_parse_column(col_data))

    return model


def parse_directory(directory: str | Path) -> list[Model]:
    """
    Recursively search the `models/` subdirectory (or the given directory if no
    `models/` subfolder exists) for *.yml files and parse dbt model definitions.
    """
    root = Path(directory)
    models_root = root / "models"
    search_root = models_root if models_root.is_dir() else root
    models: list[Model] = []

    for yml_file in sorted(search_root.rglob("*.yml")):
        try:
            with open(yml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        # Folder label: relative path of the file's directory from search_root
        rel_folder = str(yml_file.parent.relative_to(search_root))
        if rel_folder == ".":
            rel_folder = "(root)"

        for model_data in data.get("models", []):
            if isinstance(model_data, dict):
                models.append(
                    _parse_model(
                        model_data,
                        source_file=str(yml_file.relative_to(search_root)),
                        folder=rel_folder,
                    )
                )

    return models
