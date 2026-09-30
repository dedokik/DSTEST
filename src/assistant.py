"""Разбор вопроса пользователя и объяснение ответа (Часть 3)."""

from __future__ import annotations

import os
import re
from typing import Any

from .config import INTENT_GAP_THRESHOLD, INTENT_MIN_SCORE
from .forecast import forecast_demand

INTENTS = (
    "forecast_purchase",
    "reorder_list",
    "budget",
    "deficit_risk",
    "expiry_risk",
    "price_dynamics",
    "unknown",
)

# Ключевые фразы для скоринга интентов (fallback без LLM).
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "forecast_purchase": [
        "сколько масла закупить",
        "сколько масла уйдёт",
        "сколько масла уйдет",
        "посчитай закупку",
        "сколько скраба",
        "закупить на",
        "заказать масло",
        "сколько уйдёт",
        "сколько уйдет",
        "понадобится",
    ],
    "reorder_list": [
        "что нужно заказать",
        "что заказать",
        "ближайшие",
        "следующие 14",
        "список заказов",
    ],
    "budget": [
        "бюджет",
        "сколько стоит закупить всё",
        "план закупок",
        "бюджет закупок",
        "сколько это будет стоить",
        "сколько будет стоить",
    ],
    "deficit_risk": [
        "закончится",
        "дефицит",
        "риске дефицита",
        "осталось",
        "хватит",
        "до следующей поставки",
    ],
    "expiry_risk": [
        "партии сгорят",
        "сгорят",
        "срок годности",
        "истёк",
        "истек",
        "просроч",
        "списани",
    ],
    "price_dynamics": [
        "подорожал",
        "подешевел",
        "динамика цен",
        "цена у поставщика",
        "насколько",
        "стоимость изменилась",
    ],
}

_SKU_KEYWORDS: dict[str, list[str]] = {
    "OIL-002": ["ароматическ", "лаванд", "oil-002", "oil 002"],
    "SCRB-020": ["скраб", "scrb"],
    "WRAP-030": ["альгинат", "маск", "wrap"],
    "OIL-001": ["oil-001", "oil 001", "базов", "миндаль"],
}

_LOCATION_KEYWORDS: dict[str, list[str]] = {
    "Сочи": ["сочи"],
    "Красная Поляна": ["красная поляна", "красной поляне"],
    "MS-01": ["ms-01", "ms 01"],
    "MS-02": ["ms-02", "ms 02"],
}

_PERIOD_WORDS: list[tuple[str, int]] = [
    ("три месяца", 90),
    ("полгода", 180),
    ("полугод", 180),
    ("квартал", 90),
    ("месяц", 30),
    ("месяце", 30),
    ("две недели", 14),
    ("14 дней", 14),
    ("14 дне", 14),
    ("30 дней", 30),
    ("год", 365),
]

_PERIOD_NUM_RE = re.compile(r"(\d+)\s*(дн\w*|нед\w*|мес\w*|квартал\w*|год\w*|полгода)", re.IGNORECASE)
_LOAD_FACTOR_RE = re.compile(r"(?:вырастет|рост|увеличится|\+)\s*(?:на\s*)?(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)


def _score_intents(question: str) -> dict[str, float]:
    low = question.lower()
    scores: dict[str, float] = {}
    for intent, phrases in _INTENT_KEYWORDS.items():
        hit = sum(1 for p in phrases if p in low)
        # Нормируем: 1 фраза = 1.0, 2+ фраз = выше.
        scores[intent] = float(hit)
    # Эвристики для коротких вопросов без явных фраз.
    if scores.get("forecast_purchase", 0) == 0 and "закупи" in low and "сколько" in low:
        scores["forecast_purchase"] = 1.0
    if "что закончится" in low or "что закончит" in low:
        scores["deficit_risk"] = max(scores.get("deficit_risk", 0), 1.0)
    if "почему план" in low:
        scores["budget"] = max(scores.get("budget", 0), 1.0)
    if "когда привезут" in low or "погода" in low:
        for k in scores:
            scores[k] = 0.0
    return scores


def _extract_sku(question: str) -> str | None:
    low = question.lower()
    for sku, kws in _SKU_KEYWORDS.items():
        if any(k in low for k in kws):
            return sku
    # Дженерик "масло/масла" без уточнения -> считаем базовым OIL-001 (фиксируем допущение).
    if "масл" in low:
        return "OIL-001"
    return None


def _extract_location(question: str) -> str | None:
    low = question.lower()
    for loc, kws in _LOCATION_KEYWORDS.items():
        if any(k in low for k in kws):
            return loc
    return None


def _extract_period(question: str) -> int | None:
    low = question.lower()
    for phrase, days in _PERIOD_WORDS:
        # Ищем по границам слов, чтобы "год" не находился внутри "погода".
        if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", low):
            return days
    m = _PERIOD_NUM_RE.search(low)
    if m:
        num = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("дн"):
            return num
        if unit.startswith("нед"):
            return num * 7
        if unit.startswith("мес"):
            return num * 30
        if "квартал" in unit:
            return num * 90
        if "год" in unit:
            return num * 365
    if "этом месяце" in low:
        return 30
    return None


def _extract_budget(question: str) -> float | None:
    low = question.lower()
    if "лимит" not in low and "бюджет" not in low and "тысяч" not in low and "тыс" not in low:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(тыс(?:\.|яч)?|тысяч)", low)
    if m:
        return float(m.group(1).replace(",", ".")) * 1000.0
    return None


def _extract_load_factor(question: str) -> float:
    """Поправка на загрузку: 'вырастет на 20%' -> 1.2, иначе 1.0."""
    m = _LOAD_FACTOR_RE.search(question.lower())
    if not m:
        return 1.0
    try:
        return 1.0 + float(m.group(1).replace(",", ".")) / 100.0
    except ValueError:
        return 1.0


def _try_llm(question: str) -> dict[str, Any] | None:
    """Опциональный LLM-путь. Возвращает None, если ключа нет (fallback на правила)."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None
    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key)
        prompt = (
            "Классифицируй вопрос склада в JSON {intent, sku, location, horizon_days, budget_limit}. "
            f"Интенты: forecast_purchase, reorder_list, budget, deficit_risk, expiry_risk, price_dynamics, unknown. "
            f"Вопрос: {question}"
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        import json as _json

        return _json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return None


def _history_from_context(context: dict) -> dict:
    if "weekly_consumption" in context:
        return context
    if "history" in context and isinstance(context["history"], dict):
        return context["history"]
    return context


def _catalog_from_context(context: dict) -> dict:
    if "catalog" in context and isinstance(context["catalog"], dict):
        return context["catalog"]
    return {}


def answer_question(question: str, context: dict) -> tuple[dict, float, str]:
    """Разобрать вопрос и построить ответ с объяснением (числа только из Части 2).

    Args:
        question: вопрос пользователя на русском.
        context: словарь с history/catalog/as_of для расчётов Части 2.

    Returns:
        Кортеж (params, confidence, answer_text). params содержит intent, sku,
        location, horizon_days, budget_limit.
    """
    llm = _try_llm(question)
    if llm and llm.get("intent") in INTENTS:
        params = {
            "intent": llm.get("intent", "unknown"),
            "sku": llm.get("sku"),
            "location": llm.get("location"),
            "horizon_days": llm.get("horizon_days"),
            "budget_limit": llm.get("budget_limit"),
            "load_factor": float(llm.get("load_factor", 1.0) or 1.0),
        }
        return params, 0.75, _build_answer(params, context, question)

    scores = _score_intents(question)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_intent, top_score = ranked[0] if ranked else ("unknown", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    gap = float(top_score - second_score)

    sku = _extract_sku(question)
    location = _extract_location(question)
    horizon = _extract_period(question)
    budget_limit = _extract_budget(question)
    load_factor = _extract_load_factor(question)

    # Проверка обязательных параметров.
    missing_mandatory = False
    if top_intent == "forecast_purchase" and (sku is None or horizon is None):
        missing_mandatory = True
    elif top_intent == "reorder_list" and horizon is None:
        missing_mandatory = True
    elif top_intent == "budget" and horizon is None:
        # Для бюджета без периода уточняем (кроме спец-вопроса "всё в риске").
        if "в риске" not in question.lower():
            missing_mandatory = True
    elif top_intent == "price_dynamics" and sku is None:
        missing_mandatory = True

    if top_score < INTENT_MIN_SCORE or gap < INTENT_GAP_THRESHOLD or missing_mandatory:
        intent = "unknown"
        confidence = 0.35 if top_score > 0 else 0.25
        params = {
            "intent": intent,
            "sku": sku,
            "location": location,
            "horizon_days": horizon,
            "budget_limit": budget_limit,
            "load_factor": load_factor,
        }
        return params, confidence, _clarify(params, question)

    confidence = min(0.95, 0.55 + 0.15 * top_score + gap * 0.2)
    if sku is None and top_intent in ("forecast_purchase",):
        confidence -= 0.1
    params = {
        "intent": top_intent,
        "sku": sku,
        "location": location,
        "horizon_days": horizon,
        "budget_limit": budget_limit,
        "load_factor": load_factor,
    }
    return params, round(max(0.0, min(1.0, confidence)), 2), _build_answer(params, context, question)


def _clarify(params: dict, question: str) -> str:
    low = question.lower()
    if "погода" in low or "когда привезут" in low:
        return (
            "Вопрос вне домена складского учёта (нет данных о доставках/погоде). "
            "Могу помочь с закупкой, бюджетом, рисками дефицита и сроками годности. "
            "Уточните позицию и период, например: 'Сколько скраба закупить на квартал?'"
        )
    missing = []
    if params.get("sku") is None and any(
        w in low for w in ["сколько", "закупи", "заказать", "стоит"]
    ):
        missing.append("позицию (масло базовое / скраб / маска)")
    if params.get("horizon_days") is None and any(
        w in low for w in ["сколько", "закупи", "заказать", "бюджет", "стоит"]
    ):
        missing.append("период (14 дней / месяц / квартал / полгода)")
    if missing:
        return "Требуется уточнение: укажите " + " и ".join(missing) + "."
    return (
        "Требуется уточнение: не хватает параметров для расчёта. "
        "Укажите позицию и период, например: 'Сколько масла закупить на три месяца?'"
    )


def _build_answer(params: dict, context: dict, question: str) -> str:
    history = _history_from_context(context)
    catalog = _catalog_from_context(context)
    fparams = {"catalog": catalog} if catalog else {}
    if history.get("as_of"):
        fparams["as_of"] = history["as_of"]
    intent = params.get("intent")
    sku = params.get("sku")
    horizon = params.get("horizon_days")
    budget_limit = params.get("budget_limit")
    location = params.get("location")
    load_factor = float(params.get("load_factor", 1.0) or 1.0)

    skus_with_history = [k for k in history.get("weekly_consumption", {})] if isinstance(
        history.get("weekly_consumption"), dict
    ) else []

    if intent == "forecast_purchase" and sku and horizon:
        fparams = dict(fparams)
        fparams["load_factor"] = load_factor
        r = forecast_demand(history, sku, int(horizon), fparams)
        text = (
            f"По позиции {sku} на {horizon} дн.: прогноз {r['forecast_demand']} ед., "
            f"рекомендую закупить {r['recommended_qty']:g} ед., "
            f"стоимость {r['estimated_cost']:,.2f} ₽. {r['explanation']}"
        )
        if budget_limit and r["estimated_cost"] > float(budget_limit):
            text += f" Внимание: превышает лимит {float(budget_limit):,.0f} ₽."
        return text
    if intent == "reorder_list" and horizon:
        lines = []
        for s in skus_with_history:
            r = forecast_demand(history, s, int(horizon), fparams)
            if (r["current_stock"] + r["incoming_qty"]) < (r["forecast_demand"] + r["safety_stock"]):
                lines.append(f"{s}: {r['recommended_qty']:g} ед. ({r['estimated_cost']:,.0f} ₽)")
        if not lines:
            return f"На {horizon} дн. заказов не требуется: остатков и поставок в пути хватает."
        loc = f" (объект: {location})" if location else ""
        return f"Заказать в ближайшие {horizon} дн.{loc}: " + "; ".join(lines) + "."
    if intent == "budget":
        h = int(horizon) if horizon else 90
        total = 0.0
        parts = []
        for s in skus_with_history:
            r = forecast_demand(history, s, h, fparams)
            total += r["estimated_cost"]
            parts.append(f"{s}: {r['recommended_qty']:g} ед. = {r['estimated_cost']:,.0f} ₽")
        return f"Бюджет закупок на {h} дн.: {total:,.0f} ₽ (" + "; ".join(parts) + ")."
    if intent == "deficit_risk":
        from datetime import date as _date
        from datetime import timedelta as _td

        h = int(horizon) if horizon else 30
        try:
            limit_date = _date.fromisoformat(str(history.get("as_of"))) + _td(days=h)
            limit_str = limit_date.isoformat()
        except Exception:
            limit_str = None
        at_risk = []
        total = 0.0
        for s in skus_with_history:
            r = forecast_demand(history, s, h, fparams)
            low_cover = (r["current_stock"] + r["incoming_qty"]) < r["reorder_point"]
            ends_soon = bool(limit_str and r["stockout_date"] and r["stockout_date"] <= limit_str)
            if low_cover or ends_soon:
                at_risk.append(f"{s} (остаток {r['current_stock']:g}, хватит до {r['stockout_date']})")
                total += r["estimated_cost"]
        # Если спросили конкретную позицию ("сколько маски осталось") — отвечаем по ней, а не общим списком.
        if sku and sku in skus_with_history:
            r = forecast_demand(history, sku, h, fparams)
            loc = f" ({location})" if location else ""
            note = " Остатки в данных только общие, без разбивки по филиалам." if location else ""
            return (
                f"По позиции {sku}{loc}: остаток {r['current_stock']:g} ед., "
                f"в пути {r['incoming_qty']:g}, хватит до {r['stockout_date']}.{note} {r['explanation']}"
            )
        loc = f" Объект: {location}." if location else ""
        if not at_risk:
            return f"Рисков дефицита на {h} дн. нет.{loc}"
        if "сколько стоит" in question.lower() or "всё" in question.lower():
            return f"В риске дефицита: {'; '.join(at_risk)}.{loc} Стоимость закупки: {total:,.0f} ₽."
        return f"Риск дефицита на {h} дн.: {'; '.join(at_risk)}.{loc}"
    if intent == "expiry_risk":
        return (
            "Данные о сроках годности партий отсутствуют в dataset.json, "
            "поэтому назвать конкретные партии не могу (не выдумываю). "
            "Подключите реестр партий со сроками — проверю, что сгорит за период."
        )
    if intent == "price_dynamics":
        return (
            "Истории цен поставщика нет в данных (есть только текущие цены catalog.json), "
            "поэтому посчитать подорожание не могу без выдуманных чисел. "
            "Подключите историю цен — рассчитаю динамику."
        )
    return _clarify(params, question)
