# LangChain Integration

把 MASE 当作 LangChain 的 `BaseChatMemory`, 一行替换 `ConversationBufferMemory`.

## 安装

```bash
pip install langchain langchain-core
# MASE 本体已安装; 这个集成是纯 Python adapter
```

## 用法

```python
from langchain_openai import ChatOpenAI
from langchain.chains import ConversationChain
from integrations.langchain.mase_memory import MASEMemory

llm = ChatOpenAI(model="gpt-4o-mini")
memory = MASEMemory()  # ← 一行替换 ConversationBufferMemory

chain = ConversationChain(llm=llm, memory=memory)
chain.predict(input="我叫小明, 喜欢爬山")
chain.predict(input="我爱吃辣")
chain.predict(input="周末推荐?")  # MASE 自动把"小明 / 爬山 / 辣"作为 context 注入
```

## 优势 vs LangChain 默认 memory

| 维度 | `ConversationBufferMemory` | `MASEMemory` |
|------|----------------------------|--------------|
| 持久化 | 内存, 重启丢 | SQLite, 永不丢 |
| 长上下文 | 全量回灌, token 爆 | BM25 召回相关片段 |
| 跨 session | ❌ | ✅ |
| 用户可干预 | ❌ | ✅ (mase_cli.py CRUD) |
| 抗对抗性上下文 | ❌ | ✅ |
