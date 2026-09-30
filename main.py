"""CLI: прогон всего пайплайна на тестовых данных (1 команда)."""

from __future__ import annotations

import argparse
import json

from src.assistant import answer_question
from src.data_loader import catalog_map, load_catalog, load_dataset
from src.forecast import forecast_demand
from src.normalizer import normalize_movement


def run_pipeline() -> dict:
    """Выполнить все три части и вернуть результаты."""
    dataset = load_dataset()
    catalog = load_catalog()
    cmap = catalog_map(catalog)

    movements = [
        {"id": m["id"], "text": m["text"], "parsed": normalize_movement(m["text"])}
        for m in dataset.get("movements", [])
    ]

    history = {
        "as_of": dataset.get("as_of"),
        "weekly_consumption": dataset.get("weekly_consumption", {}),
        "current_stock": dataset.get("current_stock", {}),
        "incoming_qty": dataset.get("incoming_qty", {}),
    }
    forecasts = []
    for sku in ("OIL-001", "SCRB-020", "WRAP-030"):
        for horizon in (30, 90):
            r = forecast_demand(history, sku, horizon, {"catalog": cmap})
            forecasts.append({"sku": sku, "horizon_days": horizon, **r})

    context = {"history": history, "catalog": cmap, "as_of": history["as_of"]}
    answers = []
    for q in dataset.get("questions", []):
        params, conf, text = answer_question(q, context)
        answers.append({"question": q, "params": params, "confidence": conf, "answer": text})

    return {"movements": movements, "forecasts": forecasts, "answers": answers}


def main() -> None:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="MVP ИИ-помощника склада: прогон пайплайна")
    parser.add_argument("--out", default="results.json", help="Куда сохранить JSON-результат")
    parser.add_argument("--print", dest="do_print", action="store_true", help="Печатать таблицы")
    args = parser.parse_args()

    result = run_pipeline()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Saved -> {args.out}")
    if args.do_print:
        print("\n== Часть 1: нормализация ==")
        for m in result["movements"]:
            print(m["id"], m["parsed"])
        print("\n== Часть 2: прогноз ==")
        for r in result["forecasts"]:
            print(r["sku"], r["horizon_days"], r["recommended_qty"], r["estimated_cost"], r["confidence"])
        print("\n== Часть 3: вопросы ==")
        for a in result["answers"]:
            print("-", a["question"][:60], "=>", a["params"], a["confidence"])


if __name__ == "__main__":
    main()
