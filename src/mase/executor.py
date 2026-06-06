"""LangGraph legacy executor wrapper。"""

from __future__ import annotations

from .model_interface import ModelInterface


class ExecutorAgent:
    """把 query 和 memory_context 交给 executor 模型生成最终回答。"""

    def __init__(self, model_interface: ModelInterface) -> None:
        self.model_interface = model_interface

    def execute(self, query: str, memory_context: str) -> str:
        """用检索到的记忆上下文回答用户问题。"""
        system_prompt = (
            "You are a helpful, intelligent assistant.\n"
            "You are provided with a user query and relevant memory context retrieved from the database.\n"
            "Please use the provided memory context to answer the user's query accurately and concisely.\n"
            "If the memory context does not contain the answer or is empty, "
            "answer to the best of your knowledge, but clarify that you don't have a specific memory of it if appropriate.\n"
        )

        user_message = f"Memory Context:\n{memory_context}\n\nUser Query: {query}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        try:
            response = self.model_interface.chat(
                agent_type="executor",
                messages=messages
            )
            content = response.get("message", {}).get("content")
            if content:
                return content
            return "【系统提示】模型未能返回有效内容。"
        except Exception as e:
            # legacy LangGraph 路径要求返回字符串，不向图外抛模型异常。
            return f"【系统提示】调用大模型生成回复时出现异常: {str(e)}"
