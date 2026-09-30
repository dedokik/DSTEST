"""Нормализация свободных записей движения товара (Часть 1)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog.json"

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_OPERATION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("receipt", ["приход"]),
    ("consume", ["расход"]),
    ("writeoff", ["списание", "списани", "истёк срок", "истек срок", "просроч"]),
    ("return", ["возврат"]),
    ("correction", ["корректировка", "коррекция", "корректиров"]),
]

# SKU вида OIL-001 / oil 001 / WRAP 030
_SKU_RE = re.compile(r"\b([A-Za-z]{2,5})[-\s]?(\d{3})\b")
_BATCH_RE = re.compile(r"\b(B-[A-Za-z0-9][A-Za-z0-9\-]*)\b", re.IGNORECASE)
_DOC_CANDIDATE_RE = re.compile(r"\b([A-ЯA-Z]{1,4}-?\d{2,6})\b")
_LOCATION_MS_RE = re.compile(r"\bMS[-\s]?0?(\d)\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DOT_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b")
_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_TEXT_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})",
    re.IGNORECASE,
)
# "2 канистры по 5 л" / "4 уп. по 50 пар"
_MULTI_QTY_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:канистр\w*|уп\w*\.?|упак\w*|короб\w*|пачк\w*|бут\w*|флак\w*)?\s*по\s*(\d+(?:[.,]\d+)?)\s*(мл|л|г\.?|кг|пар\w*|шт\.?)\b",
    re.IGNORECASE,
)
_SIMPLE_QTY_RE = re.compile(
    # Знак минуса учитываем только если он прилеплен к числу (−120, -5).
    # Разделительное тире " — 450" минусом не является.
    r"(?P<sign>[\-−]?)(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>мл|л|г\.?|кг|пар\w*|шт\.?)\b",
    re.IGNORECASE,
)

# Сопоставление по названию (когда SKU-кода нет, напр. M8).
_NAME_TO_SKU: list[tuple[str, list[str]]] = [
    ("CONS-051", ["тапоч", "тапочек"]),
    ("CONS-052", ["шапоч"]),
    ("SCRB-020", ["скраб"]),
    ("WRAP-030", ["альгинат", "обёртыван", "обертыван", "маска для об"]),
    ("OIL-002", ["ароматическ", "лаванд"]),
    ("OIL-001", ["базов", "миндаль"]),
]


def _load_catalog() -> list[dict[str, Any]]:
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def _catalog_unit(sku: str | None) -> str | None:
    if not sku:
        return None
    for item in _load_catalog():
        if item.get("sku") == sku:
            return str(item.get("unit"))
    return None


def _parse_number(raw: str) -> float:
    return float(raw.replace(",", ".").replace("−", "-").replace("–", "-").replace("—", "-"))


def _parse_date(text: str) -> str | None:
    """Разобрать дату в ISO-строку YYYY-MM-DD, иначе None."""
    m = _ISO_DATE_RE.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _TEXT_DATE_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _MONTHS[m.group(2).lower()]
        year = int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    m = _DOT_DATE_RE.search(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"
    m = _SLASH_DATE_RE.search(text)
    if m:
        # Российский контекст: DD/MM/YY (03/06/26 -> 2026-06-03).
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _parse_operation(text: str) -> str | None:
    low = text.lower()
    for op, keywords in _OPERATION_KEYWORDS:
        if any(k in low for k in keywords):
            return op
    return None


def _parse_sku(text: str) -> str | None:
    catalog_skus = {item.get("sku") for item in _load_catalog()}
    for m in _SKU_RE.finditer(text):
        candidate = f"{m.group(1).upper()}-{m.group(2)}"
        # Проверяем по справочнику, чтобы не принять НК-345 за SKU.
        if candidate in catalog_skus:
            return candidate
        # WRAP 030 без дефиса тоже валиден, если есть в справочнике.
        # Если код не из справочника — пропускаем (защита от НК-345).
    # Fallback: поиск по названию позиции.
    # Голое «масло» без кода и уточнения не маппим (возвращаем None),
    # чтобы не выдумывать позицию (требование заказчика).
    low = text.lower()
    for sku, keywords in _NAME_TO_SKU:
        if any(k in low for k in keywords):
            return sku
    return None


def _parse_location(text: str) -> str | None:
    m = _LOCATION_MS_RE.search(text)
    if m:
        return f"MS-0{m.group(1)}"
    low = text.lower()
    if "красная поляна" in low or "красн" in low and "полян" in low:
        return "Красная Поляна"
    if "сочи" in low:
        return "Сочи"
    return None


def _normalize_unit(raw: str) -> str:
    r = raw.lower().rstrip(".")
    if r.startswith("мл"):
        return "мл"
    if r.startswith("кг") or r == "кг":
        return "кг"
    if r == "г":
        return "г"
    if r.startswith("пар"):
        return "пар"
    if r.startswith("шт"):
        return "шт"
    if r == "л":
        return "л"
    return r


def _to_base_qty(qty: float, raw_unit: str, sku: str | None) -> tuple[float, str | None]:
    """Перевести количество в базовую единицу позиции из справочника."""
    base = _catalog_unit(sku)
    u = _normalize_unit(raw_unit)
    if base is None:
        return qty, (u if u else None)
    b = base.lower()
    if b == "л" and u == "мл":
        return qty / 1000.0, base
    if b == "кг" and u == "г":
        return qty / 1000.0, base
    return qty, base


def _parse_qty_unit(text: str, sku: str | None) -> tuple[float | None, str | None]:
    norm = text.replace("−", "-").replace("–", "-").replace("—", "-")
    m = _MULTI_QTY_RE.search(norm)
    if m:
        count = _parse_number(m.group(1))
        per = _parse_number(m.group(2))
        raw_unit = m.group(3)
        qty, base_unit = _to_base_qty(count * per, raw_unit, sku)
        return qty, base_unit
    matches = list(_SIMPLE_QTY_RE.finditer(norm))
    if not matches:
        return None, None
    # Берём последнее совпадение с единицей (защита от случайных чисел в датах/доках).
    m = matches[-1]
    sign = -1 if m.group("sign") and "-" in m.group("sign") else 1
    qty_raw = sign * _parse_number(m.group("num"))
    qty, base_unit = _to_base_qty(qty_raw, m.group("unit"), sku)
    return qty, base_unit


def _parse_batch(text: str) -> str | None:
    m = _BATCH_RE.search(text)
    if m:
        return m.group(1).upper()
    return None


def _parse_doc_no(text: str, sku: str | None, batch: str | None) -> str | None:
    for m in _DOC_CANDIDATE_RE.finditer(text):
        cand = m.group(1).upper()
        if batch and cand == batch.upper():
            continue
        if sku and cand == sku.upper():
            continue
        if cand.startswith("B-"):
            continue
        # Коды локаций (MS-01/MS-02) — не документы.
        if re.fullmatch(r"MS-?0?\d", cand, re.IGNORECASE):
            continue
        return cand
    return None


def normalize_movement(text: str) -> dict:
    """Нормализовать свободную запись движения товара.

    Args:
        text: исходная строка (напр. "05.03.2026 MS-01 приход OIL-001, ...").

    Returns:
        Словарь с ключами date, sku, location, operation, qty, unit, batch, doc_no.
        Ненайденные поля равны None. qty приведено к базовой единице из catalog.json.
    """
    date = _parse_date(text)
    operation = _parse_operation(text)
    sku = _parse_sku(text)
    location = _parse_location(text)
    qty, unit = _parse_qty_unit(text, sku)
    batch = _parse_batch(text)
    doc_no = _parse_doc_no(text, sku, batch)
    return {
        "date": date,
        "sku": sku,
        "location": location,
        "operation": operation,
        "qty": qty,
        "unit": unit,
        "batch": batch,
        "doc_no": doc_no,
    }
