from __future__ import annotations

import json
import os
import re
from typing import Any

from .adaptive_verify import AdaptiveVerifyPolicy
from .model_interface import ModelInterface


def adaptive_verify_decision(
    retrieval_score: float,
    candidates: list[dict],
    qtype: str | None = None,
) -> str:
    """Verifier 深度选择钩子。

    默认返回 ``"single"`` 维持现有行为；只有设置 ``MASE_ADAPTIVE_VERIFY=1``
    时才查询 :class:`AdaptiveVerifyPolicy`。因此调用方即使包住 verifier
    链路，只要开关未开启也不会改变行为。
    """
    if os.environ.get("MASE_ADAPTIVE_VERIFY", "0") != "1":
        return "single"
    return AdaptiveVerifyPolicy().decide(retrieval_score, candidates, qtype)

# ---------------------------------------------------------------------------
# 兼容旧接口：少量回归测试和 legacy_archive/orchestrator.py 仍会导入这些 helper。
# 重构后的 Router 将关键词工作交给 LLM，因此旧的“从问题抽关键词”钩子现在只返回
# FULL_QUERY 哨兵，等价于“让搜索层直接使用原问题”。_should_force_search_memory
# 同样退化为 False，因为是否强制检索已由 planner 接管。
# ---------------------------------------------------------------------------

FULL_QUERY_SENTINEL = "__FULL_QUERY__"

# LangGraph 编排器在消耗 LLM 跳数前，会用这组关键词做 search_memory/direct_answer
# 快速预判。下面的 RouterAgent.decide 仍是权威路由；这里是延迟优化用的预过滤器。
# 两条路径都必须从这里导入，确保关键词 fast-path 与 LLM prompt 保持一致。
MEMORY_TRIGGER_PHRASES: tuple[str, ...] = (
    "之前", "上次", "刚才", "刚刚", "早先",
    "记得", "还记得", "提到过", "告诉过", "说过",
    "我们讨论", "我们聊", "我们说",
    "那个", "那条", "那次",
    "我的",
)


def keyword_router_decision(query: str) -> str:
    """LangGraph 编排器使用的关键词快速路由。"""
    return "search_memory" if any(p in query for p in MEMORY_TRIGGER_PHRASES) else "direct_answer"


def _extract_keywords_from_question(question: str) -> list[str]:
    """旧接口桩：对所有输入返回 FULL_QUERY 哨兵。"""
    return [FULL_QUERY_SENTINEL]


def _should_force_search_memory(question: str) -> bool:
    """旧接口桩：新 planner 已接管该决策。"""
    return False


def filter_keywords(keywords: list[str]) -> list[str]:
    """旧接口桩：过滤空值和 FULL_QUERY 哨兵。"""
    return [k for k in (keywords or []) if k and k != FULL_QUERY_SENTINEL]


ROUTER_SYSTEM = """
你是路由智能体。你的唯一职责是判断用户问题是否需要查询历史对话记忆，并提取检索关键词。

### 决策规则（严格遵守）

必须判定为 direct_answer 的情况：
- 要求你执行任务：写代码、做数学题、翻译、总结当前文本、生成内容
- 询问通用知识：什么是XX、如何做XX、XX的定义
- 实时信息：今天天气、现在几点、最新新闻
- 闲聊：你好、谢谢、再见

必须判定为 search_memory 的情况：
- 明确指向过去对话：之前聊的、上次说的、你刚才提到、还记得吗、我们讨论过
- 询问具体已告知的信息：那个预算多少、端口号是什么、项目代号叫啥

### 关键词提取规则（仅当 search_memory 时）
1. 提取问题中最核心的中文名词短语，不超过3个。
2. 优先提取：项目代号、数字相关短语、专有名词、配置项名称。
3. 如果问题本身很模糊（如“那个方案”），直接使用原词作为关键词。

### 输出格式（严格 JSON）
{"action": "search_memory", "keywords": ["关键词1", "关键词2"]}
或
{"action": "direct_answer", "keywords": []}

### 示例
用户："写一个快速排序的Python代码"
输出：{"action": "direct_answer", "keywords": []}

用户："我们之前聊的那个Q3预算，线上投放比例是多少？"
输出：{"action": "search_memory", "keywords": ["Q3预算", "线上投放"]}

用户："服务器端口是多少？"
输出：{"action": "search_memory", "keywords": ["服务器端口"]}

用户："请把“先验证假设，再扩大投入”改写成更适合给老板看的汇报口吻。"
输出：{"action": "direct_answer", "keywords": []}

用户："如果仓储迁移项目要做灰度切换，你会优先监控哪两个指标来判断是否继续推进？"
输出：{"action": "direct_answer", "keywords": []}

只返回 JSON。
"""


def parse_router_response(content: str) -> dict[str, Any]:
    """容错解析 Router 的 JSON 输出。"""
    cleaned = content.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 最后一层降级：从非严格 JSON 文本里提取 action/keywords 字段。
    action_match = re.search(r'"action"\s*:\s*"([^"]+)"', cleaned)
    keywords_match = re.search(r'"keywords"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)

    action = action_match.group(1) if action_match else "direct_answer"
    keywords: list[str] = []
    if keywords_match:
        keywords = re.findall(r'"([^"]+)"', keywords_match.group(1))[:3]

    if action not in {"search_memory", "direct_answer"}:
        action = "direct_answer"

    return {"action": action, "keywords": keywords}


class RouterAgent:
    """面向 LangGraph 的轻量 Router Agent，判断是否需要查询历史记忆。"""

    def __init__(self, model_interface: ModelInterface) -> None:
        self.model_interface = model_interface

    def decide(self, user_question: str, system_prompt: str | None = None) -> dict[str, Any]:
        """返回路由决策：``search_memory`` 或 ``direct_answer``。"""
        if not user_question.strip():
            return {"action": "direct_answer", "keywords": []}

        prompt_to_use = system_prompt or ROUTER_SYSTEM

        response = self.model_interface.chat(
            "router",
            messages=[
                {"role": "user", "content": user_question}
            ],
            override_system_prompt=prompt_to_use,
        )

        content = response["message"]["content"]
        route = parse_router_response(content)

        if not isinstance(route.get("keywords"), list):
            # 外部模型偶尔会把 keywords 生成为字符串；对调用方统一成列表契约。
            route["keywords"] = []

        return route
