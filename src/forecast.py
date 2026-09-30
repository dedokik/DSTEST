"""Прогноз потребности и рекомендация закупки (Часть 2, без LLM)."""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from .config import (
    CONFIDENCE_BASE,
    CONFIDENCE_CV_PENALTY,
    CONFIDENCE_MIN,
    CONFIDENCE_MISSING_PENALTY,
    CONFIDENCE_OUTLIER_PENALTY,
    CONFIDENCE_SHORT_HISTORY_PENALTY,
    MIN_WEEKS_FOR_CONFIDENCE,
    NEEDS_CLARIFICATION_THRESHOLD,
    OUTLIER_JUMP_RATIO,
    RECENT_WEEKS_FOR_AVG,
)

CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog.json"


def _load_catalog_map() -> dict[str, dict[str, Any]]:
    try:
        items = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {i["sku"]: i for i in items}


def _clean_series(weekly: list[float | None]) -> tuple[list[float], float]:
    """Заменить пропуски медианой; вернуть (чистый ряд, доля пропусков)."""
    present = [float(x) for x in weekly if x is not None]
    if not present:
        return [], 1.0
    median = statistics.median(present)
    missing_ratio = sum(1 for x in weekly if x is None) / len(weekly)
    cleaned = [float(x) if x is not None else median for x in weekly]
    return cleaned, missing_ratio


def _detect_level_shift(cleaned: list[float]) -> bool:
    """Сдвиг уровня: медиана последних 4 недель >= 2x медианы первых 8 недель."""
    if len(cleaned) < RECENT_WEEKS_FOR_AVG + 4:
        return False
    early = cleaned[:-RECENT_WEEKS_FOR_AVG]
    recent = cleaned[-RECENT_WEEKS_FOR_AVG:]
    med_early = statistics.median(early)
    med_recent = statistics.median(recent)
    if med_early <= 0:
        return False
    return (med_recent / med_early) >= OUTLIER_JUMP_RATIO


def _confidence(n_weeks: int, cv: float, missing_ratio: float, shifted: bool) -> float:
    conf = CONFIDENCE_BASE
    conf -= cv * CONFIDENCE_CV_PENALTY
    conf -= missing_ratio * CONFIDENCE_MISSING_PENALTY
    if n_weeks < MIN_WEEKS_FOR_CONFIDENCE:
        conf -= CONFIDENCE_SHORT_HISTORY_PENALTY
    if shifted:
        conf -= CONFIDENCE_OUTLIER_PENALTY
    return max(CONFIDENCE_MIN, min(0.99, conf))


def _round_to_pack(need: float, pack_size: float, min_order: float) -> float:
    """Округлить потребность вверх до кратности упаковки и мин. партии."""
    if need <= 0:
        return 0.0
    packs = math.ceil(need / pack_size)
    qty = packs * pack_size
    if qty < min_order:
        qty = math.ceil(min_order / pack_size) * pack_size
    return float(qty)


def forecast_demand(history: dict, sku: str, horizon_days: int, params: dict) -> dict:
    """Рассчитать прогноз потребности и рекомендацию закупки.

    Args:
        history: словарь с ключами as_of, weekly_consumption, current_stock,
            incoming_qty (формат dataset.json). Допускается плоский вариант
            {"weekly": [...], "stock": x, "incoming": y, "as_of": ...}.
        sku: код позиции из справочника.
        horizon_days: горизонт прогноза в днях.
        params: доп. параметры; может содержать "catalog" (dict sku->entry)
            и "as_of" (переопределение даты).

    Returns:
        Словарь с ключами avg_daily_consumption, forecast_demand, current_stock,
        incoming_qty, safety_stock, reorder_point, recommended_qty,
        estimated_cost, stockout_date, confidence, explanation.
        Через params можно передать "load_factor" (напр. 1.2 при +20% загрузки):
        масштабирует среднесуточный расход до расчёта потребности и запасов.
    """
    catalog = (params or {}).get("catalog") or _load_catalog_map()
    if sku not in catalog:
        raise ValueError(f"SKU {sku!r} нет в справочнике")
    entry = catalog[sku]

    weekly_raw: list[float | None] = []
    if "weekly_consumption" in history and isinstance(history["weekly_consumption"], dict):
        weekly_raw = list(history["weekly_consumption"].get(sku, []))
    elif "weekly" in history:
        weekly_raw = list(history["weekly"])
    else:
        raise ValueError("history не содержит weekly_consumption")

    def _stock(mapping: dict, default: float = 0.0) -> float:
        return float(mapping.get(sku, default) or 0.0)

    if "current_stock" in history and isinstance(history["current_stock"], dict):
        stock = _stock(history["current_stock"])
    else:
        stock = float(history.get("stock", 0.0) or 0.0)
    if "incoming_qty" in history and isinstance(history["incoming_qty"], dict):
        incoming = _stock(history["incoming_qty"])
    else:
        incoming = float(history.get("incoming", 0.0) or 0.0)

    as_of_str: str = (params or {}).get("as_of") or history.get("as_of") or str(date.today())
    as_of = date.fromisoformat(str(as_of_str))

    cleaned, missing_ratio = _clean_series(weekly_raw)
    n_weeks = len([x for x in weekly_raw if x is not None])
    shifted = _detect_level_shift(cleaned) if cleaned else False

    # Метод: среднее последних RECENT_WEEKS_FOR_AVG недель (устойчиво к тренду
    # и сдвигу уровня; обоснование в RESULTS.md). Пропуски импутированы медианой.
    recent = cleaned[-RECENT_WEEKS_FOR_AVG:] if len(cleaned) >= RECENT_WEEKS_FOR_AVG else cleaned
    avg_weekly = float(statistics.fmean(recent)) if recent else 0.0
    load_factor = float((params or {}).get("load_factor", 1.0) or 1.0)
    avg_daily = avg_weekly / 7.0 * load_factor
    forecast = avg_daily * float(horizon_days)

    safety_days = float(entry.get("safety_stock_days", 14))
    lead_days = float(entry.get("lead_time_days", 7))
    price = float(entry.get("price", 0.0))
    pack_size = float(entry.get("pack_size", 1))
    min_order = float(entry.get("min_order_qty", 1))
    unit = str(entry.get("unit", ""))

    safety_stock = avg_daily * safety_days
    reorder_point = avg_daily * lead_days + safety_stock

    need = forecast + safety_stock - stock - incoming
    recommended = _round_to_pack(need, pack_size, min_order)
    estimated_cost = round(recommended * price, 2)

    if avg_daily > 0:
        days_left = (stock + incoming) / avg_daily
        stockout = as_of + timedelta(days=int(math.floor(days_left)))
        stockout_str: str | None = stockout.isoformat()
    else:
        days_left = float("inf")
        stockout_str = None

    mean_all = statistics.fmean(cleaned) if cleaned else 0.0
    stdev = statistics.pstdev(cleaned) if len(cleaned) > 1 else 0.0
    cv = (stdev / mean_all) if mean_all > 0 else 0.0
    confidence = _confidence(n_weeks, cv, missing_ratio, shifted)

    needs_clar = confidence < NEEDS_CLARIFICATION_THRESHOLD
    clar_mark = " [требуется уточнение]" if needs_clar else ""
    explanation = (
        f"{sku}: средний расход {avg_daily:.2f} {unit}/день "
        f"(среднее последних {RECENT_WEEKS_FOR_AVG} недель: {avg_weekly:.2f} {unit}/нед). "
        f"Прогноз на {horizon_days} дн.: {forecast:.1f} {unit}. "
        f"Страховой запас ({safety_days:.0f} дн.): {safety_stock:.1f}. "
        f"Остаток {stock:.1f} + в пути {incoming:.1f}. "
        f"Потребность {need:.1f} округлена до упаковки {pack_size:g} (мин. {min_order:g}): {recommended:g}. "
        f"Цена {price:.2f} → стоимость {estimated_cost:.2f}.{clar_mark}"
    )
    if shifted:
        explanation += " Учтен сдвиг уровня спроса (последний месяц >2x): взят новый уровень."
    if missing_ratio > 0:
        explanation += f" Пропуски ({missing_ratio:.0%}) заменены медианой."
    if load_factor != 1.0:
        explanation += f" Применена поправка на загрузку x{load_factor:g}."

    return {
        "avg_daily_consumption": round(avg_daily, 4),
        "forecast_demand": round(forecast, 2),
        "current_stock": float(stock),
        "incoming_qty": float(incoming),
        "safety_stock": round(safety_stock, 2),
        "reorder_point": round(reorder_point, 2),
        "recommended_qty": float(recommended),
        "estimated_cost": float(estimated_cost),
        "stockout_date": stockout_str,
        "confidence": round(confidence, 2),
        "explanation": explanation,
    }
