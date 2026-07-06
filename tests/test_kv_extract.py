"""确定性 键:值 行解析(与 LLM 抽取取并集)行为测试。

半结构化表单/收据的 `键<冒号>值` 行用纯代码规则解析:值逐字取自底稿
(evidence=整行,治理层 span 定位天然通过);无冒号结构的装饰页/口号行
不产出 → 幻觉零风险。这是补 LLM 单次枚举遗漏的确定性兜底。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _kv(text):
    from mase.multimodal.kv_extract import parse_kv_lines

    return {(f.key, f.value) for f in parse_kv_lines(text)}


def test_ascii_colon_line():
    facts = _kv("Tel: +603-3362 4137\nGST ID No: 001531760640")
    assert ("Tel", "+603-3362 4137") in facts
    assert ("GST_ID_No", "001531760640") in facts


def test_fullwidth_colon_line():
    facts = _kv("出生日期：1983/6/8\n账号：2568598457456854")
    assert ("出生日期", "1983/6/8") in facts
    assert ("账号", "2568598457456854") in facts


def test_compound_line_value_keeps_trailing_anchor():
    # 收据常把两项塞一行;split first colon → value 含尾部日期锚串,足够计分。
    facts = _kv("INV NO: CS-SA-0075638 Date : 04/04/2017")
    values = {v for _, v in facts}
    assert any("04/04/2017" in v for v in values)


def test_empty_value_field_is_skipped():
    # 未填写的表单项(键后无值)不产出,避免空事实。
    assert _kv("Owned By:\n签名:") == set()


def test_time_and_ratio_are_not_kv():
    # 纯数字键(时间/比例)不是标签,不产出。
    assert _kv("10:30\n1:2\n88:00") == set()


def test_url_scheme_not_split_as_kv():
    # http://... 的冒号是 scheme 冒号,不当 KV;但 E-mail: 是真 KV。
    facts = _kv("Follow: http://example.com/x\nE-mail: a@b.com")
    values = {v for _, v in facts}
    assert "a@b.com" in values
    assert not any(v.startswith("//") for v in values)  # 不产出 //example...


def test_decoration_lines_yield_nothing():
    # 口号/装饰页无冒号结构 → 零产出(halluc_ok 保护)。
    text = "THANK YOU FOR YOUR PATRONAGE\nPLEASE COME AGAIN\n欢迎光临"
    assert _kv(text) == set()


def test_key_whitespace_normalized():
    facts = _kv("Mobile /Whatsapps : +6012-918 7937")
    keys = {k for k, _ in facts}
    assert "Mobile_/Whatsapps" in keys or "Mobile /Whatsapps" not in keys
    assert any(v == "+6012-918 7937" for _, v in facts)


def test_evidence_is_full_line():
    from mase.multimodal.kv_extract import parse_kv_lines

    (fact,) = parse_kv_lines("Tel: +603-3362 4137")
    assert fact.evidence == "Tel: +603-3362 4137"
    assert fact.category == "general_facts"


def test_multi_kv_segments_in_one_line():
    # 表单常把多个 键:值 挤进一行(宽空格分隔);≥2 个有效冒号时逐段切分。
    facts = _kv("单位：金安区第三中学 住宅：金安区天鹿睿园 手机：15141234567")
    assert ("单位", "金安区第三中学") in facts
    assert ("住宅", "金安区天鹿睿园") in facts
    assert ("手机", "15141234567") in facts


def test_multi_kv_first_segment_uses_line_prefix_as_key():
    # 首段的键沿用 v6 语义(行首到首冒号),不丢 "INV" 前缀。
    facts = _kv("INV NO: CS-SA-0075638 Date : 04/04/2017")
    assert ("INV_NO", "CS-SA-0075638") in facts
    assert ("Date", "04/04/2017") in facts


def test_time_colon_inside_multi_kv_stays_in_value():
    # 纯数字"键"的冒号(时间)不是分隔符,整段留在值里。
    facts = _kv("营业时间: 10:30-22:00 电话: 55667788")
    assert ("营业时间", "10:30-22:00") in facts
    assert ("电话", "55667788") in facts


def test_single_colon_line_keeps_v6_first_colon_behavior():
    # 只有一个有效冒号时不启用多段切分,行为与 v6 逐字节一致。
    facts = _kv("备注：含 10:30 的说明文字")
    assert ("备注", "含 10:30 的说明文字") in facts


def test_union_skips_values_already_in_llm_facts():
    from mase.multimodal.extractor import CandidateFact
    from mase.multimodal.kv_extract import union_kv_facts

    llm = [CandidateFact("finance_budget", "total_line", "Total 14.90", 0.8, "Total 14.90")]
    kv = [
        CandidateFact("general_facts", "total", "14.90", 0.7, "Total 14.90"),  # 已被覆盖的子串
        CandidateFact("general_facts", "gst_id", "001531760640", 0.7, "GST ID No: 001531760640"),  # 新值
    ]
    merged = union_kv_facts(llm, kv)
    values = {f.value for f in merged}
    assert "Total 14.90" in values and "001531760640" in values
    # 已被 LLM 值覆盖的子串不重复存
    assert sum(1 for f in merged if "14.90" in f.value) == 1


def test_union_keeps_kv_superset_that_extends_llm_value():
    # 诊断集真实反例:LLM 抽了地址中的机构短名,KV 完整地址值不能被当重复丢弃。
    from mase.multimodal.extractor import CandidateFact
    from mase.multimodal.kv_extract import union_kv_facts

    llm = [CandidateFact("general_facts", "unit_name", "高各庄村办事处", 0.8, "ev")]
    kv = [CandidateFact(
        "general_facts", "详细通讯地址", "河北省保定市徐水县正村乡高各庄村办事处", 0.7, "ev2",
    )]
    merged = union_kv_facts(llm, kv)
    assert any("河北省" in f.value for f in merged)  # 超集保留(携带前缀锚串)
