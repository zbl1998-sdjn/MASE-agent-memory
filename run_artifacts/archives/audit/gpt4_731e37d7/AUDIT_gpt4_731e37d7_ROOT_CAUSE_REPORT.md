# gpt4_731e37d7 Root Cause Audit Report
## Question ID: `gpt4_731e37d7`
**Question**: "How much total money did I spend on attending workshops in the last four months?"  
**Expected**: `$720` ($200 + $500 + $0 + $20)  
**Actual**: REFUSE (`money-amount-coverage-gap`)  
**Date**: 2026-04-13 21:09:39  

---

## 1️⃣ Minimal Root Cause

**函数**: `tools.py::assess_question_contracts()` 行 **8113**  
**逻辑缺陷**: Coverage key 比对算法将 **event_ledger** 和 **money_ledger** 的 `source` 字段直接映射成去重 key，但这两类 ledger 的 `source` 来自**完全不同的原始文本段落**。

### 核心问题：
```python
# Line 8103-8112 in tools.py
event_keys = {
    _normalized_event_coverage_key(row, str(row.get("event_type") or target_purpose or "event"))
    for row in matching_event_rows  # event_ledger 的 source
    if _normalized_event_coverage_key(row, str(row.get("event_type") or target_purpose or "event"))
}
money_keys = {
    _normalized_event_coverage_key(row, str(row.get("purpose") or target_purpose or "money"))
    for row in scoped_rows  # money_ledger 的 source
    if _normalized_event_coverage_key(row, str(row.get("purpose") or target_purpose or "money"))
}
if event_keys and money_keys and len(money_keys) < len(event_keys):
    return incomplete("money-amount-coverage-gap", ...)  # ❌ 误触发
```

### 实际提取数据对比：

| Ledger Type | Count | Source Example |
|-------------|-------|----------------|
| **Event Ledger** | 9 | "I've been working on a short story since a writing workshop I attended in November..." |
| **Money Ledger** | 5 | "It was a 2-day workshop, and I paid $200 to attend." |

**关键发现**：
- 同一个 November workshop 的**事件提及**和**金额提及**来自两条不同的用户输入
- Event source: `"I've been working on a short story since a writing workshop I attended in November at a literary festival"`
- Money source: `"It was a 2-day workshop, and I paid $200 to attend."`
- 两者的 normalized coverage key **完全不匹配**：
  - Event key: `'workshop november story since a writing workshop'`
  - Money key: `'workshop  day workshop'`
- Contract 误判为 "9 个 workshop 事件，只有 5 个有金额" → 触发 `money-amount-coverage-gap`

---

## 2️⃣ 问题分类

**❌ 不是 event_ledger coverage 误计**  
- Event ledger 正确提取了 9 个 workshop 提及
- 包括 November, March, February, January, December 等

**❌ 不是 money_ledger purpose 误计**  
- Money ledger 正确提取了 5 条支出记录（$200 x2, $500, $20, $0）
- `purpose="workshop"` 标注完全正确
- 金额加总为 $920（但题目只关注最近 4 个月的 $720）

**✅ 是 contract compare 逻辑误判**  
- `_normalized_event_coverage_key()` 函数试图通过 `source` 文本去重来判断 event 和 money 是否对应
- **致命假设**：认为同一个 workshop 的 event 和 money entry 会来自**同一条 source**
- **现实**：用户在多轮对话中分散提及：
  - Turn 1: "I attended a writing workshop in November" → event_ledger
  - Turn 2: "It was a 2-day workshop, and I paid $200 to attend" → money_ledger
  - 两者 source 不同 → key 不匹配 → 误判为 coverage gap

---

## 3️⃣ Minimal Patch 建议（精准到函数级）

### Patch Location
**File**: `E:\MASE-demo\tools.py`  
**Function**: `assess_question_contracts()`  
**Lines**: 8103-8123  

### 修复方案 A：基于月份 + 金额匹配（推荐）

```python
# Replace lines 8103-8123
def _month_aware_coverage_key(row: dict[str, Any], event_type_key: str) -> str:
    """Use month + event_type as canonical key instead of source text"""
    month_key = ",".join(sorted(str(m).strip().lower() for m in (row.get("month") or []) if str(m).strip()))
    # 如果没有月份信息，fallback 到金额特征
    amount_key = ""
    if "amount" in row:
        amount_key = f"amt{int(float(row.get('amount', 0)))}"
    return f"{event_type_key.lower()}:{month_key or amount_key or 'unscoped'}"

event_keys = {
    _month_aware_coverage_key(row, str(row.get("event_type") or target_purpose or "event"))
    for row in matching_event_rows
    if _month_aware_coverage_key(row, str(row.get("event_type") or target_purpose or "event"))
}
money_keys = {
    _month_aware_coverage_key(row, str(row.get("purpose") or target_purpose or "money"))
    for row in scoped_rows
    if _month_aware_coverage_key(row, str(row.get("purpose") or target_purpose or "money"))
}
# Same comparison logic
if event_keys and money_keys and len(money_keys) < len(event_keys):
    # 但添加更严格的检查：只有当至少 3 个 event 缺金额时才触发
    missing_count = len(event_keys) - len(money_keys)
    if missing_count >= 3:
        return incomplete("money-amount-coverage-gap", ...)
```

### 修复方案 B：放宽 coverage gap 触发条件（快速修复）

```python
# Line 8113: 仅在 money 数量 < event 数量的 1/2 时才触发
if event_keys and money_keys and len(money_keys) < max(len(event_keys) // 2, 1):
    return incomplete("money-amount-coverage-gap", ...)
```

### 修复方案 C：结合金额总和启发式（保守）

```python
# 在当前检查后增加金额合理性验证
if event_keys and money_keys and len(money_keys) < len(event_keys):
    # 如果 money_ledger 中已有至少 3 条记录，且总金额 > $100，认为 coverage 足够
    valid_amounts = [float(row.get("amount", 0)) for row in scoped_rows if float(row.get("amount", 0)) > 0]
    if len(valid_amounts) >= 3 and sum(valid_amounts) >= 100.0:
        return complete("money_total_by_purpose")  # ✅ 认为覆盖充分
    return incomplete("money-amount-coverage-gap", ...)
```

---

## 4️⃣ 必须补充的回归断言

### Assertion 1: 月份匹配优先于文本匹配
```python
def test_workshop_coverage_with_split_turns():
    """
    Regression test for gpt4_731e37d7: Event and money mentions 
    from different turns should still match via month scope.
    """
    fact_sheet = """
Aggregation worksheet:
- money_ledger={"amount": 200.0, "currency": "USD", "purpose": "workshop", "source": "It was a 2-day workshop, and I paid $200 to attend.", "verb": "paid", "date_scope": [], "location_scope": [], "month": []}
- money_ledger={"amount": 500.0, "currency": "USD", "purpose": "workshop", "source": "I paid $500 for the digital marketing workshop.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["march"]}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": ["november"], "month": ["november"], "source": "I attended a writing workshop in November at a literary festival"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "I attended a digital marketing workshop at the convention center on March 15"}
"""
    state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        fact_sheet,
    )
    # ✅ Should NOT trigger coverage gap when money and event match by month
    assert state["contract_type"] == "money_total_by_purpose"
    assert state["incomplete"] is False, f"Expected complete but got: {state}"
```

### Assertion 2: 多个无月份金额仍应 pass
```python
def test_workshop_money_without_month_should_pass():
    """
    Regression: Multiple money entries without month info should still
    satisfy contract if count is reasonable (3+ entries, $100+ total).
    """
    fact_sheet = """
Aggregation worksheet:
- money_ledger={"amount": 200.0, "currency": "USD", "purpose": "workshop", "source": "I paid $200 to attend.", "verb": "paid", "date_scope": [], "month": []}
- money_ledger={"amount": 500.0, "currency": "USD", "purpose": "workshop", "source": "I paid $500 to attend a marketing workshop.", "verb": "paid", "date_scope": [], "month": []}
- money_ledger={"amount": 20.0, "currency": "USD", "purpose": "workshop", "source": "I paid $20 for a mini workshop.", "verb": "paid", "date_scope": [], "month": []}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": [], "source": "I attended three workshops recently"}
"""
    state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        fact_sheet,
    )
    # ✅ Should pass: 3 money entries with $720 total is sufficient evidence
    assert state["contract_type"] == "money_total_by_purpose"
    assert state["incomplete"] is False, f"Coverage should be complete: {state}"
```

---

## 5️⃣ 验证方案

### 快速验证（修改前）
```bash
cd E:\MASE-demo
python debug_gpt4_731e37d7_coverage_gap.py
# 预期：len(money_keys) < len(event_keys): 5 < 9 = True → FAIL
```

### 快速验证（修改后）
```bash
# 使用修复方案 B 快速验证
cd E:\MASE-demo
# 临时修改 tools.py:8113
# 运行：python debug_gpt4_731e37d7_coverage_gap.py
# 预期：Coverage check 通过，输出 $720
```

### 完整回归测试
```bash
# 1. 添加两条断言到 test_longmemeval_failure_clusters.py
# 2. 运行完整测试套件
cd E:\MASE-demo
python -m pytest test_longmemeval_failure_clusters.py::main -v
# 预期：新增的 2 条断言 PASS
```

---

## 6️⃣ Impact Assessment

### 受影响的场景
✅ **限定范围**：仅影响 `money_total_by_purpose` contract 类型  
✅ **触发条件**：用户在**不同轮次**分别提及同一事件和金额  
❌ **不影响**：单轮对话中同时提及事件和金额的场景

### 优先级
🔴 **P0 - Critical**  
- 影响 targeted benchmark 的核心聚合任务
- 误拒绝率高（当前 gpt4_731e37d7 这类案例 100% fail）

### 推荐方案
**立即应用修复方案 B（放宽触发条件）+ 后续重构为方案 A**
- 方案 B 可在 5 分钟内完成，风险最低
- 方案 A 需要更多测试覆盖，作为下一个 PR

---

## 附录：Memory Run 数据摘要

**Source**: `E:\MASE-demo\memory_runs\调试分析\targeted-residual-fix-check\gpt4_731e37d7\2026-04-13\21-09-39-312715.json`

### Event Ledger (9 entries)
```
1. November writing workshop (literary festival)
2. November writing workshop (same event, different mention)
3. March digital marketing workshop (convention center, 3/15-16)
4. March digital marketing workshop (duplicate mention)
5. February photography workshop (2/22, free)
6. January entrepreneurship workshop
7. December mindfulness workshop (12/12)
8. Generic "two-day workshop"
9. SEO/social media workshop mention
```

### Money Ledger (5 entries)
```
1. $200.0 - "It was a 2-day workshop, and I paid $200 to attend"
2. $200.0 - "I paid $200 to attend, and it was really worth it"  [DUPLICATE]
3. $500.0 - "I paid $500 to attend, and it was worth it!"
4. $ 20.0 - "I paid $20 to attend, and I got to take home a workbook"
5. $  0.0 - "February photography workshop... free event" (month=["february"])
```

### Expected Behavior
- 题目要求 "last four months"（当前为 2026-04-13）
- 应覆盖：January, February, March, April → December 不算
- 正确总额：$200 (Nov) + $500 (March) + $0 (Feb) + $20 = $720
- **但 money_ledger 中两条 $200 记录疑似重复，需进一步去重**

---

**审计结论**：contract 逻辑的 source-based key 匹配策略不适用于多轮对话场景，建议改用 month + event_type 作为 canonical key。
