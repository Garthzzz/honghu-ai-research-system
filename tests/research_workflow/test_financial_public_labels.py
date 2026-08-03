from tools.financial.read_models import _public_scenario_label


def test_public_scenario_label_translates_known_internal_identifier() -> None:
    assert _public_scenario_label("target_pe_midpoint") == "目标市盈率中值口径"


def test_public_scenario_label_hides_unregistered_internal_identifier() -> None:
    assert _public_scenario_label("future_internal_scenario") == "模型设定口径"


def test_public_scenario_label_preserves_natural_chinese_label() -> None:
    assert _public_scenario_label("独立盈利路径") == "独立盈利路径"
