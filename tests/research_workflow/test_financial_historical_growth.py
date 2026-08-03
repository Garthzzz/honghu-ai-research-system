from tools.financial.read_models import _historical_table


def _row(
    metric_name: str,
    value: float,
    *,
    fiscal_year: int,
    fiscal_period: str,
    frequency: str,
) -> dict:
    return {
        "metric_name": metric_name,
        "value_num": value,
        "unit": "%" if metric_name.endswith("_yoy") else "亿元人民币",
        "fact_type": "actual",
        "quality_status": "usable",
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "frequency": frequency,
        "period_end": (
            f"{fiscal_year}-03-31"
            if fiscal_period == "Q1"
            else f"{fiscal_year}-12-31"
        ),
        "as_of_date": "2026-04-16",
        "provider": "tushare",
        "source_title": "测试快照",
        "source_ref": "test://snapshot",
        "revision_no": 1,
        "id": 1,
    }


def test_quarterly_yoy_is_attached_to_same_period_observation() -> None:
    table = _historical_table(
        {
            "revenue": [
                _row(
                    "revenue",
                    591.45,
                    fiscal_year=2025,
                    fiscal_period="FY",
                    frequency="annual",
                ),
                _row(
                    "revenue",
                    213.03,
                    fiscal_year=2026,
                    fiscal_period="Q1",
                    frequency="quarterly",
                ),
            ],
            "net_income": [
                _row(
                    "net_income",
                    12.67,
                    fiscal_year=2026,
                    fiscal_period="Q1",
                    frequency="quarterly",
                )
            ],
            "revenue_yoy": [
                _row(
                    "revenue_yoy",
                    46.33,
                    fiscal_year=2026,
                    fiscal_period="Q1",
                    frequency="quarterly",
                )
            ],
            "net_income_yoy": [
                _row(
                    "net_income_yoy",
                    8.92,
                    fiscal_year=2026,
                    fiscal_period="Q1",
                    frequency="quarterly",
                )
            ],
        }
    )
    q1 = next(row for row in table if row["period"] == "2026Q1")
    assert q1["metrics"]["revenue"]["yoy"] == 46.33
    assert q1["metrics"]["net_income"]["yoy"] == 8.92
