import pytest

from prospector.money import fmt, from_milli, parse_amount, to_milli


@pytest.mark.parametrize("text,milli", [("1200", 1_200_000), ("1 200,50", 1_200_500), ("1,200.50", 1_200_500),
                                         ("0.125", 125), ("12,5", 12_500), (" 7 ", 7_000)])
def test_parse_amount_accepts(text, milli):
    assert parse_amount(text) == milli


@pytest.mark.parametrize("text", ["", "  ", "abc", "0", "-5", "1.2.3", "nan", "inf", "0.0001"])
def test_parse_amount_rejects(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_fmt():
    assert fmt(1_200_000, "USD") == "$1,200"
    assert fmt(1_200_500, "USD") == "$1,200.50"
    assert fmt(1_350_000, "TND") == "1,350 TND"
    assert fmt(1_350_250, "TND") == "1,350.25 TND"
    assert fmt(90_000, "EUR") == "€90" and fmt(12_300, "GBP") == "£12.30"


def test_milli_round_trip():
    assert to_milli(12.345) == 12_345 and from_milli(12_345) == 12.345 and to_milli(0.1 + 0.2) == 300


@pytest.mark.parametrize("text,milli", [("1.200,50", 1_200_500), ("1,200,000", 1_200_000_000),
                                         ("1.200.000,5", 1_200_000_500), ("0,125", 125), ("0.125", 125),
                                         ("12.50", 12_500), ("1 200,50", 1_200_500)])
def test_parse_amount_locale_formats(text, milli):
    assert parse_amount(text) == milli


@pytest.mark.parametrize("text", ["1,200", "1.200", "12.345"])
def test_parse_amount_rejects_ambiguous_thousands(text):
    with pytest.raises(ValueError, match="could mean"):
        parse_amount(text)


@pytest.mark.parametrize("text", ["1e40", "1e3", "1E3", "+5", "5$", "0x10", "1,2,3", "99999999999999"])
def test_parse_amount_rejects_odd_input_as_value_error(text):
    with pytest.raises(ValueError):
        parse_amount(text)
