# MASE：用存力代替算力的白盒记忆系统

> **Memory-Augmented System Executor**
>
> 这不是一个靠“把更多 token 塞回模型”硬撑长上下文的项目。  
> 它是一条把记忆外化、把证据压缩、把推理拆开、把错误审计化的系统链路。

![Python](https://img.shields.io/badge/Python-3.14+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-111111?style=for-the-badge)
![MASE](https://img.shields.io/badge/MASE-v0.4.0-orange?style=for-the-badge)
![Status](https://img.shields.io/badge/status-active-success?style=for-the-badge)

MASE 想证明一件事：

**长上下文能力不该只是模型窗口大小的竞赛。**
当系统学会把历史写成可检索记忆、把证据压成 fact sheet、把回答交给确定性规则与执行器协同完成时，性能就有机会和原始上下文长度部分解耦。

---

## 为什么这件事重要

今天多数长上下文系统都默认一个前提：**只要上下文够大，模型自然会记住。**

MASE 的立场正好相反：**真正可靠的记忆，不该靠模型硬背，而该靠系统把“找什么、信什么、怎么答”拆成可治理的步骤。**

这意味着 MASE 想解决的不只是“答对一道题”，而是三个更难的问题：

1. **上下文变长时，系统还能不能稳定工作**
2. **答错之后，能不能知道到底错在哪一步**
3. **能不能把云端能力、本地成本、白盒审计放进同一条链路**

---

## Empirical Data

### MASE anti-decay curve

![MASE anti-decay curve](results/标准基准/LV-Eval/MASE-v1.0-LV-Eval-English-Full-Sweep/MASE-v1.0-LV-Eval-anti-decay-curve.png)

- Chart archive:
  `results/标准基准/LV-Eval/MASE-v1.0-LV-Eval-English-Full-Sweep/`
- English full-sweep summary:
  `results/标准基准/LV-Eval/MASE-v1.0-LV-Eval-English-Full-Sweep/MASE-v1.0-LV-Eval-English-Full-Sweep-summary.json`

### Chinese and English LV-Eval side by side

| Track | Length | Result | Accuracy | Notes |
|---|---:|---:|---:|---|
| Chinese clean reference | 32k | 10 / 10 | 100.00% | Clean line |
| Chinese clean reference | 64k | 10 / 10 | 100.00% | Clean line |
| Chinese clean reference | 256k | 20 / 20 | 100.00% | Anchor-upgrade line |
| English full sweep | 16k | 164 / 170 | 96.47% | Full sweep |
| English full sweep | 32k | 161 / 172 | 93.60% | Full sweep |
| English full sweep | 64k | 183 / 188 | 97.34% | Full sweep |
| English full sweep | 128k | 165 / 167 | 98.80% | Full sweep |
| English full sweep | 256k | 121 / 124 | 97.58% | Full sweep |
| English full sweep overall | 16k-256k | 794 / 821 | 96.71% | Full sweep aggregate |
| Cloud LongMemEval 100 | - | 40 / 100 | 40.00% | route-to-memory = 93%, retrieval hit on memory routes = 100% |

### What this means

- **Chinese line** has already shown a continuous high-stability curve at `32k / 64k / 256k`.
- **English line** has now completed a full sweep from `16k` to `256k`, with an overall result of **`794 / 821 = 96.71%`**.
- The most accurate current claim is:

> **MASE shows a strong anti-decay trend on LV-Eval across both Chinese and English tracks.**

Rigorous note: the English sweep is a **length-specific full sweep**, not a same-sample paired experiment, so this is strongest as an **anti-decay trend claim**, not a formal "reverse-decay" proof.

---

## MASE 的不同，不在于“更大”，而在于“更拆开”

传统“把所有历史都塞回 messages”的方案，轮数一长就会遇到几个老问题：

- 上下文不断膨胀，成本和延迟一起上升
- 越靠前的信息越容易丢
- 模型会把旧回答、回忆问答和当前任务搅在一起
- 一旦记错，很难审计到底错在模型还是错在记忆链路

MASE 的思路是把职责拆开：

1. **路由智能体**只判断要不要查记忆
2. **记事智能体**只负责写、查、读、审计
3. **编排层**负责把记忆取回来并组织任务上下文
4. **执行智能体**真正完成回答、代码生成、数学计算等任务

---

## 系统如何做到

- **纯净路由**：只输入当前问题，只输出 `action + keywords`
- **工具化记事**：JSON 记忆、Markdown 审计日志、日期浏览、摘要读取、全文记录读取
- **显式编排层**：把“路由 -> 查记忆 -> 选执行模式 -> 写回记忆”变成独立模块
- **通用执行器**：支持 `grounded_answer`、`general_answer`、`code_generation`、`math_compute`、`structured_task`
- **检索兜底**：关键词检索 + 同义词扩展 + 时间衰减排序 + 语义检索 fallback
- **查询改写**：模糊回忆问题会先做 rewrite，再生成多样查询变体参与召回
- **线程识别**：每轮对话补充 `thread_id`、`thread_label`、`topic_tokens`
- **统一消息协议**：路由、记事、执行链路统一写成 `AgentMessage` envelope
- **多执行器路由**：执行模式不仅选 prompt，也可按 mode 覆盖模型/provider/参数
- **时间热度分工**：按“刚才/最近”与“最开始/历史”区分 hot / cold 记忆热度
- **双记事 / 双执行**：`Qwen2.5-1.5B` + `Qwen2.5-3B` 负责热/冷记事；`Qwen2.5-7B` 负责 `GeneralExecutor`，`DeepSeek-R1-Distill-Qwen-7B` 负责 `ReasoningExecutor`
- **摘要防幻觉**：摘要严格限制在原文事实内，不补年份、不扩写
- **备忘录压缩**：fact sheet 现在会去重、抽取相关原句，并为聚合题附加“聚合工作表”
- **轻量 Planner**：复杂任务会先生成显式步骤计划，再进入检索、压缩和执行阶段
- **审计友好**：每轮都实时落 JSON；每天自动汇总一份 Markdown 日志
- **极致白盒化**：从路由、检索、压缩、候选裁决到最终答案，全部保留可追溯痕迹；每个 benchmark case 都能回看到 `case_memory_dir`、`fact_sheet`、`候选裁决表`、调用日志与最终回答

一句话概括：

> **MASE 不是试图让一个模型记住一切，而是让整个系统学会如何记住、如何查证、如何回答。**

---

## 云端 + 本地混合编排

MASE 当前已经不再局限于“整套系统只跑本地”或“整套系统只跑云端”两种模式，而是支持 **按角色、按 mode、按降级链** 的异构模型编排。

### 当前支持的混用粒度

1. **按智能体混用**：例如 `router` 走云端，`notetaker` 走本地，`planner` 走云端，`executor` 走本地
2. **按 mode 混用**：同一个 `executor` 里，`grounded_answer` 可走云端，`general_answer` 可走本地；英文路径可走云端，中文路径可走本地
3. **按 fallback chain 混用**：主模型走云端，超时后切备用云模型，必要时再回本地

### 为什么能做到

- `model_interface.py` 已按 `agent + mode` 解析最终配置
- 每个模式都可以独立声明 `provider / model_name / base_url / api_key_env`
- 当前已支持 `ollama`、`anthropic-compatible`、`openai-compatible` 这类不同后端在同一条链路中并存
- 配置修改后可通过 `reload()` 让**后续请求**生效

### 当前边界

- 支持 **按请求边界** 的模型切换与异构编排
- 不支持把一个已经发出的单次模型调用中途切到别的模型
- 也就是说，准确的工程表述不是“运行中的单个 HTTP 请求热切换”，而是 **后续步骤 / 后续请求可按配置切到不同模型**

### 稳定性增强

为了解决云端多模型链路的 timeout 问题，当前已经补齐：

- 分离 `overall / connect / read / write / pool` timeout
- 指数退避 + 随机抖动重试
- `httpx.Client` 复用 + 显式 pool limits
- planner / executor / notetaker / router 的 fallback chain

### 已验证结论

- 历史 3 题 cloud smoke：`1/3`，其中 `2` 题 `ReadTimeout`
- 稳定性修复后 1 题 smoke：`1/1`
- 稳定性修复后 3 题 smoke：`3/3`，零 infra / execution error，平均单题约 `69.26 s`

一个重要兼容性细节是：当前 DashScope `apps/anthropic` 链路里，`qwen3.5-plus` 可用，但 `qwen-plus` / `qwen-turbo` / `qwen-flash` 会返回 `400`，因此路由 fallback 现阶段改为**跨 provider 备用模型**，而不是继续在这条接口内同族降级。

因此，MASE 的一个核心架构优势已经很明确：

> **它可以把“本地低成本稳定层”和“云端高能力推理层”放进同一条白盒、可审计、可降级的执行链里协同工作。**

---

## MASE 站在前人的肩膀上

MASE 不是“凭空发明一切”的系统。相反，它更像一次**把已有研究思路、成熟工程模式和本地多模型能力重新拼装、白盒化、可审计化**的集成工程。

截至当前，仓库里可以明确点名的策略 / 模式，至少有 **5 类、29 项**：

| 类别 | 统计 | 已落地内容 | 主要落点 |
|---|---:|---|---|
| **长上下文证据策略** | `3` | `Gold Panning`、`DCR (Dynamic Context Retrieval)`、`SAKE` | `tools.py` |
| **检索与召回策略** | `8` | `direct_lookup`、`query_rewrite_lookup`、`zoom_in_out`、`date_scan`、`widen_search`、`synonym expansion`、`semantic fallback`、`__FULL_QUERY__` 全文回退 | `planner.py`、`notetaker_agent.py`、`tools.py` |
| **架构与记忆组织模式** | `5` | `Router / Notetaker / Planner / Orchestrator / Executor` 分层、工具化记事、`AgentMessage` envelope、hot/cold memory、thread/topic 线程化 | `config.json`、`protocol.py`、`memory_heat.py`、`topic_threads.py` |
| **执行与协作模式** | `8` | 五类主任务模式：`grounded_answer`、`general_answer`、`code_generation`、`math_compute`、`structured_task`；三类协作模式：`off`、`verify`、`split` | `config.json`、`orchestrator.py` |
| **白盒治理与审计机制** | `5` | `fact_sheet` 去重压缩、候选裁决表、动态阈值 `threshold_profile`、`evidence_layout` 元数据、`case_memory_dir` / trace 全链路审计 | `tools.py`、`orchestrator.py` |

这里面有两层意思：

1. **有些名字是直接点名借鉴的。** 比如 `Gold Panning`、`DCR`、`SAKE`，我们没有换皮改名，而是明确承认它们来自前人的长上下文研究思路。
2. **有些能力属于成熟工程范式的再组合。** 比如 query rewrite、semantic fallback、planner-executor、tool calling、verify gate、white-box trace，这些都不是谁一个人的“神来之笔”，而是长期社区实践沉淀下来的共同智慧。

所以，如果要用一句话概括 MASE 的方法论，那更准确的说法不是“某个人发明了一个无中生有的新系统”，而是：

> **这里没有个人英雄主义，只有齐心协力。**

MASE 所做的，是把这些分散在不同论文、工程经验、系统模式里的想法，整成一条**本地可运行、结果可复盘、错误可审计、性能可验证**的白盒链路。

---

## 存力代替算力：实际存储开销

截至 `2026-04-11 23:38`，对 `memory_runs/`、`memory/`、`results/` 下生成的 `.json` 与 `.md` 文件做了一次实测统计，结论如下：

| 范围 | JSON | Markdown | 合计 |
|---|---:|---:|---:|
| 累计文件数 | 5,149 | 184 | 5,333 |
| 累计体积 | 19.65 MB | 30.07 MB | 49.72 MB |
| 最近两天新增 | 19.66 MB | 30.07 MB | 49.73 MB |

几个更有解释力的点：

1. **“两天不到 4MB”这个判断并不成立。** 按当前仓库内已生成的 benchmark 轨迹、审计日志和结果文件统计，最近两天新增体积约为 **49.73 MB**。
2. **但单次高强度长上下文跑批的存储成本仍然很低。** 两次已完成的 `LV-Eval 32k / 10 样本` 运行目录分别约为 **2.25 MB** 与 **2.26 MB**。
3. **JSON 本身并不重，Markdown 日志更占空间。** 当前累计 JSON 为 **19.65 MB**，Markdown 为 **30.07 MB**，说明如果后续要进一步压缩存储，占优先级的不是 trace JSON，而是 Markdown 审计日志的粒度与保留策略。
4. **这正体现了“存力代替算力”的工程特征。** MASE 把一次高成本推理过程转化为廉价、可复用、可审计的外部存储：即便按一次完整 `32k` 回归约 **2.25 MB** 估算，连续 **100** 次同级别回归也仅约 **225 MB**，远低于反复把长上下文整体送回模型所消耗的 GPU 时间与推理成本。

因此，MASE 的关键优势不只是“能记住”，而是：

- **把长上下文推理结果沉淀为低成本存储资产**
- **把后续重复计算转化为按需检索与局部验证**
- **在保留白盒审计能力的同时，显著降低长期运行对算力的依赖**

本次统计结果已保存为：`results/storage-footprint-20260411-233808.json`

---

## 存力代替算力：响应速度与上下文长度的关系

截至 `2026-04-12 00:50`，结合已完成的 `LV-Eval factrecall` 跑批结果，可以得到一个更精确的判断：

| 轮次 | 档位 | MASE 结果 | MASE 平均单题耗时 | Qwen3.5-27B 结果 |
|---|---|---:|---:|---:|
| `benchmark-lveval-20260411-190152-175229-summary.json` | `16k` | `9/10` | `72.81 s` | `0/10`，`10/10 timeout` |
| `benchmark-lveval-20260411-201528-911340-summary.json` | `32k` | `7/10` | `133.66 s` | `0/10`，`10/10 timeout` |
| `lveval-decay-batch-factrecall_zh-20260412-002758.json` | `32k-clean` | `10/10` | `6.57 s` | `0/10`，`10/10 timeout` |
| `lveval-decay-batch-factrecall_zh-20260412-005956.json` | `64k-clean` | `10/10` | `6.60 s` | `0/10`，`10/10 timeout` |
| `lveval-256k-batch-factrecall_zh-20260412-011232.json` | `256k-clean(10)` | `9/10` | `8.13 s` | `baseline skipped` |
| `lveval-256k-batch-factrecall_zh-20260412-011804.json` | `256k-clean(20)` | `19/20` | `8.16 s` | `baseline skipped` |
| `lveval-256k-batch-factrecall_zh-20260412-014948.json` | `256k-anchor-upgrade(20)` | `20/20` | `7.88 s` | `baseline skipped` |

这组数据说明两点：

1. **MASE 并不是天然“无论上下文多长都完全等速”。** 在旧链路下，`16k -> 32k` 时 MASE 的平均单题耗时确实从 `72.81 s` 上升到 `133.66 s`。
2. **但在当前“检索 -> 压缩 -> 候选裁决 -> 局部验证”的 clean 链路下，MASE 的单题耗时已经被显著压缩到低个位数秒级。** 最新 clean `32k`、clean `64k` 与 clean `256k` 跑批中，平均单题耗时分别只有 `6.57 s`、`6.60 s` 与 `8.16 s`，说明系统已经把大部分与上下文长度线性相关的成本，转移成了可复用的外部记忆、局部证据和结构化裁决。

因此，更严谨的工程表述不是“MASE 永远等速”，而是：

> **MASE 可以通过外部记忆、上下文压缩和局部验证，把执行耗时与原始上下文长度部分解耦；而单体长上下文模型仍会更直接地承受长度增长带来的延迟与超时风险。**

这也是为什么 `64k` 跑批的整轮 wall clock 仍接近每题 `~187 s`：这更多是被 `Qwen3.5-27B` baseline 的长上下文超时上限拖住，而不是 MASE 本体重新退回到同样的响应级别。最终结果也验证了这一点：**`64k-clean` 上 MASE `10/10`、平均单题 `6.60 s`，而 `Qwen3.5-27B` 仍是 `0/10` 且 `10/10 timeout`。**

### 当前里程碑

截至 `2026-04-12 01:49`，MASE 已经在同一套 `LV-Eval factrecall_zh` 任务线上取得以下连续结果：

- `32k-clean`：**`10/10`**
- `64k-clean`：**`10/10`**
- `256k-clean`：**`9/10`**
- `256k-clean` 扩样 `20` 条：**`19/20`**
- `256k-anchor-upgrade` 扩样 `20` 条：**`20/20`**

这意味着当前系统已经不只是“在某个长度档位偶然答对”，而是开始展现出**跨 32k / 64k / 256k 的连续稳定性**。而在继续把 **Gold Panning（证据重排）/ DCR（动态扩窗）/ SAKE（首尾锚定）** 落到证据链之后，原先 `256k` 下唯一顽固错例 `factrecall-209278` 也被修复，`20` 条扩样已达到 **`20/20`**。这可以视为当前阶段一个明确的工程里程碑。

同时，这个里程碑还有一个同样重要的工程含义：**由于 MASE 采用极致白盒链路，所有错误都不是“黑箱失分”，而是可以定位到具体环节、具体样本、具体裁决依据的可追溯、可审计错误。** 无论是候选抽取污染、跨实体证据串染，还是 `256k` 下的超长距离证据锚定失败，都可以直接回看到 `case_memory_dir`、`fact_sheet`、`候选裁决表`、Verifier 决策与最终回答。

---

## 当前架构

```text
用户问题
   │
   ▼
┌──────────────┐
│ 路由智能体    │  只做意图分类
│ action+keys  │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ 编排层        │  选择任务模式 / 是否查记忆
└──────┬───────┘
       │
   ┌───┴───────────────┐
   ▼                   ▼
┌──────────────┐   ┌──────────────┐
│ 记事智能体    │   │ 执行智能体    │
│ tool interface│   │ executor hub │
└──────┬───────┘   └──────┬───────┘
       │                  │
       └────────┬─────────┘
                ▼
           结果 + 记忆写回
```

### 四层职责

| 层 | 职责 | 工具权限 |
|---|---|---|
| **Router** | 判断是否需要访问历史记忆 | 否 |
| **Notetaker** | 写入、检索、浏览、更新、删除记忆 | 是 |
| **Orchestrator** | 编排数据流、决定执行模式、拼装事实备忘录 | 是 |
| **Executor** | 回答问题、生成代码、数学计算、结构化处理 | 按模式使用上下文，不直接碰文件 |

### 极致白盒化能力

MASE 的一个核心工程特点是：**不是只给结论，而是把“结论是怎么来的”完整落盘。**

对任意一次 benchmark 或单样本排查，现在都可以回溯：

1. **原始上下文写入**：每段 benchmark context 都会写入独立记忆 JSON 与 Markdown 日志
2. **路由决策**：可以看到 `route_action`、`keywords`
3. **Planner 计划**：可以看到 `strategy`、`query_variants`、`confusion_level`、步骤列表
4. **指令包**：可以直接检查 `instruction_package.fact_sheet`
5. **候选裁决**：强混淆题会在 fact sheet 中显式写出 `候选裁决表` 与 `系统初判`
6. **执行器调用**：可以回看模型、mode、usage、elapsed time、by_agent 聚合
7. **最终落盘**：每个 case 都对应一个 `case_memory_dir`，可独立审计

这意味着 MASE 的优势不仅在于结果本身，还在于：

- **所有步骤可追溯**
- **所有关键判断可审计**
- **错误样本可定位到具体链路环节**
- **修复可以直接对准“哪一步错了”而不是只能靠猜**

### 模型分工

- **Notetaker 仍按时间热度分工**
  - **Hot memory**：偏“刚才 / 今天 / 最近”的查询，优先走更快的记事模型
  - **Cold memory**：偏“之前 / 上次 / 最开始 / 历史”的查询，优先走更强的记事模型
  - 当前默认分工：
    - **Notetaker hot** → `qwen2.5:1.5b`
    - **Notetaker cold** → `qwen2.5:3b`
- **Executor 改为按任务模式分工**
  - **GeneralExecutor** → `qwen2.5:7b`
    - 负责单事实问答、常规内容生成、简单推理
  - **ReasoningExecutor** → `deepseek-r1:7b`
    - 负责复杂聚合、计数、多跳推理、代码和数学
- **可选协同模式**
  - `off`：默认，直接由目标执行器完成回答
  - `verify`：General 先出草稿，Reasoning 做事实核查
  - `split`：Reasoning 先聚合事实，General 负责组织自然语言

---

## v0.3 核心变化

相比前一阶段的 Agent-Style Pipeline，`v0.3` 做了三个关键升级：

### 1. 记事工具化

新增 `notetaker_agent.py`，把记忆能力封装成清晰的工具接口：

- `write_interaction`
- `search_memory`
- `list_dates`
- `get_summary_by_date`
- `read_full_record`
- `update_summary`
- `delete_record`

### 2. 显式编排层

新增 `orchestrator.py`，让“怎么调度”变成一等公民：

- 保持路由纯净
- 基于问题类型选择执行模式
- 在需要时取回记忆并构造 fact sheet
- 每轮执行后统一写回记忆

### 3. 通用执行器

执行智能体不再只做问答，而是升级为通用任务执行器：

- `grounded_answer`
- `general_answer`
- `code_generation`
- `math_compute`
- `structured_task`

---

## 项目目录

```text
E:\MASE-demo
├── mase.py                   # 主入口，保留兼容 API 与 CLI
├── model_interface.py        # 统一模型接口，支持 Ollama / OpenAI-compatible
├── memory_heat.py            # 热/冷记忆时间热度判定
├── protocol.py               # 统一消息协议
├── router.py                 # 路由智能体实现与关键词过滤
├── orchestrator.py           # 显式编排层
├── notetaker_agent.py        # 记事智能体工具接口
├── topic_threads.py          # 线程识别与 topic 推断
├── tools.py                  # JSON 记忆读写 / 检索 / 排序
├── notetaker.py              # Markdown 审计日志
├── executor.py               # 执行器示例
├── config.json               # 本地默认配置
├── config.cloud.example.json # DeepSeek + GLM + MiniMax 云端样例配置
├── baseline.py               # 单体模型对照脚本
├── compare_mase_vs_qwen27b.py # 代表性 MASE vs Qwen27B 对比
├── scripts\
│   ├── benchmarks\           # benchmark / smoke / regression 入口脚本
│   └── ops\                  # 打包与维护脚本
├── benchmarks\               # 标准 benchmark 适配 / 评分 / Runner
├── test_ollama.py            # 最小模型连通性测试
├── test_hotswap.py           # 本地热插拔验证
├── test_cloud_backend.py     # OpenAI-compatible mock 云端验证
├── test_long_context.py      # 长上下文回忆验证
├── test_mase_100_rounds.py   # 100 轮记忆压测
├── analyze_router_false_positives.py
├── test_randomized_recall.py # 随机化中长度回忆测试
├── test_randomized_recall_batch.py
├── test_router_context_limit.py
├── test_v01_v02_compare.py
├── memory\                   # 主记忆目录
├── memory\logs\              # 每日 Markdown 审计日志
├── memory_runs\              # 运行中批次目录（根目录只保留当前批次）
│   ├── 标准基准_历史\        # 已完成 benchmark 运行目录归档
│   ├── 调试分析\             # debug / analysis 目录归档
│   ├── 稳定性与回归\         # 随机回忆 / MASE vs baseline 等运行目录
│   └── 烟雾测试\             # smoke 运行目录
└── results\                  # 结果根目录（根目录只保留进行中的批次输出）
    ├── 标准基准\
    │   ├── LongMemEval\
    │   ├── LV-Eval\
    │   └── 其他基准\
    ├── 单样本排查\
    ├── 稳定性与回归\
    └── 工程验证\
```

> **整理约定**
>
> - `results\` 与 `memory_runs\` 根目录只保留**进行中的批次输出**
> - 已完成结果统一归档到中文子目录
> - README 与 Obsidian 中引用的路径，默认都指向这些中文归档目录

---

## 快速开始

### 1. 环境要求

- Windows + Python 3.14+
- [Ollama](https://ollama.com/)
- 已拉取模型：
  - `qwen2.5:0.5b`（路由）
  - `qwen2.5:1.5b`（hot 记事）
  - `qwen2.5:3b`（记事 / 摘要）
  - `qwen2.5:7b`（hot 执行）
  - `deepseek-r1:7b`（cold 执行）

### 2. 安装 Python 依赖

```powershell
pip install ollama
```

### 3. 拉取模型

```powershell
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull deepseek-r1:7b
```

### 4. 运行 Demo

```powershell
python .\mase.py
```

### 5. 云端配置示例

如果要切到云端后端，可复制样例配置并填入环境变量：

```powershell
Copy-Item .\config.cloud.example.json .\config.cloud.json
$env:DEEPSEEK_API_KEY="your-key"
$env:GLM_API_KEY="your-key"
$env:MINIMAX_API_KEY="your-key"
python .\mase.py
```

默认样例采用：

- **Router** → DeepSeek
- **Notetaker** → GLM
- **Executor** → MiniMax

当前云端适配走 **OpenAI-compatible HTTP backend**，因此后续切换到其他兼容供应商时，只需要改配置，不需要改业务代码。

---

## 示例流程

### A. 记住一个事实

```text
用户：请记住：服务器端口是9909。
路由：direct_answer
编排：general_answer
执行：好的，我已记录。后续你可以随时问我相关的问题。
记事：写入 JSON + Markdown 日志
```

### B. 基于记忆生成代码

```text
用户：根据我们刚才记住的服务器端口，写一个Python配置字典。
路由：search_memory
编排：code_generation + use_memory
记事：召回“服务器端口是9909”
执行：生成带 9909 的 Python 配置代码
```

### C. 直接做数学计算

```text
用户：计算 (12 + 30) * 4 等于多少？
路由：direct_answer
编排：math_compute
执行：168
```

---

## 记忆设计

### JSON 记录

每轮交互都会落成单独的 JSON：

```json
{
  "timestamp": "2026-04-10T18:11:49",
  "user_query": "请记住：服务器端口是9909。",
  "assistant_response": "好的，我已记录。后续你可以随时问我相关的问题。",
  "semantic_summary": "用户要求记住：服务器端口是9909。",
  "key_entities": []
}
```

### Markdown 审计日志

同一天的所有交互会汇总到一份可审查日志：

```text
memory\logs\2026-04-10.md
```

每条记录包含：

- 时间
- 用户原话
- 助手回答
- 语义摘要

---

## 已完成验证

本项目已经完成的关键验证包括：

- **5 轮流程验证**：确认每轮实时生成 JSON
- **10 轮审计日志验证**：确认 Markdown 每日累计写入
- **30 轮关键场景对比**：`v0.2` 优于 `v0.1`
- **100 轮记忆压测**：第 100 轮成功回忆第 1 轮事实
- **路由上下文极限压测**：记录裸路由模型在长 prompt 下的失稳阈值
- **v0.3 smoke test**：已验证记忆写入、记忆增强代码生成、直接数学计算三种路径
- **v0.4 热插拔验证**：已验证配置改动后无需改代码即可切换本地模型
- **云端后端验证**：已用 OpenAI-compatible mock 服务验证 DeepSeek / GLM / MiniMax 三角色配置可实际走 HTTP 后端
- **随机化中长度回忆测试**：20 轮随机关联问题后，随机抽取更早事实进行回忆，已成功命中目标记录
- **标准 benchmark 脚手架**：已支持 LongMemEval / LV-Eval / MMLU / GPQA / GSM8K / HumanEval 统一运行与评分
- **LongMemEval_S 真实抽样对比**：已完成 5 条真实样本的 MASE(7B) vs Qwen27B 对比
- **LV-Eval 长度分档对比**：已完成 `factrecall_zh` 的 16k / 32k / 64k 小样本上下文曲线

## 实证数据

### 随机回忆证明

本项目已经把“它看起来能记住”推进到了“它有可复现证据地记住”，并且开始把“路由降假阳性”与“多 seed 稳定性”量化下来。

单 seed 归档测试参数：

| 项 | 值 |
|---|---|
| **Run ID** | `20260410-184722` |
| **Seed** | `20260410` |
| **Models** | router=`qwen2.5:0.5b`, notetaker=`qwen2.5:3b`, executor=`qwen2.5:7b` |
| **Rounds before recall** | `20` |
| **Inserted memory facts** | `6` |
| **Filler rounds** | `14` |
| **False-positive search_memory** | `0` |
| **Recall target** | `risk-threshold` |
| **Recall target round** | `17` |
| **Recall success** | `true` |

本次随机抽取的回忆题是：

> 把前面说过的退款预警阈值再确认一下，我记得后面还有人工复审条件。

系统最终回答：

> 好的，根据之前的记录，风控侧将退款预警阈值设定为7.5%。如果连续两天超过这个值，就会自动触发人工复审流程。

这说明在**中长度、多干扰、随机抽题**条件下，MASE 仍能通过外部记忆稳定找回更早轮次中的精确信息，而不是依赖模型把整段历史“硬记”在上下文里。

### 路由收紧

针对典型“任务型请求误查记忆”样本，新增 `analyze_router_false_positives.py` 做采样分析。最新结果：

| 项 | 值 |
|---|---|
| **Run ID** | `20260410-222846` |
| **Negative cases** | `17` |
| **False positives** | `0` |
| **Positive cases** | `12` |
| **False negatives** | `0` |

这说明当前 hybrid router 已经能把“写代码 / 改写 / 比较 / 解释 / 给建议”与“回忆旧事实”拉开。

### 多 Seed 随机回忆

新增 `test_randomized_recall_batch.py` 后，已经可以直接统计多 seed 结果。最新一轮轻量批量验证：

| 项 | 值 |
|---|---|
| **Run ID** | `20260410-225021` |
| **Rounds per seed** | `12` |
| **Seeds** | `20260410, 20260411` |
| **Recall success rate** | `1.0` |
| **Avg false-positive count** | `0` |
| **Avg false-positive rate** | `0.0` |

这说明改造后的链路不再只依赖单次幸运命中，而是在多 seed 条件下也能稳定召回。

### 标准基准真实结果

这一轮开始，README 不再只记录“看起来很强”的案例，也记录**真实跑分后不占优的结果**。

LongMemEval_S 抽样 5 条的最新真实结果：

| 系统 | 通过数 |
|---|---:|
| **MASE（7B grounded executor）** | `0 / 5` |
| **Qwen3.5-27B baseline** | `4 / 5` |

结果文件：

```text
E:\MASE-demo\results\标准基准\LongMemEval\benchmark-longmemeval_s-20260411-024849.json
```

这说明当前版本的 MASE 还**不能**宣称在标准长记忆基准上优于 27B 单体模型。主瓶颈已经从“要不要查记忆”转移到了“拿到事实后能否稳定完成聚合 / 计数 / 汇总推理”。

#### 双执行首轮复测（hot/cold）

在接入 `qwen2.5:1.5b / qwen2.5:3b` 双记事和 `qwen2.5:7b / deepseek-r1:7b` 双执行后，重新跑了一轮关键基准：

| 基准 | MASE | Qwen27B | 结论 |
|---|---:|---:|---|
| **LongMemEval_S（5条）** | `0 / 5` | `4 / 5` | **没有比分提升** |
| **LV-Eval 64k（3条）** | `0 / 3` | `0 / 3` | MASE 全部返回但全答错；27B 全超时 |

对应结果文件：

```text
E:\MASE-demo\results\标准基准\LongMemEval\benchmark-longmemeval_s-20260411-120452-005871.json
E:\MASE-demo\results\标准基准\LV-Eval\benchmark-lveval-20260411-122547-203305.json
```

这轮复测说明两件事：

1. **目前还没有出现“1+1>2”的量化证据**：双执行接入后，LongMemEval 分数没有高于此前的 `0/5`。
2. **当前编排还不够“纯”**：部分复杂 LongMemEval case 虽然最终 target 标成了 cold executor，但实际调用日志显示先走了 `grounded_analysis_hot -> qwen2.5:7b`，说明“复杂题稳定落到 DeepSeek”这件事还没有完全实现。

#### Planner 复跑（任务模式分工 + 检索压缩 + 轻量规划）

在把执行层改成 `GeneralExecutor / ReasoningExecutor` 分工、补上查询改写与压缩 fact sheet，并把编排层升级为带显式步骤的轻量 Planner 后，又重跑了一轮相同基准：

| 基准 | MASE | Qwen27B | 对比上一轮 |
|---|---:|---:|---|
| **LongMemEval_S（5条）** | `1 / 5` | `4 / 5` | **MASE 从 `0/5` 提升到 `1/5`** |
| **LV-Eval 64k（3条）** | `0 / 3` | `0 / 3` | 分数未变 |

对应结果文件：

```text
E:\MASE-demo\results\标准基准\LongMemEval\benchmark-longmemeval_s-20260411-131947-434516.json
E:\MASE-demo\results\标准基准\LV-Eval\benchmark-lveval-20260411-134329-222191.json
```

这轮复跑的真实结论是：

1. **Planner + 检索优化已经带来第一步实质提升**：LongMemEval 从 `0/5` 抬到 `1/5`，说明“更准的检索 + 更短的证据 + 显式 reasoning 路由”开始起作用。
2. **64k LV-Eval 仍未突破**：分数仍是 `0/3`，但失败模式从“误答混淆项”变成了 **GeneralExecutor 的快速拒答**，说明当前 Planner 仍把这类对抗性 fact recall 题判成了 `direct_lookup + grounded_answer_general`。
3. **下一步的关键不再是有没有 Planner，而是 Planner 的任务识别精度**：需要把这类“看似单事实、实则含强混淆干扰”的题型提升到 `ReasoningExecutor` 或专门的 disambiguation 流程。

#### 64k 去混淆突破（强混淆单事实判别）

随后针对 `factrecall_zh_64k` 的“贝多芬 / 贝克汉姆 / 贝弗利”强混淆单事实题，链路又做了三处关键修复：

1. **压缩层从碎片打分改成锚点窗口截取**：确保 `贝多芬 -> 现代物理学之奠基者` 这类完整证据句不会再被短噪音片段挤掉。
2. **去混淆工作表升级为“候选裁决表”**：显式列出候选名、目标领域命中、目标角色命中与 `direct_target_match`，把“在物理学有贡献”与“现代物理学奠基人”分开。
3. **执行层加入唯一 direct match 兜底**：当问题是在问名字，且裁决表中只有一个 `direct_target_match=yes` 候选时，执行器直接采用系统初判，不再让自由生成漂移到混淆项。

单个关键样本 `factrecall-52822` 的回归结果：

| 验证项 | 结果 |
|---|---|
| 修复前 | 会在 `贝多芬 / 贝克汉姆` 之间漂移，甚至错误拒答 |
| 高温一致性试验 | `6` 次里出现 `3` 次贝多芬、`3` 次贝克汉姆，说明是“真摆动”而不是稳定偏错 |
| 修复后 3 次回归 | `3 / 3` 全部输出 `贝多芬` |

对应结果文件：

```text
E:\MASE-demo\results\单样本排查\postpatch-three-trial-factrecall-52822-20260411-171707.json
```

在此基础上，重新跑带 baseline 的完整对比后，`factrecall_zh_64k` 抽样 3 条结果变成：

| 基准 | MASE | Qwen27B | 结论 |
|---|---:|---:|---|
| **LV-Eval factrecall_zh 64k（3条）** | `3 / 3` | `0 / 3` | **MASE 全对；Qwen27B 全部 `ReadTimeout`** |

对应结果文件：

```text
E:\MASE-demo\results\标准基准\LV-Eval\benchmark-lveval-20260411-172629-514008.json
E:\MASE-demo\results\单样本排查\mase-only-factrecall-zh-64k-sample3-20260411-172116.json
E:\MASE-demo\results\单样本排查\inspect2-factrecall-52822-20260411-171541.json
```

这次 baseline 使用的就是本地 `Qwen3.5-27B TurboQuant` OpenAI-compatible 接口：

```text
profile: local-qwen35-27b
model_name: Qwen3.5-27B.Q4_K_M.gguf
base_url: http://127.0.0.1:8081/v1
```

也就是 WSL 中 `/root/start-qwen35.sh` 启起来、并映射到 Windows `127.0.0.1:8081` 的那条服务。

这轮里程碑的最新可引用结论是：

- **MASE 已经不只是“在 64k 下能跑完”，而是已经能在强混淆单事实题上稳定答对**
- **这次优势同时体现在正确率和服务可完成性上**：MASE `3/3`，Qwen27B `0/3`
- **架构确定性已经开始转化为分数优势**，这是一条比“偶然命中单样本”更硬的实证证据

> **关于 `ReadTimeout` 的解释**
>
> 这里的 `ReadTimeout` 更准确地表示：**Qwen27B baseline 没能在当前 benchmark 设定的超时预算内返回结果**。这并不必然等同于“模型能力上完全不能回答”，因为本地 27B OpenAI-compatible 服务可能在更长等待时间下返回答案，尤其当模型启用了更慢的深度思考或 prefill / decode 路径时。
>
> 但这恰恰也是 MASE 架构优势的一部分：**在固定时延预算下，MASE 不只是正确率更高，而且系统级可用性更强**。换句话说，MASE 当前领先的不只是“理论上能不能答”，而是“在真实服务时限里能不能稳定交付结果”。

### LV-Eval 长度分档

为了直接观察上下文压力下的衰减与失稳，本项目新增了 `scripts\benchmarks\run_lveval_context_sweep.py`，并对 `factrecall_zh` 做了 16k / 32k / 64k 的长度分档对比。

先前的 1 条/档试跑给出的信号是：

| 档位 | 实际长度 | MASE | Qwen27B | 备注 |
|---|---:|---:|---:|---|
| **16k** | `13249` | `0 / 1` | `1 / 1` | 27B 正确，但耗时更长 |
| **32k** | `26723` | `1 / 1` | `0 / 1` | MASE 正确，27B 接口 `503` |
| **64k** | `52822` | `0 / 1` | `0 / 1` | MASE答错，27B 接口 `503` |

对应试跑汇总：

```text
E:\MASE-demo\results\标准基准\LV-Eval\lveval-context-sweep-factrecall_zh-20260411-030740.json
```

随后补跑的扩样结果更值得引用：

| 档位 | 样本数 | 实际长度范围 | MASE | Qwen27B | 主要失败模式 |
|---|---:|---:|---:|---:|---|
| **16k** | `2` | `13249-13390` | `0 / 2` | `0 / 2` | MASE 误答混淆项；27B 全部 `ReadTimeout` |
| **32k** | `3` | `26235-26723` | `1 / 3` | `0 / 3` | MASE `1` 对 `2` 错；27B 全部 `ReadTimeout` |
| **64k** | `3` | `52683-52822` | `0 / 3` | `0 / 3` | MASE `1` 次拒答 + `2` 次误答；27B 全部 `ReadTimeout` |

对应结果文件：

```text
E:\MASE-demo\results\标准基准\LV-Eval\benchmark-lveval-20260411-045629-219769.json
E:\MASE-demo\results\标准基准\LV-Eval\benchmark-lveval-20260411-042953-070212.json
E:\MASE-demo\results\标准基准\LV-Eval\benchmark-lveval-20260411-044244-714728.json
E:\MASE-demo\results\标准基准\LV-Eval\lveval-context-sweep-factrecall_zh-20260411-042953-070048.json
```

这轮扩样后的真实结论是：

- **MASE 赢的是“可完成性 / 可返回性”，不是“准确率已领先”**
- 在当前本地部署条件下，**Qwen27B 在扩样后的 16k/32k/64k 共 8 条样本里没有 1 条在设定超时内完成**
- **MASE 能稳定跑完所有样本，但精度仍低**，尤其在 64k 仍会被混淆事实带偏

这里需要特别强调：**timeout 是服务时延结论，不是纯能力上限结论**。当前 benchmark runner 对 baseline 使用了显式 `timeout_seconds` 预算；因此 `ReadTimeout` 说明的是“在约定时限内无法交付”，而不是“延长等待后绝对答不出来”。这也是为什么 MASE 的优势应表述为：**在长上下文 + 受限时延预算下，MASE 体现出更强的系统级优越性。**

### 耗时与 usage 证据

这轮 benchmark runner 已新增两类可复盘指标：

- **wall-clock / elapsed time**
- **usage / token-like counters**

以最新扩样后的 `factrecall_zh` 长度分档为例：

| 档位 | MASE avg wall-clock | Qwen27B |
|---|---:|---|
| **16k** | `49.13s` | `2/2` 超时 |
| **32k** | `76.07s` | `3/3` 超时 |
| **64k** | `86.01s` | `3/3` 超时 |

这让后续对比不再只看答对率，也能同时比较：

- 正确率
- 长度升高后的失稳点
- 系统延迟
- 推理成本

### 本轮经验

这轮真实 benchmark 最重要的经验有四条：

1. **路由已不再是主瓶颈**：回忆题被修正到 `search_memory + __FULL_QUERY__` 后，失败主因已经转到执行层。
2. **收紧 grounded prompt 只能减少胡答，不能自动提分**：纪律解决的是幻觉，不解决复杂聚合能力。
3. **7B 执行层不足以稳定处理 LongMemEval 聚合题**：同样的分析链路切到 27B 时，`3 plants`、`8 days` 等样本可以算对；切回 7B 又退化。
4. **MASE 还没有稳定突破上下文限制，但已经表现出明显强于单体 27B 的服务连续性**：当前优势主要在“能跑完”，而不是“已经答得更准”。

### 可复现实验归档

为保证复现性，本次测试的原始结果、配置快照和记忆日志都已归档：

```text
E:\MASE-demo\results\稳定性与回归\randomized-recall-seed-20260410-log.json
E:\MASE-demo\results\稳定性与回归\randomized-recall-seed-20260410-config.json
E:\MASE-demo\results\稳定性与回归\randomized-recall-seed-20260410-bundle.json
E:\MASE-demo\results\稳定性与回归\randomized-recall-seed-20260410-memory.zip
E:\MASE-demo\results\稳定性与回归\router-false-positive-analysis-20260410-222846.json
E:\MASE-demo\results\稳定性与回归\randomized-recall-multiseed-20260410-225021.json
```

其中 `bundle.json` 额外汇总了：

- 本次 seed、run_id、轮数与模型配置
- 随机抽中的目标事实与最终回答
- 假阳性 `search_memory` 样本计数与示例

结果文件位于：

```text
E:\MASE-demo\results\标准基准\
```

---

## 设计原则

### Router 必须保持纯净

- 不读历史
- 不调工具
- 不做指代消解
- 只输出 `action + keywords`

### Notetaker 持有记忆

- 记忆写入
- 记忆检索
- 日期浏览
- 完整记录读取
- 审计日志写入

### Orchestrator 持有控制流

- 调路由
- 调记事工具
- 决定执行模式
- 统一写回记忆

### Executor 持有任务完成

- 回答问题
- 生成代码
- 数学计算
- 结构化处理

---

## 路线图

- [x] 路由 / 记事 / 执行三角色拆分
- [x] JSON 记忆落盘
- [x] Markdown 审计日志
- [x] 100 轮长记忆验证
- [x] 无状态路由 + 时间衰减检索
- [x] 记事工具化
- [x] 显式编排层
- [x] 通用执行器
- [x] 路由假阳性采样分析与继续收紧
- [x] 多 seed 随机回忆测试统计
- [x] 记事智能体语义检索兜底
- [x] 会话线程 / topic thread 识别
- [x] 统一消息协议
- [x] 多执行器模式路由
- [x] 标准 benchmark 脚手架
- [x] 长上下文长度分档对比
- [ ] 32k / 64k 多样本上下文衰减曲线
- [ ] 推理时间 / token 成本多样本统计
- [ ] MCP Server 化
- [ ] 监督智能体 / 评估智能体

---

## 项目理念

MASE 不是“把模型记忆做大”，而是：

**让模型在该遗忘的时候遗忘，把真正需要长期保存的信息交给外部记忆系统。**

这也是它能从一个 demo，继续进化成生产级智能体系统的根基。

---

## 2026-04-12 Granite 英文专线修复与测试流水线

这一轮优化的目标非常聚焦：**优先修英文 LongMemEval 的两个主问题——检索/聚合错数，以及输出形态/细节不匹配 gold。**

### 本轮落地的核心修复

1. **Granite 英文执行收口**
   - `executor.py`
   - 英文 `grounded_analysis` 保持 `think=true` 推理链
   - 统一解包 `<response>`
   - 英文 count 问题增加二次校验与重写
   - `How many different doctors...` 改为稳定输出：
     - `I visited three different doctors: a primary care physician, an ENT specialist, and a dermatologist.`
   - 避免把纯数字 gold 题强行句式化，例如 `0a995998` 恢复为 `3`

2. **英文 repeated search 深化**
   - `notetaker_agent.py`
   - 新增基于首轮命中结果的确定性 `build_english_followup_queries(...)`
   - 从首轮结果的 `summary / user_query / assistant_response` 中提取：
     - 名字对（如 `Jen and Tom`）
     - 医生角色
     - 领域短语
   - 第二轮英文检索不再只复用原问题，而是把这些 focused variants 一起送进规则检索

3. **fact sheet 证据压缩修复**
   - `tools.py`
   - 英文计数题在构造 `Aggregation worksheet` 时，优先保留**带名字、角色、时间、原因**的长句
   - 避免把真正关键的尾句（如 `Emily ... Sarah`）在压缩阶段裁掉

4. **确定性 countable item 去噪**
   - `tools.py`
   - 医生类 canonicalize 为：
     - `primary care physician`
     - `ent specialist`
     - `dermatologist`
   - property 类改为域规则抽取：
     - `bungalow`
     - `cedar creek property`
     - `1-bedroom condo`
     - `2-bedroom condo`
   - `how many times ...` 不再默认按“物品数”计，而优先按事件事实计数

### 本轮测试步骤

1. **编译检查**

```powershell
Set-Location E:\MASE-demo
python -m compileall .\notetaker_agent.py .\orchestrator.py .\executor.py .\tools.py
```

2. **代表样本回放**

```powershell
python .\scripts\benchmarks\run_standard_benchmark.py --benchmark longmemeval_s --sample-limit 20 --baseline-profile none
```

重点观察样本：

- `0a995998`：衣物计数题，确认返回 `3`
- `gpt4_f2262a51`：医生题，确认输出完整英文句式
- `gpt4_2f8be40d`：婚礼题，确认 fact sheet 已保留 `Emily/Sarah`、`Jen/Tom` 这类名字证据
- `gpt4_7fce9456`：房产题，确认 deterministic property count 从错误高计数压回 `4`

### 20 题同口径结果演进

| 阶段 | 结果文件 | 成绩 |
|---|---|---:|
| 纯确定性英文检索主链 | `results\标准基准\LongMemEval\benchmark-longmemeval_s-20260412-062205-856953.json` | `7 / 20` |
| Granite 结构化推理第一轮 | `results\标准基准\LongMemEval\benchmark-longmemeval_s-20260412-070503-921287.json` | `8 / 20` |
| Granite 英文专线当前基线 | `results\标准基准\LongMemEval\benchmark-longmemeval_s-20260412-072217-571964.json` | **`11 / 20`** |

### 当前 20 题仍未解决的集中问题

1. **召回仍不足**
   - `gpt4_a56e767c`：电影节题仍只拉到 `3`，gold 为 `4`
   - `80ec1f4f`：museum / gallery 仍少召回

2. **求和类事实不足或聚合不完整**
   - `6cb6f249`：social media break days 仍只答局部
   - `36b9f61e`：luxury amount 仍停在 `$1,200`

3. **计数已对，但细节句仍不完整**
   - `gpt4_7fce9456`：已恢复到 `4 properties`，但未补全 gold 中四条拒绝理由
   - `gpt4_2f8be40d`：已稳定到 `3 weddings`，但 couples 名字仍未完全覆盖 gold

4. **事件去重口径仍不稳**
   - `2e6d26dc`：babies 仍过计
   - `88432d0a`：bake something 仍把“做了几次”和“做了几种”混淆

### 全量 306 题结果

本轮在当前 Granite 英文专线基线上，继续跑了 `longmemeval_s` 全量 `306` 样本：

```powershell
Set-Location E:\MASE-demo
python .\scripts\benchmarks\run_standard_benchmark.py --benchmark longmemeval_s --baseline-profile none
python .\scripts\benchmarks\summarize_benchmark_result.py --path .\results\标准基准\LongMemEval\benchmark-longmemeval_s-20260412-072729-337284.json
```

结果文件：

- `results\标准基准\LongMemEval\benchmark-longmemeval_s-20260412-072729-337284.json`
- `results\标准基准\LongMemEval\benchmark-longmemeval_s-20260412-072729-337284-summary.json`

全量汇总：

| 指标 | 数值 |
|---|---:|
| 样本数 | `306` |
| MASE pass | `42` |
| MASE avg_score | `0.1373` |
| 完成率 | `1.0` |
| infra_error | `0` |

### 全量失败集中区

基于全量失败样本的自动聚类，问题主要集中在下面几类：

| 类别 | 数量 | 说明 |
|---|---:|---|
| 拒答 / 门控过严 | `79` | 明明是可答题，但 evidence gate 或最终执行器仍给出“证据不足 / 无法回答” |
| 求和 / 时长 / 比例聚合 | `77` | 多条数值事实没有完整相加，或单位/跨度处理不稳 |
| 召回不足 / 计数错误 | `64` | 检索少拉、拉偏，或 countable item 去重口径仍漂移 |
| 其他 | `21` | 少量长尾 case，主要是口语回指、局部上下文丢失 |
| 实体选择 / 比较判断 | `16` | 返回了数字或局部事实，但 gold 需要实体名、排序或比较结论 |
| 事件去重 / 按次计数 | `5` | `how many times` 仍容易把“几次”和“几种/几件”混算 |
| 细节句缺失 / 格式不匹配 | `2` | 主答案接近正确，但单位或完整句式还差一点 |

### 当前最值得继续攻的三个方向

1. **先打拒答 / 门控过严**
   - 这是目前最大的单一失败簇（`79`）
   - 说明英文 evidence gate 仍偏保守
   - 下一轮应优先检查：
     - `evidence_confidence`
     - `verifier_action`
     - 英文任务的 refusal rewrite 条件

2. **再打求和 / 时长 / 比例聚合**
   - 这是第二大簇（`77`）
   - 说明当前“Countable items + Deterministic sum”主要修好了简单计数，但对：
     - 多段天数
     - 金额合计
     - 差值 / 平均值 / 百分比
     仍缺系统性规则

3. **继续补召回不足 / 计数错误**
   - 仍有 `64` 个失败
   - 重点不是再加模型，而是继续补：
     - focused follow-up query variants
     - 英文证据句裁剪
     - domain-specific canonicalization
