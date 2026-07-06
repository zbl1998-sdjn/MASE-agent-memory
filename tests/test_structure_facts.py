"""确定性版面结构解析(表格行/问答行/宽空格 KV/序号选项组)行为测试。

规则与 kv_extract 同族:值取底稿原文切片、evidence=原文行、无结构不产出
(装饰页零产出保 halluc_ok);规则通用,不引用任何评测内容。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _facts(text):
    from mase.multimodal.structure_facts import parse_structure_facts

    return parse_structure_facts(text)


def _pairs(text):
    return {(f.key, f.value) for f in _facts(text)}


# ---------- 表格行打包 ----------

def test_table_row_packs_first_cell_as_key_rest_verbatim():
    text = (
        "| 学期 | 课程 | 思想道德 | 高等数学 | 建筑材料 | 总分 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 一学期 | 分数 | 85 | 68 | 78 | 646 |"
    )
    pairs = _pairs(text)
    keys = {k for k, _ in pairs}
    assert "学期" in keys and "一学期" in keys
    header_value = next(v for k, v in pairs if k == "学期")
    assert "建筑材料" in header_value and "思想道德" in header_value
    # 值是原文切片(保留竖线分隔),不做重排
    assert "|" in header_value
    score_value = next(v for k, v in pairs if k == "一学期")
    assert "68" in score_value and "646" in score_value


def test_table_separator_row_and_digit_first_cell_yield_nothing():
    assert _pairs("| --- | --- | --- |") == set()
    # 首格纯数字(序号列)不是标签
    assert _pairs("| 1 | NASI LEMAK | 2.50 |") == set()


def test_two_cell_row_pairs_label_to_value():
    pairs = _pairs("口互换号牌号码 | 互换后的号牌号码 |")
    assert ("口互换号牌号码", "互换后的号牌号码") in pairs


def test_table_row_with_leading_empty_cells_uses_first_nonempty():
    pairs = _pairs("| | 民营(√) | 合资() | 合资方国别 |")
    value = next(v for k, v in pairs if k == "民营(√)")
    assert "合资()" in value


def test_long_first_cell_is_not_a_label():
    text = "| 本表所列各项内容均须如实填写并对真实性负责否则后果自负 | 备注 |"
    assert _pairs(text) == set()


# ---------- 问答行配对 ----------

def test_question_line_pairs_with_checkbox_answer_line():
    pairs = _pairs("上周您是否没能获得工作？\n口是 口否\n您是否在上周离职？")
    values = {v for _, v in pairs}
    assert "口是 口否" in values


def test_question_skips_bilingual_duplicate_and_aggregates_options():
    text = (
        "1、身体是否有不适症状？\n"
        "Do you have any health problems?\n"
        "□ 是 Yes\n"
        "□ 否 No\n"
        "2、过去14天内是否到过疫区？"
    )
    pairs = _pairs(text)
    value = next(v for k, v in pairs if "不适症状" in k)
    assert "□ 是 Yes" in value and "□ 否 No" in value


def test_question_without_checkbox_answer_yields_nothing():
    # 问句后是普通长句(非勾选选项)→ 不配对,避免装饰页误产出
    assert _pairs("这是什么?\n这是一段与勾选无关的普通说明文字而已") == set()


# ---------- 宽空格 KV ----------

def test_wide_space_pairs_split_labels_and_values():
    pairs = _pairs("姓名 孙艺   学号 200652468    班主任：邵寅")
    assert ("姓名", "孙艺") in pairs
    assert ("学号", "200652468") in pairs
    assert ("班主任", "邵寅") in pairs


def test_wide_space_needs_multiple_segments():
    # 单段行不触发(避免把普通"两词句"误判为 KV)
    assert _pairs("GRAND TOTAL") == set()
    assert _pairs("欢迎光临 本店") == set()


# ---------- 序号选项组 ----------

def test_enumerated_options_kept_verbatim_with_label():
    line = "妊娠情况 1.未孕√ 2.已孕（怀孕时间： 年月）3.已生育"
    pairs = _pairs(line)
    value = next(v for k, v in pairs if k == "妊娠情况")
    assert "1.未孕√" in value and "3.已生育" in value


def test_enumeration_without_selection_mark_yields_nothing():
    assert _pairs("目录 1.前言 2.正文 3.附录") == set()


def test_multiline_lettered_options_pair_with_label_line():
    text = "客户类型\nA. 生产企业□\nB. 加工企业□\nC. 贸易公司□"
    pairs = _pairs(text)
    value = next(v for k, v in pairs if k == "客户类型")
    assert "A. 生产企业□" in value and "C. 贸易公司□" in value


def test_multiline_options_need_checkbox_and_two_lines():
    # 无勾选框的字母列表(目录/条款)不配对;单行选项也不配对。
    assert _pairs("参考文献\nA. 某文献\nB. 另一文献") == set()
    assert _pairs("客户类型\nA. 生产企业□") == set()


# ---------- 公共不变式 ----------

def test_decoration_page_yields_nothing():
    text = "THANK YOU FOR YOUR PATRONAGE\nPLEASE COME AGAIN\n欢迎光临\n满100减20"
    assert _facts(text) == []


def test_evidence_is_source_line_and_category_general():
    facts = _facts("口互换号牌号码 | 互换后的号牌号码 |")
    assert facts[0].evidence == "口互换号牌号码 | 互换后的号牌号码 |"
    assert facts[0].category == "general_facts"


def test_qa_evidence_is_verbatim_slice_of_source():
    # 治理层 evidence 须能在抽取全文中逐字定位:QA 证据=问句到选项的连续切片。
    text = (
        "1、身体是否有不适症状？\n"
        "Do you have any health problems?\n"
        "□ 是 Yes\n"
        "□ 否 No"
    )
    fact = next(f for f in _facts(text) if "不适症状" in f.key)
    assert fact.evidence in text


# ---------- 单向超集并集 ----------

def test_union_superset_keeps_pack_that_extends_existing_value():
    from mase.multimodal.extractor import CandidateFact
    from mase.multimodal.structure_facts import union_superset_facts

    llm = [CandidateFact("general_facts", "核算方式", "√独立核算", 0.8, "ev")]
    pack = [CandidateFact(
        "general_facts", "核算方式", "√独立核算 □非独立核算 | 适用会计规定 | □企业会计准则", 0.7, "ev2",
    )]
    merged = union_superset_facts(llm, pack)
    assert any("企业会计准则" in f.value for f in merged)  # 超集保留(带新锚串)


def test_union_superset_drops_candidate_covered_by_existing():
    from mase.multimodal.extractor import CandidateFact
    from mase.multimodal.structure_facts import union_superset_facts

    llm = [CandidateFact("general_facts", "options", "□企业会计准则 □企业会计制度", 0.8, "ev")]
    covered = [CandidateFact("general_facts", "适用会计规定", "企业会计准则", 0.7, "ev2")]
    merged = union_superset_facts(llm, covered)
    assert len(merged) == 1  # 已被现有值覆盖 → 不重复存
