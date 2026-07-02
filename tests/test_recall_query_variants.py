"""召回查询变体扩展:千分位与字符间空格伪影不再导致检索 miss。

dev 评测实证的两种真实存储形态(审计底稿逐字忠实,不可改写,只能查询侧兜底):
- VLM 把金额转写为 "¥731,000"  → FTS token [731][000],查 "731000" 原本 miss
- VLM 字符间空格伪影 "P O - 2 0 2 6 - 9 5 6 1" → 单字符 token,查 "PO-2026-9561" 原本 miss
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "recall.db"))


def test_digit_grouping_variant_matches_comma_formatted_amount(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from mase_tools.memory.db_core import add_event_log, search_event_log

    add_event_log("t", "system", "订单总额: ¥731,000 (含税)")
    hits = search_event_log(["731000"], limit=5)
    assert hits and "731,000" in hits[0]["content"]


def test_char_spaced_variant_matches_vlm_spacing_artifact(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from mase_tools.memory.db_core import add_event_log, search_event_log

    add_event_log("t", "system", "采购订单 P O - 2 0 2 6 - 9 5 6 1 供应商: 泰岳智造")
    hits = search_event_log(["PO-2026-9561"], limit=5)
    assert hits and "9 5 6 1" in hits[0]["content"]


def test_latin_word_spacing_artifact(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from mase_tools.memory.db_core import add_event_log, search_event_log

    add_event_log("t", "system", "T i a n s h a n 项目二期预算核定为 ¥58,200。")
    hits = search_event_log(["Tianshan"], limit=5)
    assert hits


def test_exact_match_still_first_and_unaffected(tmp_path, monkeypatch):
    """特征钉:正常文本的既有检索行为不变。"""
    _isolate(tmp_path, monkeypatch)
    from mase_tools.memory.db_core import add_event_log, search_event_log

    add_event_log("t", "user", "budget approved 4200 EUR for phoenix")
    hits = search_event_log(["phoenix"], limit=5)
    assert hits and "phoenix" in hits[0]["content"]
    assert search_event_log(["nonexistent-token-xyz"], limit=5) == []


def test_variant_expansion_through_public_recall_api(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_search_memory, mase2_write_interaction

    mase2_write_interaction("t", "system", "价税合计：¥86,400 开票日期：2026-05-13")
    hits = mase2_search_memory(["86400"], limit=5)
    assert any("86,400" in str(h.get("content", "")) for h in hits)
