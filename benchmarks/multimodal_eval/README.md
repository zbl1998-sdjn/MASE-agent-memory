# multimodal_eval_v1 — MASE 多模态端到端评测集

**目的**:在多模态改造(S0 文档图像 / S1 语音 / S2 交互上传)优化完成后统一跑分。
**建集时间**:2026-07-03,**先于优化冻结**——holdout 结果不受"照着考题调参"污染。

## 四个 lane

| lane | 来源 | 数量 | 语言 | 许可 | 独有价值 |
|---|---|---|---|---|---|
| synthetic | 本目录 generate_dataset.py(虚构实体,seed=20260703) | 72 | zh/en/混 | 自产 | **唯一**覆盖溯源链/负例幻觉/干扰弃答/三档难度退化的 lane |
| sroie | [zzzDavid/ICDAR-2019-SROIE](https://github.com/zzzDavid/ICDAR-2019-SROIE)(修正版) | 100 采样 | en | MIT | 真实扫描小票 + 4 字段 KIE ground truth |
| xfund_zh | [doc-analysis/XFUND](https://github.com/doc-analysis/XFUND) zh.val | 50 全量 | zh | CC BY-NC-SA 4.0(**仅内部评测,不得再分发**) | 真实中文表单 KV |
| librispeech | [openslr.org/12](https://www.openslr.org/12) test-clean | 50 采样 | en | CC BY 4.0 | 真实语音 + 逐字参考转写 |

媒体二进制在仓外:合成 lane 在 `E:/MASE-runs/datasets/multimodal_eval_v1/`,外部 lane 在
`E:/MASE-runs/datasets/external/`;仓内只提交 ground truth(cases*.json)、manifest 与脚本。

## 构建(一次性,已冻结后勿重跑)

```bash
python -X utf8 benchmarks/multimodal_eval/generate_dataset.py   # 合成 lane 渲染 + TTS
python -X utf8 benchmarks/multimodal_eval/build_suite.py        # 采样外部 lane + 合并 + manifest
```

## 跑分

```bash
# 正式(holdout 全量,单次口径)
python -X utf8 benchmarks/multimodal_eval/run_eval.py --split holdout
# 调优期间只允许看 dev
python -X utf8 benchmarks/multimodal_eval/run_eval.py --split dev
# 冒烟(不作为成绩)
python -X utf8 benchmarks/multimodal_eval/run_eval.py --split dev --limit 5
```

产物落 `E:/MASE-runs/eval_runs/<dataset>_<split>_<ts>/{results.json,summary.md}`。

## 维度口径(全部确定性,无 LLM 评委)

- `fulltext_anchor_rate`:锚串(casefold + 去空白/逗号/货币符归一化)出现在抽取全文
- `fact_anchor_rate`:某条已入库事实的 value 含期望锚串
- `recall_rate`:`mase2_search_memory` 按锚串能召回
- `halluc_ok_rate`:负例(纯装饰页)写入事实数 == 0
- `provenance_ok_rate`:事实→media_extraction→media_asset→资产字节 机械链检
- `char_similarity_mean`:音频转写 vs 参考转写的归一化字符相似度(SequenceMatcher;**非严格 WER/CER**,只用于纵向自比)

## 正式基线(holdout,单次全量)

- **当前基线(2026-07-06,优化轮四收口)**:`E:/MASE-runs/eval_runs/multimodal_eval_v1_holdout_20260706T171141Z/`
  (`sample_ids_sha256=09bc7a2886b7b32e…` 与 manifest 一致,`manifest_mismatch=[]`,212 例单次跑完)
  - 改动:① kv 一行多键切分 + 单向并集 + ② 版面结构确定性解析 `structure_facts.py`(表格行/问答行/宽空格对/序号选项组)+ ③ 视觉补看轮(抽取器 v7)+ 传输层加固(ollama 读超时、whisper cpu+int8 统一回退)
  - overall:fulltext_anchor 0.9325 / **fact_anchor 0.8677(前基线 0.8505,+1.7pp)** / recall 0.8971 /
    **halluc_ok 1.0(保持)** / provenance_ok 1.0 / char_similarity 0.8955(librispeech lane);**infra 0(历史首次)**
  - by lane:sroie fact 0.9219(前 0.9281,80 例内 ±1 事实级波动)/ xfund_zh **0.775**(前 0.735)/
    synthetic **0.8871**(前 0.8226)/ librispeech char_sim 0.8955(与轮三逐位一致,音频路径未动)
  - 口径:音频 `MASE_WHISPER_DEVICE=cpu MASE_WHISPER_COMPUTE=int8`(与轮三一致);诊断集(XFUND-train)本轮 0.7733→0.88,偏中文表单,holdout 泛化幅度如上,如实并报。
- **优化轮三基线(2026-07-05,历史)**:`E:/MASE-runs/eval_runs/multimodal_eval_v1_holdout_20260704T123334Z/`
  (`sample_ids_sha256=09bc7a2886b7b32e…` 与 manifest 一致,`manifest_mismatch=[]`,212 例单次跑完)
  - 改动:① 确定性 KV 行解析并集(抽取器 v6)+ ② XFUND-train 诊断集(治 dev 过拟合的方法论)+ ③ **doc_facts 换 qwen3:14b**(二轮 A/B 主力,think 关闭)
  - overall:fulltext_anchor 0.9325 / **fact_anchor 0.8505(前基线 0.7199,+13.1pp)** / recall 0.8939 /
    **halluc_ok 1.0(保持)** / provenance_ok 1.0 / char_similarity 0.8822;infra_errors 2(0.9%,两张老问题图 400)
  - by lane:sroie fact **0.9281**(前 0.8063)/ xfund_zh **0.735**(前 0.545,qwen3 中文表单大幅补齐)/
    synthetic 0.8226(持平,已饱和)/ librispeech char_sim 0.8955
  - **口径说明**:本次为绕开音频 GPU 争用死锁用 `MASE_WHISPER_DEVICE=cpu`(int8),librispeech char_sim 从 0.9054 微降到 0.8955 纯是 int8-CPU vs float16-GPU 所致,音频路径本轮未改、fact_anchor 不受影响。
- **优化轮二基线(2026-07-04,历史)**:`E:/MASE-runs/eval_runs/multimodal_eval_v1_holdout_20260704T032902Z/`
  (`sample_ids_sha256=09bc7a2886b7b32e…` 与 manifest 一致,`manifest_mismatch=[]`,212 例单次跑完)
  - 改动:补抽轮(completeness pass)+ 多行值合并指引(抽取器 v5)+ 瞬时 infra 重试(实救 5 次调用)
  - overall:fulltext_anchor 0.9325 / **fact_anchor 0.7199(前基线 0.6271,+9.3pp)** / recall 0.8891 /
    **halluc_ok 1.0(保持)** / provenance_ok 1.0 / char_similarity 0.8895;infra_errors 2(0.9%)
  - by lane:sroie fact **0.8063**(前 0.65)/ synthetic **0.8387**(前 0.8226)/
    xfund_zh **0.545**(前 0.53;dev 提升未完全泛化,无回退)/ librispeech char_sim 0.9054
- **v1.1 首基线(2026-07-03,历史)**:`E:/MASE-runs/eval_runs/multimodal_eval_v1_holdout_20260703T084941Z/`
  (`sample_ids_sha256=09bc7a2886b7b32e…` 与 manifest 一致,`manifest_mismatch=[]`,212 例单次跑完)
  - 配置:vision=qwen2.5vl:7b,doc_facts=qwen2.5:14b,speech_facts=qwen2.5:7b,whisper=large-v3;
    `MASE_OLLAMA_KEEP_ALIVE=0` + `CUDA_VISIBLE_DEVICES=1`
  - overall:fulltext_anchor 0.9325 / **fact_anchor 0.6271** / recall 0.8842 /
    **halluc_ok 1.0** / provenance_ok 1.0 / char_similarity 0.8895;infra_errors 3(1.4%,
    1 瞬时 CUDA error + 2 Ollama 图像加载 400,环境层非模型质量)
  - by lane:sroie fact 0.65 / synthetic fact 0.8226 / xfund_zh fact 0.53 / librispeech char_sim 0.9054
  - 后续任何改动的成绩都与此基线纵向对比;halluc_ok 仅 synthetic 负例 lane 计分。

## 版本修订

- **v1.1(2026-07-03,holdout 从未运行过,重冻结合规)**:XFUND 适配器加标注卫生规则——
  未勾选复选框项(□)不作期望值(客观错标:真实值是 √ 勾选项)、含句读长段落不作 KV 值、
  纯符号值排除。规则通用,不引用任何评测锚串;`sample_ids_sha256=09bc7a2886b7b32e…`。
  依据:dev 逐例取证(`eval_runs/multimodal_eval_v1_dev_20260702T222829Z`)。
- v1.0(2026-07-03):初版冻结,`sample_ids_sha256=9845e185e30ae4eb…`。

## 反过拟合政策(与 docs/BENCHMARK_ANTI_OVERFIT.md 同口径)

1. **holdout(~80%)冻结**:优化期间禁止查看 holdout 逐例结果;只有优化收口后才跑 holdout。
2. 调参一律用 **dev(~20%)**。
3. 正式成绩 = **单次全量 holdout 跑** + results 中 `sample_ids_sha256` 与 manifest 一致;
   `--limit`、按例重试、跨 run 拼 best-of 一律不作为成绩。
4. runner 每次跑分前重算文件哈希,与 manifest 不一致的案例记 `manifest_mismatch` 并在
   summary 顶部标注(此时结果与历史不可比)。
5. 禁止把评测锚串/案例内容写进产品提示词或路由规则(anti-overfit 审计的既有禁令)。

## 已知盲区(诚实边界)

- 合成"退化"(低 DPI/JPEG/旋转/灰底)≠ 真实扫描仪/手机拍摄的完整噪声分布;SROIE/XFUND 补真实噪声,但领域仍偏小票/表单。
- SAPI 合成语音比真实会议干净(无重叠说话/远场/口音);LibriSpeech 是朗读体,非会议体。真实会议录音(如 AMI/AliMeeting)留作 v2 扩展。
- 无手写体、无表格线密集财务报表、无低资源方言。
- 生成式 QA 与干扰弃答需要 executor 参与,方差大,v1 默认不计分(清单已在 cases.json,QA lane 留作扩展)。
- SROIE 使用的是修正版全量 626 中的采样(train+test 混合标注件),非官方 task-3 排行榜切分——只用于内部纵向对比,不与论文数字横向比较。
