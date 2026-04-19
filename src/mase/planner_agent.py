from __future__ import annotations

from .model_interface import ModelInterface

PLANNER_SYSTEM = """
你是 MASE 的编排 Planner。你的职责是分配任务，不是回答问题。

硬性规则：
1. 绝对不能直接给出最终答案。
2. 绝对不能引入记忆中不存在的新实体、新数字、新日期、新结论。
3. 只输出执行步骤，描述“先做什么、再做什么、最后验证什么”。
4. 如果已有记忆，步骤必须围绕“检索事实 -> 压缩证据 -> 执行/验证”展开。
5. 如果没有相关记忆，只能写“direct answer path”，不能代替执行器作答。

输出要求：
- 最多 4 行
- 每行一个步骤
- 不要解释，不要举例，不要写最终答案
"""

class PlannerAgent:
    def __init__(self, model_interface: ModelInterface | None = None):
        self.model_interface = model_interface

    def plan(self, query: str, memory_context: str, mode: str | None = "task_planning") -> str:
        if not self.model_interface:
            # 简单回退机制
            if memory_context and "无相关记忆" not in memory_context:
                return "1. 结合查找到的记忆。\n2. 直接回答用户问题。"
            return "直接基于常识回答问题。"

        prompt = f"用户问题: {query}\n\n相关记忆:\n{memory_context}\n\n请输出你的计划："
        
        response = self.model_interface.chat(
            "planner",
            messages=[{"role": "user", "content": prompt}],
            mode=mode,
            override_system_prompt=PLANNER_SYSTEM
        )
        return response["message"]["content"].strip()

DEFAULT_PLANNER = PlannerAgent()
