"""评测集适配器卫生规则:XFUND KV 对过滤(v1.1)。

dev 逐例取证发现的两类客观错标(修正先于 holdout 任何一次运行):
- 未勾选复选框项(□紧急)被当期望值——真实值是 √ 勾选项;
- 长段落描述(工作职责全文)被当 KV 事实值。
规则为通用标注卫生,不引用任何评测锚串。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _doc(pairs):
    entities = []
    for i, (q, a) in enumerate(pairs):
        qid, aid = i * 2, i * 2 + 1
        entities.append({"id": qid, "label": "question", "text": q, "linking": [[qid, aid]]})
        entities.append({"id": aid, "label": "answer", "text": a, "linking": [[qid, aid]]})
    return {"document": entities}


def test_unchecked_checkbox_values_excluded():
    from benchmarks.multimodal_eval.build_suite import extract_xfund_pairs

    doc = _doc([
        ("紧急程度", "□紧急"),        # 未勾选 → 排除
        ("紧急程度", "√一般"),        # 勾选 → 保留(去掉勾选符)
        ("招聘岗位", "营运部主管"),   # 普通 KV → 保留
    ])
    pairs = extract_xfund_pairs(doc)
    values = [a for _, a in pairs]
    assert "营运部主管" in values
    assert any("一般" in v for v in values)
    assert not any("□" in v for v in values)
    assert not any("紧急" == v.lstrip("□√ ") for v in values)  # 未勾选的"紧急"不在


def test_long_paragraph_values_excluded():
    from benchmarks.multimodal_eval.build_suite import extract_xfund_pairs

    doc = _doc([
        ("工作职责", "对公司经营管理的全过程进行计划执行和控制。对各门店日常经营行为执行指导、协调和监督职能。"),
        ("拟到岗日期", "2020年9月1日"),
    ])
    pairs = extract_xfund_pairs(doc)
    assert [a for _, a in pairs] == ["2020年9月1日"]


def test_symbol_only_and_short_values_excluded():
    from benchmarks.multimodal_eval.build_suite import extract_xfund_pairs

    doc = _doc([("备注", "——"), ("性别", "无"), ("姓名", "夏艳辰")])
    pairs = extract_xfund_pairs(doc)
    assert [a for _, a in pairs] == ["夏艳辰"]
