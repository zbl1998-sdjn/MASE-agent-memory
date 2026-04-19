# MASE — Twitter / HN Launch Copy

发布前把 `docs/assets/nolima_3way_lineplot.png` 作为主图。

---

## 🐦 Twitter (X) — 3 行版本

```
We just lifted a 7B local model from 1.79% → 60.71% on NoLiMa-32k.

No fine-tuning. No frontier model. Just a chunked-recall architecture that survives where context windows die.

MASE — schema-less SQLite memory, ~zero hallucination, 84.8% LongMemEval.
github.com/<your-handle>/MASE-demo
```

**附图**: `docs/assets/nolima_3way_lineplot.png`

---

## 🟠 Hacker News — 标题候选 (按吸引力排序)

1. **Show HN: MASE — A 7B local model survives 32k NoLiMa at 60% with chunked recall**
2. **Show HN: Schema-less SQLite memory for LLM agents — git-diffable, no vector DB**
3. **MASE — Lifting a 7B model from 1.79% to 60.71% on NoLiMa without fine-tuning**

**正文 (~150 词)**:

```
MASE is a memory-augmented architecture for LLM agents. Two design choices:

1. Storage = SQLite + per-day Markdown. No vector DB, no schema, no hidden state.
   Users can `SELECT / UPDATE / DELETE` their own memory. Engineers can
   `git diff` to see how memory evolved (tri-vault layout opt-in).

2. Long context = chunked recall, not bigger windows. On NoLiMa needle-in-
   haystack at 32k context, a vanilla qwen2.5:7b scores 1.79% (window
   truncates the needle). Same model under MASE chunked pipeline: 60.71%.
   No fine-tuning, no model swap.

Honest numbers (LLM-judge):
  - LV-Eval EN 256k: 88.71% (vs 4.84% baseline)
  - NoLiMa 32k:      60.71% (vs 1.79%)
  - LongMemEval-S:   84.8%  (on par with frontier API models)

LongMemEval is NOT our primary target — it assumes full history fits in the
context window, which sidesteps MASE's whole point. We publish the number
because it's where the field looks. NoLiMa is where MASE actually wins.

Repo, reproducible runs, all source: github.com/<your-handle>/MASE-demo
```

---

## 📌 Reddit r/LocalLLaMA — 标题 + TL;DR

**标题**: `MASE — chunked recall takes qwen2.5:7b from 1.79% → 60.71% on NoLiMa-32k (no fine-tuning)`

**TL;DR**:
- 本地 7B 模型 + SQLite 记忆层 + 分块召回
- 突破 ollama 8K context 截断，长上下文 needle-in-haystack 大幅提升
- 完整白盒：内存就是 .db + .md 两种文本格式，可以 SELECT、可以 git diff
- 一个 30 行 demo 演示 Ctrl-C 重启后的持久化记忆 (`examples/10_persistent_chat_cli.py`)
- 84.8% LongMemEval 与 GPT-4o / Claude 3.5 / Gemini 1.5 Pro 同档 — 但**不是**主战场，主战场是长上下文窗口

---

## 🎯 一图流要点 (绘制者用)

如果要单独给 NoLiMa 图加 caption:

```
"Same 7B model, two architectures.
 Vanilla long-context: dies at 32k (1.79%).
 MASE chunked recall: holds 60.71% — a 34× lift,
 without fine-tuning or a bigger model."
```

---

## ✅ Pre-publish checklist

- [ ] GitHub repo public + topic 标签 `llm`, `memory`, `long-context`, `agent`
- [ ] README banner image 存在 (`docs/assets/banner.png`)
- [ ] NoLiMa 3-way 对比图存在 (`docs/assets/nolima_3way_lineplot.png`) ✅
- [ ] LICENSE 文件 (Apache-2.0 / MIT)
- [ ] `examples/10_persistent_chat_cli.py` 跑一次 GIF 录屏 (可选但加分)
- [ ] 第一条 issue 自己开：`Welcome — start here, what to read first`
- [ ] HN 发布时间窗口：周二/周三 美西早上 8:30am
