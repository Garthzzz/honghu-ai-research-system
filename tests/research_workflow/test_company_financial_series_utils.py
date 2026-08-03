from tools.pipeline.company_financial_series_utils import (
    _amounts,
    _pct_change,
    build_net_income_yoy_meta,
    rounded_pct_change_with_interval,
)


def test_pct_change_accepts_positive_comparable_base():
    assert _pct_change(120, 100) == 20.0


def test_pct_change_suppresses_zero_and_negative_bases():
    assert _pct_change(10, 0) is None
    assert _pct_change(10, -5) is None
    assert _pct_change(-2, -5) is None
    assert _pct_change(-2, 5) is None


def test_amounts_preserve_unrounded_provider_input():
    result = _amounts(1_234_567.89, "CNY", {"CNY": 1.0, "USD": 7.0})
    assert result["local_raw"] == 1_234_567.89
    assert result["local_yi"] == 0.01
    assert result["local_currency"] == "CNY"
    assert result["cny_currency"] == "CNY"
    assert result["usd_currency"] == "USD"


def test_rounded_pct_change_flags_small_display_base():
    result = rounded_pct_change_with_interval(0.02, 0.01)
    assert result is not None
    assert result["value"] == 100.0
    assert result["low"] == 0.0
    assert result["high"] == 400.0
    assert result["unstable"] is True


def test_rounded_pct_change_keeps_stable_display_inputs():
    result = rounded_pct_change_with_interval(120.0, 100.0)
    assert result is not None
    assert result["value"] == 20.0
    assert result["unstable"] is False


def test_net_income_yoy_meta_preserves_provider_value_but_blocks_negative_base():
    result = build_net_income_yoy_meta(
        {"local_raw": 37_000_000, "local_yi": 0.37},
        {"local_raw": -223_000_000, "local_yi": -2.23},
        currency="CNY",
        provider_original_value=-116.46,
        provider_original_origin="Tushare fina_indicator.netprofit_yoy",
    )
    assert result["state"] == "turnaround"
    assert result["state_label"] == "扭亏"
    assert result["valid_for_comparison"] is False
    assert result["comparison_value_pct"] is None
    assert result["provider_original_value_pct"] == -116.46
    assert result["provider_original_is_comparison_input"] is False


def test_net_income_yoy_meta_blocks_unstable_rounded_low_base():
    result = build_net_income_yoy_meta(
        {"local_yi": 0.02},
        {"local_yi": 0.01},
        currency="EUR",
        snapshot_original_value=100.0,
    )
    assert result["state"] == "low_base_unstable"
    assert result["valid_for_comparison"] is False
    assert result["comparison_value_pct"] is None
    assert result["rounding_interval_pct"]["unstable"] is True
