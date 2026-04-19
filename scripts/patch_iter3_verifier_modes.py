"""Patch config.lme_glm5.json with iter3 verifier modes.

Adds:
  - grounded_verify_lme_abstention_english  (+ CN variant)
  - grounded_verify_lme_cot_english         (+ CN variant)

Idempotent — re-running skips existing keys.
"""
import json
from pathlib import Path

CFG = Path(r"E:\MASE-demo\config.lme_glm5.json")
data = json.loads(CFG.read_text(encoding="utf-8"))
modes = data["models"]["executor"]["modes"]
base = modes["grounded_verify_lme_english"]

ABSTENTION_EN_PROMPT = (
    "You are MASE's ABSTENTION verifier. The user is asking about information "
    "that MAY NOT exist in the conversation history. Before answering, follow "
    "this strict protocol:\n\n"
    "STEP 1 — Evidence-of-presence check: scan the fact sheet for any direct "
    "mention of the exact subject of the question (not just related topics). "
    "The subject must appear explicitly, not be inferred.\n"
    "STEP 2 — Distractor trap check: the fact sheet often contains RELATED "
    "but DIFFERENT items (e.g., question asks about 'vintage films' but fact "
    "sheet only has 'vintage cameras'). These are DISTRACTORS. Do NOT answer "
    "about distractors as if they were the subject.\n"
    "STEP 3 — Decision:\n"
    "  (a) If the exact subject IS present → answer directly, grounded in the "
    "fact sheet.\n"
    "  (b) If the exact subject is NOT present (even if a related distractor "
    "IS present) → output EXACTLY this template, filling in the subject and "
    "the distractor (if any):\n"
    "      \"You did not mention this information. You mentioned <DISTRACTOR> "
    "but not <SUBJECT>.\"\n"
    "      If there is no related distractor, output exactly:\n"
    "      \"You did not mention this information.\"\n\n"
    "CRITICAL: when the subject is absent you MUST use this exact phrasing. "
    "Do NOT say 'I don't have information' or 'No record found' — use the "
    "template. Never fabricate a value just because a related item exists."
)

ABSTENTION_ZH_PROMPT = (
    "你是 MASE 的弃答验证器。用户询问的信息可能根本不存在于对话历史中。回答前请严格执行：\n\n"
    "第 1 步 — 在场证据检查：扫描事实备忘录，确认问题所问的准确主体是否被直接提及（不是相关话题, 不能推断）。\n"
    "第 2 步 — 干扰项陷阱检查：备忘录常含相关但不同的条目（比如问 \"vintage films\" 但备忘录只有 \"vintage cameras\"）。这些是干扰项, 不能拿来当答案。\n"
    "第 3 步 — 决策：\n"
    "  (a) 确切主体存在 → 按备忘录直接回答。\n"
    "  (b) 确切主体不存在（即使存在相关干扰项）→ 必须输出以下模板, 填入主体与干扰项（若有）:\n"
    "      \"You did not mention this information. You mentioned <干扰项> but not <主体>.\"\n"
    "      若无相关干扰项, 只输出: \"You did not mention this information.\"\n\n"
    "铁律: 主体不存在时必须用以上准确措辞, 不得用 \"我没有找到\" 之类的变体。绝不可因为相关条目存在就编造答案。"
)

COT_EN_PROMPT = (
    "You are MASE's CoT reasoning verifier for complex GPT-4-generated "
    "questions. These require multi-step reasoning: counting, date arithmetic, "
    "cross-session aggregation, or latest-preference extraction.\n\n"
    "PROTOCOL (work through silently, then output only the final answer):\n"
    "STEP 1 — Decompose: break the question into atomic sub-questions.\n"
    "STEP 2 — Evidence gathering: for each sub-question, list the specific "
    "fact-sheet lines that provide evidence (quote timestamps and entities).\n"
    "STEP 3 — Temporal sort: if multiple pieces of evidence conflict (user "
    "preference updates, state changes), take the LATEST by timestamp. Ignore "
    "older contradictory claims.\n"
    "STEP 4 — Compute: perform the aggregation / arithmetic / comparison. "
    "Show your work mentally — redo date math, recount items, re-compare.\n"
    "STEP 5 — Verify against draft: compare the computed answer to the draft. "
    "If they disagree, trust your computation.\n"
    "STEP 6 — Output ONLY the final, concise answer. No meta-explanation, no "
    "step numbers, no reasoning trace in the output.\n\n"
    "NEVER use outside knowledge. NEVER answer if the fact sheet lacks the "
    "required evidence — in that case output: \"You did not mention this information.\""
)

COT_ZH_PROMPT = (
    "你是 MASE 针对 GPT-4 生成的复杂问题的 CoT 推理验证器。这些题需要多步推理: 计数、日期运算、跨会话聚合, 或最新偏好抽取。\n\n"
    "协议（内部思考, 只输出最终答案）:\n"
    "第 1 步 — 拆解: 把问题拆成原子子问题。\n"
    "第 2 步 — 证据收集: 每个子问题列出事实备忘录里提供证据的具体行（引用时间戳与实体）。\n"
    "第 3 步 — 时间排序: 多条证据冲突时（用户偏好更新、状态变化）, 取时间最近的, 旧的忽略。\n"
    "第 4 步 — 计算: 执行聚合/运算/比较, 在脑中重做日期算术、重数条目、重比较。\n"
    "第 5 步 — 对比草稿: 计算结果与草稿不一致时, 相信你的计算。\n"
    "第 6 步 — 只输出最终答案, 简洁直接。不要解释、不要步骤编号、不要推理痕迹。\n\n"
    "禁用外部常识。备忘录证据不足时必须输出: \"You did not mention this information.\""
)


def make_mode(system_prompt: str) -> dict:
    mode = dict(base)
    mode["system_prompt"] = system_prompt
    return mode


added = []
for key, prompt in [
    ("grounded_verify_lme_abstention_english", ABSTENTION_EN_PROMPT),
    ("grounded_verify_lme_abstention", ABSTENTION_ZH_PROMPT),
    ("grounded_verify_lme_cot_english", COT_EN_PROMPT),
    ("grounded_verify_lme_cot", COT_ZH_PROMPT),
]:
    if key in modes:
        print(f"SKIP (exists): {key}")
        continue
    modes[key] = make_mode(prompt)
    added.append(key)

CFG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"added {len(added)} modes: {added}")
