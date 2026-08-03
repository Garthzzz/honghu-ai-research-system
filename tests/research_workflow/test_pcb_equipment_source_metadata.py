from tools.pipeline.pcb_equipment_research_data import SOURCES
from tools.pipeline.prepare_pcb_equipment_research import _source_payload as claim_source_payload
from tools.pipeline.register_pcb_equipment_profile_sources import _source_payload as db_source_payload


def test_pcb_source_metadata_is_explicit_and_consistent():
    assert len({source.key for source in SOURCES}) == len(SOURCES)
    for source in SOURCES:
        claim = claim_source_payload(source)
        db = db_source_payload(source)
        assert source.language in {"zh", "en", "ko"}
        assert claim["language"] == db["language"] == source.language
        assert claim["fetch_method"] == db["fetch_method"]
        assert claim["note"] == source.note
        assert db["note"] == source.note


def test_pcb_source_api_and_foreign_language_contracts():
    by_key = {source.key: source for source in SOURCES}
    assert by_key["tushare"].fetch_method == "api_tushare"
    assert by_key["yfinance"].fetch_method == "api_yfinance"
    assert by_key["yfinance"].language == "en"
    assert by_key["isu_factory"].language == "ko"

    english_sources = {
        "kla_pcb", "kla_ttm", "kla_2025_10k", "mks_esi",
        "mycronic_atg", "mycronic_atg_current", "nidec_history",
        "amada_via", "ushio_via", "camtek_sale", "mitsubishi_drill",
        "via_solution", "jcu_products", "lpkf_scope", "screen_ledia",
        "schmoll_web", "cohu_atg_sale", "ttm_2024_10k", "isu_business",
    }
    assert all(by_key[key].language == "en" for key in english_sources)

    chinese_websites = {
        "hans_laser_group", "dongwei_web", "zhengye_pcb",
        "tianzhun_electronics", "inno_laser_web", "yanmade_web",
        "jutze_web", "gage_web", "ymz_web", "taliang_web", "csun_web",
        "shennan_thailand", "gce_2024",
    }
    assert all(by_key[key].language == "zh" for key in chinese_websites)
