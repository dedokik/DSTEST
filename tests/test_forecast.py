"""Тесты прогноза и округления до упаковки."""

from src.data_loader import catalog_map, load_catalog, load_dataset
from src.forecast import forecast_demand


def _ctx():
    ds = load_dataset()
    cmap = catalog_map(load_catalog())
    history = {
        "as_of": ds["as_of"],
        "weekly_consumption": ds["weekly_consumption"],
        "current_stock": ds["current_stock"],
        "incoming_qty": ds["incoming_qty"],
    }
    return history, cmap


def test_rounding_to_pack_and_min():
    history, cmap = _ctx()
    r = forecast_demand(history, "OIL-001", 30, {"catalog": cmap})
    # OIL-001: pack 5, min 10 -> recommended кратно 5 и >= 10 (или 0).
    assert r["recommended_qty"] % 5 == 0
    assert r["recommended_qty"] == 0 or r["recommended_qty"] >= 10


def test_zero_need_gives_zero():
    history, cmap = _ctx()
    r = forecast_demand(history, "WRAP-030", 30, {"catalog": cmap})
    assert r["recommended_qty"] == 0.0
    assert r["estimated_cost"] == 0.0


def test_cost_uses_catalog_price():
    history, cmap = _ctx()
    r = forecast_demand(history, "SCRB-020", 30, {"catalog": cmap})
    assert abs(r["estimated_cost"] - r["recommended_qty"] * cmap["SCRB-020"]["price"]) < 0.01


def test_confidence_range():
    history, cmap = _ctx()
    for sku in ("OIL-001", "SCRB-020", "WRAP-030"):
        r = forecast_demand(history, sku, 30, {"catalog": cmap})
        assert 0.0 <= r["confidence"] <= 1.0


def test_load_factor_scales_forecast():
    history, cmap = _ctx()
    base = forecast_demand(history, "OIL-001", 30, {"catalog": cmap})
    scaled = forecast_demand(history, "OIL-001", 30, {"catalog": cmap, "load_factor": 1.2})
    assert scaled["forecast_demand"] > base["forecast_demand"]
    assert scaled["forecast_demand"] == round(base["forecast_demand"] * 1.2, 2)
