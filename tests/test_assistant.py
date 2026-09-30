"""Тесты разбора вопросов (Часть 3)."""

from src.assistant import answer_question
from src.data_loader import catalog_map, load_catalog, load_dataset


def _context():
    ds = load_dataset()
    return {
        "history": {
            "as_of": ds["as_of"],
            "weekly_consumption": ds["weekly_consumption"],
            "current_stock": ds["current_stock"],
            "incoming_qty": ds["incoming_qty"],
        },
        "catalog": catalog_map(load_catalog()),
    }


def test_forecast_intent_with_params():
    params, conf, text = answer_question(
        "Сколько масла закупить на три месяца и сколько это будет стоить?", _context()
    )
    assert params["intent"] == "forecast_purchase"
    assert params["sku"] == "OIL-001"
    assert params["horizon_days"] == 90


def test_unknown_when_no_params():
    params, conf, text = answer_question("Сколько это будет стоить?", _context())
    assert params["intent"] == "unknown"
    assert "уточнение" in text.lower()


def test_out_of_domain_unknown():
    params, conf, text = answer_question("Какая погода в Сочи на выходных?", _context())
    assert params["intent"] == "unknown"


def test_no_hallucinated_numbers():
    # Ответ должен содержать числа только из forecast (проверяем наличие объяснения).
    params, conf, text = answer_question("Посчитай закупку скраба на полгода при лимите 200 тысяч", _context())
    assert params["intent"] == "forecast_purchase"
    assert "SCRB-020" in text or "скраб" in text.lower() or "прогноз" in text.lower()


def test_load_factor_extracted():
    params, conf, text = answer_question(
        "Сколько масла уйдёт за месяц, если загрузка вырастет на 20%?", _context()
    )
    assert params["intent"] == "forecast_purchase"
    assert params["load_factor"] == 1.2
    assert "x1.2" in text or "загрузку" in text.lower()


def test_god_inside_pogoda_is_not_period():
    params, conf, text = answer_question("Какая погода в Сочи на выходных?", _context())
    assert params["horizon_days"] is None
