# 火力全开(Full Power)运行档

MASE 默认走**稳妥档**(`config.json`):小模型 + 单 GPU + 用完即卸,是为"桌面卡被占、显存吃紧、避免被杀"这一现实约束调的。本档是 **opt-in 的性能上限档**,在你愿意腾出算力时把双 3090 用满。

> 这是一个可切换档,不是默认。切回稳妥只需不带 `MASE_CONFIG_PATH`。

## 它改了什么

两部分——**MASE 侧配置** + **ollama 服务器侧 env**,缺一不可(GPU 放置是 ollama 服务器启动级的,config.json 管不了)。

### 1. MASE 侧:`config.full_power.json`

| agent | 稳妥档 | 火力全开 | 说明 |
|---|---|---|---|
| doc_facts | qwen3:14b | **qwen3:32b** | 二轮 A/B 主力的更大杯,准确率最大杠杆;num_ctx 8192→16384,think 关闭 |
| vision | qwen2.5vl:7b | 7b + 可选 `--mode big`=**qwen2.5vl:32b** | 转写已强(fulltext 0.9325);big 模式治 xfund run-on 底稿的结构缺失 |
| 其余 pipeline agent | 不变 | 不变 | router/notetaker/planner/executor 属记忆 QA 轴,本轮未 A/B,不擅自动 |

### 2. ollama 服务器侧:双卡 + 常驻(启动前设 env,需重启 ollama 服务)

```powershell
# 先关掉稳妥档跑的 ollama,再用这些 env 重启服务:
$env:CUDA_VISIBLE_DEVICES = "0,1"     # 两张 3090 都可见 → 不同模型自动落不同卡
$env:OLLAMA_KEEP_ALIVE   = "-1"       # 模型常驻不卸 → 消灭反复重载(稳妥档是 0)
# (OLLAMA_SCHED_SPREAD 是把单个大模型跨卡切分,qwen3:32b 20GB 单卡放得下,不需要)
ollama serve
```

## 前置

```bash
ollama pull qwen3:32b          # ~20GB,doc_facts 必需
ollama pull qwen2.5vl:32b      # 可选,仅当用 vision --mode big
```

## 跑法

```bash
# 多模态评测(dev/诊断集调参,holdout 逐例禁看):
MASE_CONFIG_PATH=config.full_power.json \
  python -X utf8 benchmarks/multimodal_eval/run_eval.py --split dev --lanes xfund_zh,sroie

# 摄取 / 库调用:导出 MASE_CONFIG_PATH 后照常
export MASE_CONFIG_PATH=config.full_power.json
python -m mase.multimodal ingest ./docs
```

## 诚实的天花板与代价

- **真正的硬约束不是 GPU,是 GPU0 上的桌面**(Terminal/Copilot/WhatsApp/Perplexity/Clash 都在 GPU0)。双卡常驻前请先腾出 GPU0,否则桌面 + 大模型抢显存会复发"挂起/被杀"。
- **大 ≠ 更好**:北极星是"既定事实上的正确率 + 低幻觉率",不是参数量。qwen3:32b 相对 14b 大概率是几 pp 边际、约 2× 慢;换档后**务必在 dev/诊断集上 A/B**,不达标或 halluc_ok 掉了就退回稳妥档。
- **音频 lane**:长跑若混跑音频,whisper 与大 doc_facts 抢 GPU 会挂起 → 加 `MASE_WHISPER_DEVICE=cpu MASE_WHISPER_COMPUTE=int8`(见优化轮三教训)。
- **稳妥档仍是发布默认**:full_power 是探顶工具,不是生产接受口径。

## 当前基线(纵向对比锚点)

稳妥档(qwen3:14b)holdout 正式基线:fact_anchor **0.8505** / halluc_ok 1.0 / 溯源 1.0(212 例单次,`multimodal_eval_v1_holdout_20260704T123334Z`)。火力全开要证明自己**超过**这个数才值得长期用。
