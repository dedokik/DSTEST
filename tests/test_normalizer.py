"""Тесты нормализации дат и единиц."""

from src.normalizer import normalize_movement


def test_dot_date():
    r = normalize_movement("05.03.2026 MS-01 приход OIL-001, 2 канистры по 5 л, НК-345")
    assert r["date"] == "2026-03-05"


def test_text_date():
    r = normalize_movement("1 марта 2026 MS-01 расход oil 001 — 450 мл, B-OIL-001-012")
    assert r["date"] == "2026-03-01"


def test_iso_date():
    r = normalize_movement("2026-03-08; MS-01; CONS-051; расход; 48 пар")
    assert r["date"] == "2026-03-08"


def test_slash_date_dd_mm_yy():
    r = normalize_movement("03/06/26 Сочи списание SCRB-020 1,2 кг, истёк срок")
    assert r["date"] == "2026-06-03"


def test_two_digit_year_dot():
    r = normalize_movement("07.03.26 ms-02 WRAP 030 расход 3,5кг, парт.B-WRAP-030-004")
    assert r["date"] == "2026-03-07"


def test_ml_to_litres():
    r = normalize_movement("1 марта 2026 MS-01 расход oil 001 — 450 мл, B-OIL-001-012")
    assert r["qty"] == 0.45
    assert r["unit"] == "л"


def test_multi_pack():
    r = normalize_movement("05.03.2026 MS-01 приход OIL-001, 2 канистры по 5 л, НК-345")
    assert r["qty"] == 10.0


def test_dash_separator_is_not_minus():
    r = normalize_movement("1 марта 2026 MS-01 расход oil 001 — 450 мл, B-OIL-001-012")
    assert r["qty"] == 0.45  # разделительное тире не делает число отрицательным


def test_negative_correction():
    r = normalize_movement("Корректировка 15.03.2026, MS-02, CONS-052: −120 шт")
    assert r["qty"] == -120
    assert r["operation"] == "correction"


def test_location_is_not_doc():
    r = normalize_movement("2026-03-08; MS-01; CONS-051; расход; 48 пар")
    assert r["location"] == "MS-01"
    assert r["doc_no"] is None
