# MASE V2 — Benchmark Results

> **Status**: Living document. Numbers are auto-filled as new runs complete.
> Last updated: 2026-07-07(v0.16 全切片复测)

---

## TL;DR

A **7B local model** (`qwen2.5:7b`, native 32k context) reaches **88.7%** on
LV-Eval **256k** EN factrecall under the MASE architecture — *without ever
showing the model more than 16k tokens at once*.

The same 7B model **without MASE** (raw Ollama, full context truncated to
native 32k window) collapses on the same benchmark — quantifying the
contribution of the architecture itself.

| | LV-Eval EN 64k | LV-Eval EN 128k | LV-Eval EN 256k |
|---|---|---|---|
| **MASE + qwen2.5:7b(2026-07-07 v0.16 复测)** | **94.15%** | **89.22%** | **91.94%** |
| MASE + qwen2.5:7b(2026-04-19 首发) | 91.49% | 83.23% | 88.71% |
| Bare qwen2.5:7b (no MASE, 2026-04-19) | 22.34% | 10.78% | 4.84% |

> v0.16 复测(scripts/run_lveval_en_iter5.py,60.9min,同协议同模型标签):五切片零回退,
> 128k +6.0pp / 256k +3.2pp——4 月至今检索路径演进(fact sheet/notetaker/mode_selector)的红利。
> 裸基线未重跑:256k 内容结构性超出 32k 原生窗口,该失败与模型 blob 版本无关。
> 另:NoLiMa **ONLYDirect**(字面直接档)32k 同日复测 MASE chunked **96.43%**(54/56)
> vs 真裸基线 **0.0%**(0/56,任务 ≈36-40k qwen tokens 超出原生窗口,逐例截断记账)。
> 档位如实:ONLYDirect 问句与针字面重叠,关键词检索的主场,证明的是窗口突破而非潜在
> 联想;NoLiMa 反字面招牌档(onehop/twohop/Hard)关键词系统为 **0%**——2026-07-07
> v0.16 同协议复测 272 例全零(needle_set 0/116、hard 0/20,@16k 与 @32k 各一轮),
> 与 2026-04 committed 一致,见 docs/NOLIMA_3WAY.md。4 月裸基线 1.79% 系当时 runner
> 经 8k executor 截断的测量伪影,取证留痕于
> docs/benchmark_claims/evidence/nolima_32k_v016_refresh_summary.json。

> Model-swap runs are tracked as future work until completed; pending GLM-5
> numbers are intentionally excluded from the headline table.

> **Key claim**: MASE decouples *what the model can see* from *what the task
> requires*. Architecture, not raw window size, is the long-context lever.

---

## 1. LV-Eval — adversarial long-context fact recall

### 1.1 Chinese (qwen2.5:7b + iter5 meta-prompt + multipass)

| Slice | Pass rate |
|---|---|
| 16k | ~96% |
| 32k | ~95% |
| 64k | ~93% |
| 128k | ~91% |
| 256k | ~89% |

### 1.2 English (qwen2.5:7b + iter5 meta-prompt, multipass off)

**2026-07-07 v0.16 复测(当前口径,60.9min 全切片)**

| Slice | n | Pass | Pct |
|---|---|---|---|
| 16k | 170 | 165 | **97.06%** |
| 32k | 172 | 162 | **94.19%** |
| 64k | 188 | 177 | **94.15%** |
| 128k | 167 | 149 | **89.22%** |
| 256k | 124 | 114 | **91.94%** |

**2026-04-19 首发(历史)**

| Slice | n | Pass | Pct | Wall-clock |
|---|---|---|---|---|
| 16k | 170 | 165 | **97.06%** | 3.0min |
| 32k | 172 | 160 | 93.02% | 4.3min |
| 64k | 188 | 172 | 91.49% | 6.8min |
| 128k | 167 | 139 | 83.23% | 10.5min |
| 256k | 124 | 110 | 88.71% | 13.3min |

### 1.3 Bare-baseline ablation (qwen2.5:7b, no MASE)

> ✅ Complete (2026-04-19 08:25, 109.7 min total via
> `scripts/run_lveval_en_bare_baseline.py`).

| Slice | Bare 7B | MASE + 7B | **Δ** |
|---|---|---|---|
| 64k  | **22.34%** (42/188) | **91.49%** | **+69.15pp** |
| 128k | **10.78%** (18/167) | **83.23%** | **+72.45pp** |
| 256k | **4.84%** (6/124)  | **88.71%** | **+83.87pp** |

> **Reading**: 同样的 qwen2.5:7b base model, 同样的题目, 不上 MASE 时
> 64k 只到 22%, 128k 跌到 10.8%, 256k 崩到 4.8% — 裸模型在真正的长上下文
> 下面对"大海捞针"基本没能力. 上了 MASE 后, 三个切片稳定在 83-91%, 且越长
> 反而越稳 (256k > 128k 得益于 stem-prefix + memory gating).
>
> 这是 MASE 项目最核心的一张图: **长上下文表现的瓶颈不是模型参数量, 是上下文管理架构**. MASE 的检索 + 工作内存 + iron-rule prompt 能把 7B 推到远超其原生能力的位置, 而且窗口越大优势越显.

### 1.4 Future model-swap experiment (MASE + GLM-5 cloud)

Pending runs are kept out of published result tables until a full summary and
claim manifest evidence are available.

---

## 2. LongMemEval-S 500 — long-history conversational memory

> **Two scoring lanes are reported.** LongMemEval shipped with a *paragraph*
> ground-truth, so a literal substring match systematically penalises any
> answer that adds context, summarises the same fact in different words, or
> uses the official "did not mention" abstention template with extra detail.
> The official LongMemEval evaluator is therefore an LLM judge. We report
> **both** numbers so reviewers can choose:
>
> - **Substring** — pure keyword/phrase match. Floor; never wrong, often unfair.
> - **LLM judge** — same prompt as the official LongMemEval evaluator, run
>   through MASE's own kimi-k2.5 → deepseek → glm-4.6 fallback chain.
>   *Conservative*: only flips substring-FAIL → PASS, never the other way.
>
> Published claim manifests tracked under `docs/benchmark_claims/`.
> Anti-overfit policy and publishable-lane rules are documented in
> [`docs/BENCHMARK_ANTI_OVERFIT.md`](docs/BENCHMARK_ANTI_OVERFIT.md).

| Configuration | n | Substring % | **LLM-judge %** | Δ pp |
|---|---|---|---|---|
| **local v0.16 lane**(qwen2.5:7b 全本地,multipass+HyDE+rerank,2026-07-07) | 500 | **62.6** | 待云端复评 | — |
| GLM-5 baseline (no multipass, no verifier) | 500 | 70.4 | **72.4** | +2.0 |
| iter1 (multipass)                          | 500 | 69.4 | **72.4** | +3.0 |
| **best stable run** (multipass + length-aware) | 500 | 75.4 | **77.2** | +1.8 |
| **iter2 (multipass + kimi-k2.5 verifier)** | 500 | 61.0 | **🏆 80.2** | **+19.2** |
| iter3 dev_250 (type-aware verifier, partial 54) | 54 | 64.8 | **83.3** | +18.5 |
| iter4 combined/retry diagnostic | 500 | — | 84.8 | post-hoc diagnostic, not headline |

> **Headline lanes** (tracked in `docs/benchmark_claims/longmemeval.json`):
> - 61.0% (305/500) — official substring-comparable lane
> - 80.2% (401/500) — LLM-judge lane on the same iter2 full_500 run
>
> The 84.8% combined/retry result is retained as a diagnostic reference only.
> It is not the public headline because post-hoc retry lanes carry higher
> overfitting risk.

**Why iter2's substring score collapsed to 61%**: the kimi-k2.5 verifier
rewrites the executor's draft into its own phrasing (often correctly adding
context like *"You did not mention the iPad. You mentioned Sony WH-1000XM4
headphones."*). That richer phrasing **passes the official LLM judge** but
**fails substring matching** because the GT keyword string changed. iter2
verifier is therefore reported on both lanes: 61.0% for official substring
comparability and 80.2% for the LLM-judge lane.

> Reproduce: `python scripts/rescore_with_llm_judge.py <result_file>` walks
> any benchmark result and emits a `*.rescored.json` plus a side-by-side
> summary. The judge is the same kimi-k2.5+fallback used elsewhere — no
> extra dependencies.

### Failure breakdown of GLM-5 baseline

| Question type | Failures | Share of total fails |
|---|---|---|
| temporal-reasoning | 56 | 37.8% |
| multi-session | 47 | 31.8% |
| knowledge-update | 20 | 13.5% |
| (other) | 25 | 16.9% |

> ⇒ 70% of failures are reasoning-over-evidence rather than retrieval misses.
> Iter2 attacks this with an independent cloud verifier (kimi-k2.5) checking
> date arithmetic and multi-session aggregation.

---

## 3. LongBench-v2 short — cross-document multi-choice

> Honest finding: **at the 7B reasoning ceiling**.

| Run | Pass rate (n=30) |
|---|---|
| Single pass (T=0.0) | 30~33% |
| ctx bump to 32k | 23.3% (worse) |
| Self-consistency vote (3×) | 23.3% |

3 temperatures produce identical *wrong* answers — self-consistency cannot
recover. Matches Llama3.1-8B official (30.0%). Marked for cloud-tier
upgrade (kimi-k2.5 200K) in a future round.

---

## 4. Reproduction

```powershell
# 1. setup
git clone <repo>
cd MASE-demo
pip install -e .

# 2. local LV-Eval EN (full sweep, ~40 min on a 4090)
python scripts/run_lveval_en_iter5.py

# 3. cloud LongMemEval-500 (GLM-5 baseline)
$env:GLM51_API_KEY = '<your-key>'
python scripts/run_lme_glm5.py

# 4. ablation: bare 7B (no MASE)
python scripts/run_lveval_en_bare_baseline.py

# 5. ablation: MASE + GLM-5 (model swap)
python scripts/run_lveval_en_glm5_swap.py
```

Each script writes a JSON summary into `scripts/_*.json`.
Set `MASE_RUNS_DIR` to keep new runtime outputs outside the repository root;
for example, `MASE_RUNS_DIR=E:/MASE-runs` redirects benchmark result JSON to
`E:/MASE-runs/results` and per-case memory stores to `E:/MASE-runs/memory_runs`.

---

## 5. Methodology notes

- **Datasets**: LV-Eval (Tencent) factrecall_en/zh slices; LongMemEval-S 500
  (official); LongBench-v2 short subset (n=30).
- **No leaks**: judging is rule-based string match (LV-Eval) or LLM-judge
  upgrade for synonym/abstain handling (LongMemEval). All env-gated changes
  are validated with regression runs against prior watermarks.
- **No qid-bucket routing in publishable lanes**: LongMemEval routing may use
  general `question_type` metadata for analysis, but runtime verifier selection
  no longer branches on benchmark-specific question-id prefixes/suffixes.
  See [`docs/BENCHMARK_ANTI_OVERFIT.md`](docs/BENCHMARK_ANTI_OVERFIT.md).
- **Provenance and external checks**: new benchmark summaries include dataset
  fingerprints and an anti-overfit run protocol. Use
  `python scripts/benchmarks/run_generalization_regression.py --official-max-only`
  for external BAMBOO/NoLiMa regression checks, and
  `generalization_smoke` only as a fast non-public integration sanity check.
  For failed external runs, generate a conservative bucketed failure report with
  `python scripts/benchmarks/summarize_external_failures.py`; bucket definitions
  live in [`docs/EXTERNAL_GENERALIZATION_FAILURE_REPORT.md`](docs/EXTERNAL_GENERALIZATION_FAILURE_REPORT.md).
- **Hardware**: dual 4090 (one for ollama LLM, one for bge-reranker-v2-m3).
  Cloud runs use api.deepseek.com / api.bigmodel.cn / api.kimi.com.

---

## 6. Roadmap (post-headline)

1. Iter3 LongMemEval: question-type aware prompt routing → target ≥85%.
2. Cloud-tier LongBench-v2 (kimi-k2.5 200K).
3. Add RULER and LongBench-v1 sweeps for triangulation.
4. Modular memory plugins (math, code, multimodal) — architecture is hot-swap
   ready (3 env-gated extensions already shipped: `MASE_LONG_CONTEXT_VARIANT`,
   `MASE_MULTIPASS`, `MASE_LME_VERIFY`).
