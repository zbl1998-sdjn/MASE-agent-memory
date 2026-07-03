"""text_facts:从既定文本抽事实的公共第二段(视觉/音频共用)。

P6 起输出契约为管道行格式(category | key | value | evidence):
7B 模型对行格式的稳定性远高于嵌套 JSON(dev 实证:中文表单 7/10 案例
JSON 崩溃且重试无效);行格式同时比 JSON 更人眼可读(白盒)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class FakeModelInterface:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
        self.calls.append({"agent_type": agent_type, "messages": messages,
                           "override_system_prompt": override_system_prompt})
        return {"message": {"role": "assistant", "content": self.replies.pop(0)}, "model": "fake-llm"}


def test_parses_pipe_line_facts():
    from mase.multimodal.text_facts import extract_facts_from_text

    reply = "\n".join([
        "finance_budget | total | 15.00 | TOTAL 15.00",
        "junk line without pipes",
        "general_facts | company | RESTORAN HASSAN | RESTORAN HASSAN",
    ])
    fake = FakeModelInterface([reply])
    facts, warnings, model = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="SYS", text="RECEIPT",
    )
    assert [(f.category, f.key, f.value) for f in facts] == [
        ("finance_budget", "total", "15.00"),
        ("general_facts", "company", "RESTORAN HASSAN"),
    ]
    assert facts[0].evidence == "TOTAL 15.00"
    assert warnings == [] and model == "fake-llm"


def test_json_reply_still_accepted_for_compat():
    """模型若仍输出旧 JSON 契约,兼容解析(迁移期零破坏)。"""
    from mase.multimodal.text_facts import extract_facts_from_text

    reply = json.dumps({"facts": [{"category": "general_facts", "key": "k", "value": "v",
                                   "confidence": 0.5, "evidence": "e"}]})
    facts, warnings, _ = extract_facts_from_text(
        FakeModelInterface([reply]), agent_type="doc_facts", system_prompt="S", text="t",
    )
    assert [f.key for f in facts] == ["k"] and warnings == []


def test_explicit_empty_marker_is_not_retried():
    from mase.multimodal.text_facts import extract_facts_from_text

    fake = FakeModelInterface(["无事实"])
    facts, warnings, _ = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="S", text="装饰页",
    )
    assert facts == [] and warnings == [] and len(fake.calls) == 1


def test_unparseable_reply_retried_once_then_degrades():
    from mase.multimodal.text_facts import extract_facts_from_text

    fake = FakeModelInterface(["I think this document...", "still prose"])
    facts, warnings, _ = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="S", text="t",
    )
    assert len(fake.calls) == 2
    assert "|" in fake.calls[1]["messages"][0]["content"]  # 重试带格式纠正提示
    assert facts == []
    assert "unparseable_response" in warnings


def test_retry_recovery_recorded():
    from mase.multimodal.text_facts import extract_facts_from_text

    fake = FakeModelInterface(["prose only", "general_facts | k | v | e"])
    facts, warnings, _ = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="S", text="t",
    )
    assert [f.key for f in facts] == ["k"]
    assert "unparseable_response(recovered_on_retry)" in warnings


def test_chunks_long_text_at_line_boundaries():
    from mase.multimodal import text_facts
    from mase.multimodal.text_facts import extract_facts_from_text

    # 每行 "line-i " + 50 字 = 57 字符(+1 换行);300 上限 → 5+5 = 2 块
    lines = "\n".join(f"line-{i} " + "长" * 50 for i in range(10))
    fake = FakeModelInterface(["无事实"] * 2)
    orig = text_facts.TEXT_FACTS_CHUNK_CHARS
    text_facts.TEXT_FACTS_CHUNK_CHARS = 300
    try:
        _, warnings, _ = extract_facts_from_text(fake, agent_type="doc_facts", system_prompt="S", text=lines)
    finally:
        text_facts.TEXT_FACTS_CHUNK_CHARS = orig
    assert len(fake.calls) == 2
    assert "chunked: 2 parts" in warnings
    for call in fake.calls:
        for line in call["messages"][0]["content"].splitlines():
            assert line.startswith("line-")
