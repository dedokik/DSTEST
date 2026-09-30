"""Загрузка dataset.json и catalog.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_dataset(path: str | Path | None = None) -> dict[str, Any]:
    """Загрузить тестовый датасет."""
    p = Path(path) if path else ROOT / "dataset.json"
    return json.loads(p.read_text(encoding="utf-8"))


def load_catalog(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Загрузить справочник товаров."""
    p = Path(path) if path else ROOT / "catalog.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return list(data)


def catalog_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Справочник в виде словаря sku -> запись."""
    return {i["sku"]: i for i in items}
