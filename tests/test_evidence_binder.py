"""evidence_binder 机械证据定位行为测试(P0 T2)。

定位语义:先精确 substring;再"空白/换行差容忍"(归一化后命中映射回原文偏移);
不做字符级模糊。定位失败返回 None,由调用方降级 quarantined。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_exact_substring_hit_returns_source_offsets():
    from mase.governance.evidence_binder import locate_evidence

    source = "发票号 INV-88\n供应商 宏远贸易\n总额 4200 元"
    evidence = "供应商 宏远贸易"
    span = locate_evidence(evidence, source)
    assert span is not None
    start, end = span
    assert source[start:end] == evidence


def test_whitespace_difference_quote_compact_source_spaced():
    # VLM 底稿常见字符间空格伪影:引用写紧凑形,原文是空格散排。
    from mase.governance.evidence_binder import locate_evidence

    source = "P O - 2 0 2 6 采购单\n合计 1 2 3 4 5"
    span = locate_evidence("PO-2026", source)
    assert span is not None
    start, end = span
    assert source[start:end] == "P O - 2 0 2 6"


def test_whitespace_difference_quote_spaced_source_compact():
    from mase.governance.evidence_binder import locate_evidence

    source = "订单号PO-2026总额12345"
    span = locate_evidence("PO - 2026", source)
    assert span is not None
    start, end = span
    assert source[start:end] == "PO-2026"


def test_cross_line_quote_hits():
    from mase.governance.evidence_binder import locate_evidence

    source = "项目 甲\n总额\n4200 元"
    span = locate_evidence("总额 4200", source)
    assert span is not None
    start, end = span
    assert "总额" in source[start:end] and "4200" in source[start:end]


def test_absent_evidence_returns_none():
    from mase.governance.evidence_binder import locate_evidence

    assert locate_evidence("不存在的引文", "发票总额 4200") is None


def test_blank_evidence_returns_none():
    from mase.governance.evidence_binder import locate_evidence

    assert locate_evidence("", "任意原文") is None
    assert locate_evidence("   \n ", "任意原文") is None


def test_char_level_fuzz_is_not_tolerated():
    # 只容忍空白差,不做编辑距离:数字不同不许命中。
    from mase.governance.evidence_binder import locate_evidence

    assert locate_evidence("总额 4201", "总额 4200") is None


def test_build_span_produces_hash_of_source_hit():
    from mase.governance.evidence_binder import build_span

    source = "供应商 宏远贸易\n总额 4 2 0 0 元"
    span = build_span(
        "总额 4200",
        source,
        source_type="media_extraction",
        source_id="17",
        trust_level=4,
    )
    assert span is not None
    assert span.evidence_id.startswith("ev_")
    assert span.source_type == "media_extraction"
    assert span.source_id == "17"
    assert span.trust_level == 4
    assert span.span_start is not None and span.span_end is not None
    matched = source[span.span_start : span.span_end]
    assert span.quote_hash == hashlib.sha256(matched.encode("utf-8")).hexdigest()
    assert span.quote_excerpt == matched
    assert span.created_at  # 非空时间戳


def test_build_span_truncates_excerpt_to_200_chars():
    from mase.governance.evidence_binder import build_span

    long_hit = "甲" * 300
    source = f"前言 {long_hit} 后记"
    span = build_span(long_hit, source, source_type="file", source_id="a.txt", trust_level=5)
    assert span is not None
    assert span.quote_excerpt is not None and len(span.quote_excerpt) == 200
    # 哈希仍是完整命中段的哈希,excerpt 只是人读摘要。
    import hashlib as _h

    assert span.quote_hash == _h.sha256(long_hit.encode("utf-8")).hexdigest()


def test_build_span_returns_none_when_not_located():
    from mase.governance.evidence_binder import build_span

    assert (
        build_span("不存在", "原文", source_type="memory_log", source_id="1", trust_level=5)
        is None
    )
