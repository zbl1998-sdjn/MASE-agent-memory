<div align="center">

# MASE
**A dual-whitebox memory engine for LLM agents.**
**88.71% on LV-Eval 256k with a local 7B model.**

> 🚫 **拒绝向量黑盒。把 Agent 记忆重新变成可读、可改、可验证的工程系统。**
> SQLite 负责结构化事实，Markdown / tri-vault 负责人类可读审计。
> **先治理记忆，再喂模型上下文。**

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![Tests](https://img.shields.io/badge/tests-69%2F69%20passing-brightgreen)
![Concurrency](https://img.shields.io/badge/concurrency-battle--tested-orange)
![NoLiMa-32k](https://img.shields.io/badge/NoLiMa--32k-60.71%25%20(%2B58.9pp)-red)
![LongMemEval](https://img.shields.io/badge/LongMemEval--S-84.8%25-blueviolet)

<b>中文</b> | <a href="docs/README_en.md">English</a>

![MASE vs baseline on NoLiMa long-context (3-way comparison)](docs/assets/nolima_3way_lineplot.png)

</div>

## What MASE Is

MASE 是一个**双白盒 Agent 记忆引擎**。

它不把记忆默认建在向量数据库之上，而是把 Agent 记忆拆成两类更可控的对象：

- **Event Log**：保留原始对话与检索入口
- **Entity Fact Sheet**：保存最新、可覆盖的结构化事实

这意味着 MASE 关注的首先不是“如何把更多上下文塞回模型”，而是：
**如何把冲突事实治理干净，再把最小必要事实交给模型。**

## Why Not Black-Box Memory

MASE 反对把 Agent 记忆默认做成黑盒向量召回，原因很简单：

1. **事实会更新，不是只会堆积。**
2. **记忆如果不可检查，就不可调试。**
3. **长上下文问题首先是上下文治理问题，而不只是窗口大小问题。**

## How MASE Works

MASE 的主叙事是记忆系统，不是 runtime 功能列表。

- **L1: SQLite + FTS5**：负责事件流水账与结构化事实检索
- **L2: Markdown / tri-vault**：负责人类可读、可迁移、可审计的记忆外化
- **Entity Fact Sheet**：新事实覆盖旧事实，避免冲突事实并存
- **Runtime Flow**：Router → Notetaker → Planner → Action → Executor，用来实现这套记忆引擎

## Evidence

| Benchmark | Model | MASE | Naked baseline | Δ |
|---|---|---|---|---|
| LV-Eval EN 256k | qwen2.5:7b local | **88.71%** | **4.84%** | **+84pp** |
| NoLiMa ONLYDirect 32k | qwen2.5:7b local, MASE chunked | **60.71%** | **1.79%** | **+58.9pp** |
| LongMemEval-S 500 | GLM-5 + kimi-k2.5 二号意见 + LLM-judge | **84.8%** (424/500) | **70.4%** | **+14.4pp** |

> LongMemEval 上报两条计分通道（详见 `docs/benchmark_claims/`）：
> - 84.8% (424/500) — LLM-judge, full_500 combined lane
> - 61.0% (305/500) — official substring-comparable lane

这三组数字分别证明：

- MASE 不只是“能记”，还能在长上下文里稳定提纯事实
- 架构本身，而不是模型参数量，决定了长上下文是否可用
- 它不是实验室概念稿，而是已经被 benchmark 和审计反复打磨过的工程项目


## Quick Start

```bash
git clone https://github.com/zbl1998-sdjn/MASE.git
cd MASE
pip install -e ".[dev]"
python -m pytest tests/ -q
python mase_cli.py
```

如果你只是第一次上手，优先跑 `python mase_cli.py`。
更完整的 benchmark 复现命令请看 [BENCHMARKS.md](BENCHMARKS.md)，
完整示例列表请看 [examples/README.md](examples/README.md)。

## Integrations
- LangChain `BaseChatMemory`
- LlamaIndex `BaseMemory`
- MCP server（Claude Desktop / Cursor）
- OpenAI-compatible endpoint

```python
from integrations.langchain.mase_memory import MASEMemory
memory = MASEMemory(thread_id="zbl1998::main", top_k=8)
agent_executor.invoke({"input": "我上次说的预算是多少？"}, config={"memory": memory})
```

## Limitations

MASE 当前最强的是**事实更新、跨 session 记忆、一致性治理、白盒可调试性**。

它目前不是通用语义检索终局方案，尤其在以下场景仍有边界：

- 同义词 / 近义表达驱动的强语义泛化
- 需要大规模文档级语义召回的场景
- 高并发服务端运行时（当前主路径仍偏 CLI / benchmark / 单进程）

## Roadmap

- 白盒语义检索（write-time tags / read-time expansion / FTS + LLM filtering）
- 更成熟的 async / server-grade runtime
- 更多 benchmark triangulation
- 更多集成面（LangChain / MCP / OpenAI compat 之外）

## Contributing

欢迎 issue / PR，尤其欢迎：

- 新模型后端适配
- 新 benchmark 复跑
- 新 integration
- 真实世界的长记忆失败样例

### Citation

```bibtex
@software{mase2026,
  author = {zbl1998-sdjn},
  title = {{MASE}: Memory-Augmented Smart Entity — Schema-less SQLite memory for LLM agents},
  year = {2026},
  url = {https://github.com/zbl1998-sdjn/MASE},
  note = {Lifts qwen2.5:7b from 1.79\% to 60.71\% on NoLiMa-32k; 84.8\% on LongMemEval-S}
}
```

## 💡 写在最后 (A Note from the Developer)

坦白讲，我只是一个**接触大模型仅 3 个月的新手**。

在探索 AI 的过程中我深刻地意识到：当人们面对一个深不可测、强大到宛如黑盒的 AI 个体时，**内心的恐惧往往要大于惊喜**。我们害怕它悄悄篡改记忆，害怕它产生无法理解的幻觉，害怕失去控制权。

这正是 MASE 放弃拥抱庞大黑盒、选择“双白盒”的初衷。在这个系统里：

> **没有无所不能的“个人英雄主义”，只有各司其职的“齐心协力”。**

我们不要求一个单一的巨型模型面面俱到，而是让 2.72 MB 的轻量级核心串联起 **Router / Notetaker / Planner / Action / Executor** 五个节点，让每个小模型各有所长，交织运作。正因为 MASE 保持了极简架构，它反而为未来的生态扩展（多智能体协同、MCP 接入、插件化）预留了无限可能。

**开源的魅力就在于不需要一个人做到完美。** 如果你也认同这种透明、极简、协作的理念，欢迎加入 MASE。我们一起，各有所长，搭好这个稳固的地基。

— *zbl1998-sdjn, 2026 春*
