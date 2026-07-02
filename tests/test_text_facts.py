"""text_facts:从既定文本抽事实的公共第二段(视觉/音频共用)。"""
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


def test_extracts_facts_with_agent_and_prompt():
    from mase.multimodal.text_facts import extract_facts_from_text

    reply = json.dumps({"facts": [{"category": "finance_budget", "key": "total", "value": "15.00",
                                   "confidence": 0.9, "evidence": "TOTAL 15.00"}]})
    fake = FakeModelInterface([reply])
    facts, warnings, model = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="SYS", text="RECEIPT\nTOTAL 15.00",
    )
    assert fake.calls[0]["agent_type"] == "doc_facts"
    assert fake.calls[0]["override_system_prompt"] == "SYS"
    assert "TOTAL 15.00" in fake.calls[0]["messages"][0]["content"]
    assert [f.key for f in facts] == ["total"]
    assert warnings == [] and model == "fake-llm"


def test_chunks_long_text_at_line_boundaries():
    from mase.multimodal import text_facts
    from mase.multimodal.text_facts import extract_facts_from_text

    # 每行 "line-i " + 50 字 = 57 字符(+1 换行);300 上限 → 5+5 = 2 块
    lines = "\n".join(f"line-{i} " + "长" * 50 for i in range(10))
    replies = [json.dumps({"facts": []})] * 2
    fake = FakeModelInterface(replies)
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
            assert line.startswith("line-")  # 不劈开行


def test_malformed_reply_retried_once_with_corrective_hint():
    """非法 JSON 触发一次纠正性重试(追加提示改变输入);重试成功则事实照常入库。"""
    from mase.multimodal.text_facts import extract_facts_from_text

    good = json.dumps({"facts": [{"category": "general_facts", "key": "k", "value": "v",
                                  "confidence": 0.5, "evidence": "e"}]})
    fake = FakeModelInterface(["not json", good])
    facts, warnings, _ = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="S", text="content",
    )
    assert len(fake.calls) == 2
    # 重试输入必须带纠正提示(temp=0 下原输入只会得到同样的坏输出)
    assert "JSON" in fake.calls[1]["messages"][0]["content"]
    assert [f.key for f in facts] == ["k"]
    assert "non_json_response(recovered_on_retry)" in warnings


def test_malformed_reply_degrades_after_failed_retry():
    from mase.multimodal.text_facts import extract_facts_from_text

    fake = FakeModelInterface(["not json", "still not json"])
    facts, warnings, _ = extract_facts_from_text(
        fake, agent_type="doc_facts", system_prompt="S", text="t",
    )
    assert len(fake.calls) == 2
    assert facts == []
    assert "non_json_response" in warnings
