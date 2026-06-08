"""跨项目整合探针:验证 MASE 能否给 Agent Cowork 当"跨轮记忆"。

模拟场景:
  第1轮 用户告诉 Agent 一件事(写进 MASE)
  第2轮 用户问相关问题 —— 用新 prompt 去 MASE 取记忆,
        看吐出的文本能不能直接塞进 Agent Cowork 的 memoryText 插槽。

跑法:python examples/98_cowork_bridge_probe.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="mase_bridge_")) / "demo.db"
from mase_tools.memory import db_core  # noqa: E402

db_core.DB_PATH = _TMP
db_core.init_db()

from mase_tools.memory import api  # noqa: E402


def make_memory_text(query_keywords: list[str]) -> str:
    """模拟 Agent Cowork agent-stream.ts 那一步:
    取 MASE 记忆 → 拼成喂给 memoryText 插槽的文本。
    """
    facts = api.mase2_get_facts()
    hits = api.mase2_search_memory(query_keywords, limit=3)
    lines = []
    if facts:
        lines.append("【当前事实】")
        for f in facts:
            lines.append(f"- {f['category']}.{f['entity_key']} = {f['entity_value']}")
    if hits:
        lines.append("【相关历史】")
        for h in hits:
            tag = "[FACT]" if h.get("id") is None else f"[{h['id']}]"
            lines.append(f"- {tag} {h['content']}")
    return "\n".join(lines)


print("=" * 60)
print("  第 1 轮:用户告诉 Agent 一件事")
print("=" * 60)
api.mase2_write_interaction("t1", "user", "这个项目的部署目标是 Kubernetes，命名空间用 mase-prod")
api.mase2_upsert_fact("project_status", "deploy_target", "Kubernetes / namespace=mase-prod")
print("  已写入 MASE。")

print("\n" + "=" * 60)
print("  第 2 轮:用户换个问题(新 run,Agent Cowork 本来看不到第1轮)")
print("=" * 60)
new_prompt = "把部署脚本整理一下"
print(f"  用户新 prompt: {new_prompt}")
print("  → 用 prompt 关键词去 MASE 取记忆,拼成 memoryText:\n")

memory_text = make_memory_text(["部署", "deploy", "Kubernetes"])
print("-" * 60)
print(memory_text)
print("-" * 60)
print("\n  ↑ 这段文本可直接塞进 Agent Cowork 的 memoryText 插槽")
print("    (system-prompt.ts:99 '工作区记忆')——第2轮就'记得'第1轮说的部署目标。")
print(f"\n  demo db: {_TMP}")
