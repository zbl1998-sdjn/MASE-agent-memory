# LlamaIndex Integration

把 MASE 当作 LlamaIndex 的 `BaseMemory`.

## 安装

```bash
pip install llama-index-core
```

## 用法

```python
from llama_index.core.agent import ReActAgent
from llama_index.llms.openai import OpenAI
from integrations.llamaindex.mase_memory import MASELlamaMemory

memory = MASELlamaMemory()
agent = ReActAgent.from_tools(
    tools=[...],
    llm=OpenAI(model="gpt-4o-mini"),
    memory=memory,
)
agent.chat("我喜欢爬山")
agent.chat("推荐周末活动")  # MASE 自动注入"爬山"作为 context
```
