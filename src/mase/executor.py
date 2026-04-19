from __future__ import annotations

from .model_interface import ModelInterface


class ExecutorAgent:
    def __init__(self, model_interface: ModelInterface) -> None:
        self.model_interface = model_interface

    def execute(self, query: str, memory_context: str) -> str:
        """
        Takes the user query and the retrieved memory context, 
        and formulates a response using the LLM.
        """
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
            return f"【系统提示】调用大模型生成回复时出现异常: {str(e)}"
