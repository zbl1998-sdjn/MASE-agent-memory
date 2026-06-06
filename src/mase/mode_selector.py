"""由环境变量和问题内容共同驱动的模式选择器。

本模块集中承载“路由式”决策：当前是不是长上下文/长记忆任务、应当使用
哪个执行器模式、Notetaker 采用哪类压缩画像。新增任务族时优先改这里，
避免把分支继续塞回编排器形成上帝类。
"""
from __future__ import annotations

import os

from .markers import (
    EN_DISAMBIGUATION_MARKERS,
    EN_HOT_MEMORY_MARKERS,
    EN_REASONING_MARKERS,
    ZH_DISAMBIGUATION_MARKERS,
    ZH_HOT_MEMORY_MARKERS,
    ZH_REASONING_MARKERS,
    contains_any,
)
from .topic_threads import ENGLISH_RECALL_MARKERS, RECALL_MARKERS, detect_text_language


# ---- 任务上下文探针：只读环境变量，不反向依赖编排器 ----
def current_task_type() -> str:
    return str(os.environ.get("MASE_TASK_TYPE") or "").strip().lower()


def is_long_context_qa() -> bool:
    return current_task_type() == "long_context_qa"


def is_long_memory() -> bool:
    return current_task_type() == "long_memory"


def use_deterministic_fact_sheet() -> bool:
    return is_long_context_qa() or is_long_memory()


def lveval_dataset() -> str:
    return str(os.environ.get("MASE_LVEVAL_DATASET") or "").strip().lower()


def long_context_length_bucket() -> str:
    """返回当前 LV-Eval 数据集长度后缀，例如 ``256k``。

    数据集环境变量缺失或无法解析时返回空串。编排层用这个桶调大检索数量
    和 fact-sheet 窗口半径，避免 128k+ 长干草堆把召回饿死。
    """
    ds = lveval_dataset()
    if not ds:
        return ""
    for bucket in ("256k", "128k", "64k", "32k", "16k"):
        if ds.endswith(bucket) or f"_{bucket}" in ds:
            return bucket
    return ""


def long_context_search_limit(default: int = 10) -> int:
    bucket = long_context_length_bucket()
    return {
        "16k": 12,
        "32k": 15,
        "64k": 20,
        "128k": 30,
        "256k": 30,
    }.get(bucket, default)


def long_context_window_radius(default: int = 220) -> int:
    bucket = long_context_length_bucket()
    return {
        "16k": 240,
        "32k": 280,
        "64k": 320,
        "128k": 380,
        "256k": 420,
    }.get(bucket, default)


def multipass_allowed_for_task() -> bool:
    """判断当前任务族是否适合启用多轮检索。

    这是引擎里的“任务级”门禁。调用方仍需通过
    ``multipass_retrieval.is_enabled()`` 检查 ``MASE_MULTIPASS=1``；这里
    只回答“该任务族在架构上是否应该进入 multipass”。

    允许范围限定为 ``long_context_qa``（LV-Eval 中英文）和
    ``long_memory``（LME）。普通闲聊被排除，避免调用进程里残留的
    MASE_MULTIPASS 环境变量误触发重型流水线。
    """
    return is_long_context_qa() or is_long_memory()


def is_factrecall_long_context() -> bool:
    if not is_long_context_qa():
        return False
    ds = lveval_dataset()
    return ds.startswith("factrecall") or ds == ""


def is_multidoc_long_context() -> bool:
    if not is_long_context_qa():
        return False
    ds = lveval_dataset()
    if not ds:
        return False
    return not ds.startswith("factrecall")


def local_only_models_enabled() -> bool:
    # 长记忆官方/本地复现实验可强制只走本地模型，避免云模型审批与成本噪声。
    raw = (
        os.environ.get("MASE_LOCAL_ONLY")
        or os.environ.get("MASE_LONG_MEMORY_LOCAL_ONLY")
        or os.environ.get("MASE_LME_LOCAL_ONLY")
        or ""
    )
    return str(raw).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def prefer_stable_local_temporal_executor() -> bool:
    # temporal-reasoning 默认走稳定本地执行器；只有显式开关才切深度推理模型。
    raw = os.environ.get("MASE_LONG_MEMORY_TEMPORAL_DEEPREASON") or os.environ.get("MASE_LME_TEMPORAL_DEEPREASON") or ""
    return str(raw).strip().lower() not in {"1", "true", "yes"}


# ---- 记忆热度与模式选择：返回字符串模式名，由 model_providers 解析 ----
def determine_memory_heat(user_question: str) -> str:
    lowered = str(user_question or "").lower()
    if contains_any(lowered, ZH_HOT_MEMORY_MARKERS + EN_HOT_MEMORY_MARKERS):
        return "hot"
    if contains_any(lowered, RECALL_MARKERS + ENGLISH_RECALL_MARKERS):
        return "cold"
    return "cold"


def benchmark_profile() -> str:
    return str(os.environ.get("MASE_BENCHMARK_PROFILE") or "").strip().lower()


def task_profile() -> str:
    raw = str(os.environ.get("MASE_TASK_PROFILE") or benchmark_profile()).strip().lower()
    # 历史脚本沿用 nolima_wrapper 命名，内部统一映射成候选证据画像。
    aliases = {
        "nolima_wrapper": "candidate_evidence",
        "nolima_wrapper_extract": "candidate_evidence_extract",
    }
    return aliases.get(raw, raw)


def lme_question_type() -> str:
    return str(os.environ.get("MASE_LONG_MEMORY_QTYPE") or os.environ.get("MASE_QTYPE") or "").strip().lower()


def lme_qtype_routing_enabled() -> bool:
    raw = os.environ.get("MASE_LONG_MEMORY_QTYPE_ROUTING") or os.environ.get("MASE_LME_QTYPE_ROUTING") or ""
    return str(raw).strip().lower() in {"1", "true", "yes"}


def long_memory_verify_enabled() -> bool:
    raw = os.environ.get("MASE_LONG_MEMORY_VERIFY") or os.environ.get("MASE_LME_VERIFY") or ""
    return str(raw).strip().lower() in {"1", "true", "yes"}


def long_memory_retry_enabled() -> bool:
    raw = os.environ.get("MASE_LONG_MEMORY_RETRY") or os.environ.get("MASE_LME_RETRY") or ""
    return str(raw).strip().lower() in {"1", "true", "yes"}


def select_notetaker_mode(user_question: str, memory_heat: str) -> str:
    # 英文长记忆基准需要事实卡压缩；中文则按冷热记忆选择操作画像。
    language = detect_text_language(user_question)
    if language == "en":
        return "english_fact_card_ops"
    return "hot_ops" if memory_heat == "hot" else "cold_ops"


def select_executor_mode(user_question: str, fact_sheet: str) -> str:
    language = detect_text_language(user_question)
    if not fact_sheet.strip() or fact_sheet.strip() == "无相关记忆。":
        return "general_answer_reasoning"
    profile = task_profile()
    # 候选证据画像用于 NoLiMa/长上下文抽取任务，保持和 fact-sheet 渲染约定一致。
    if profile == "candidate_evidence":
        return "grounded_nolima_main_english" if language == "en" else "grounded_answer"
    if profile == "candidate_evidence_extract":
        return "grounded_long_context_nolima_english" if language == "en" else "grounded_long_context"
    if is_long_context_qa():
        # LV-Eval 按题型和语种分流；多文档任务需要更强的证据约束提示。
        if str(os.environ.get("MASE_LONG_CONTEXT_VARIANT") or "").strip().lower() == "mc":
            return "grounded_long_context_mc"
        if is_multidoc_long_context():
            return "grounded_long_context_multidoc_english" if language == "en" else "grounded_long_context_multidoc"
        return "grounded_long_context_english" if language == "en" else "grounded_long_context"
    if is_long_memory():
        if local_only_models_enabled():
            # 本地模式先尊重 qtype 路由，再决定是否使用深度推理执行器。
            if lme_qtype_routing_enabled() and lme_question_type() == "temporal-reasoning":
                if prefer_stable_local_temporal_executor():
                    return "grounded_long_memory_english" if language == "en" else "grounded_long_memory"
                return "grounded_long_memory_deepreason_english" if language == "en" else "grounded_long_memory_deepreason"
            return "grounded_long_memory_english" if language == "en" else "grounded_long_memory"
        # iter4-retry：MASE_LME_RETRY=1 时强制所有问题走二次意见执行器
        #（kimi-k2.5 + 非弃答偏置提示），供 103-fail 切片复盘脚本使用。
        if long_memory_retry_enabled():
            return "grounded_long_memory_retry_kimi"
        # iter5：按 qtype 路由执行器。MASE_LME_QTYPE_ROUTING=1 时，
        # temporal-reasoning 显式走本地深度推理模型，而不是云端 GLM-5 链路。
        # 这个例外只在用户主动开启该类别时生效，其他路径仍遵守 deepseek 低优先级规则。
        if lme_qtype_routing_enabled():
            qtype = lme_question_type()
            if qtype == "temporal-reasoning":
                return "grounded_long_memory_deepreason_english" if language == "en" else "grounded_long_memory_deepreason"
        return "grounded_long_memory_cloud_english" if language == "en" else "grounded_long_memory_cloud"
    if language == "en":
        if contains_any(user_question, EN_REASONING_MARKERS):
            return "grounded_analysis_english_reasoning"
        if contains_any(user_question, EN_DISAMBIGUATION_MARKERS) and "candidate" in fact_sheet.lower():
            return "grounded_disambiguation_english_reasoning"
        return "grounded_answer_english_reasoning"
    if contains_any(user_question, ZH_REASONING_MARKERS):
        return "grounded_analysis_reasoning"
    if contains_any(user_question, ZH_DISAMBIGUATION_MARKERS) and "候选裁决表" in fact_sheet:
        return "grounded_disambiguation_reasoning"
    return "grounded_answer"


def verify_mode_for_question(user_question: str) -> str:
    is_en = detect_text_language(user_question) == "en"
    if is_long_context_qa():
        return "grounded_verify_long_context_english" if is_en else "grounded_verify_long_context"
    if is_long_memory() and local_only_models_enabled():
        return "grounded_verify_english_reasoning" if is_en else "grounded_verify_reasoning"
    # 仅在长记忆上下文且显式开启 verifier 逃生口时，使用云端 LME 调优 verifier。
    # 不按 benchmark qid 命名分支，避免把逻辑过拟合到 LongMemEval 文件名。
    if is_long_memory() and long_memory_verify_enabled():
        return "grounded_verify_lme_english" if is_en else "grounded_verify_lme"
    return "grounded_verify_english_reasoning" if is_en else "grounded_verify_reasoning"


def generalizer_mode_for_question(user_question: str) -> str:
    if is_long_memory() and local_only_models_enabled():
        # 本地 qtype generalizer 只覆盖可确定模板化的偏好/多会话聚合题。
        if lme_qtype_routing_enabled():
            qtype = lme_question_type()
            if qtype == "single-session-preference":
                return (
                    "grounded_long_memory_preference_generalizer_local_english"
                    if detect_text_language(user_question) == "en"
                    else "grounded_answer"
                )
            if qtype == "multi-session":
                return (
                    "grounded_long_memory_aggregate_generalizer_local_english"
                    if detect_text_language(user_question) == "en"
                    else "grounded_analysis_reasoning"
                )
        return "grounded_answer_english_reasoning" if detect_text_language(user_question) == "en" else "grounded_answer"
    if is_long_memory() and lme_qtype_routing_enabled():
        qtype = lme_question_type()
        if qtype == "single-session-preference":
            return (
                "grounded_long_memory_preference_generalizer_english"
                if detect_text_language(user_question) == "en"
                else "grounded_answer"
            )
        if qtype == "multi-session":
            return (
                "grounded_long_memory_aggregate_generalizer_english"
                if detect_text_language(user_question) == "en"
                else "grounded_answer"
            )
    return "grounded_answer_english_reasoning" if detect_text_language(user_question) == "en" else "grounded_answer"


__all__ = [
    "current_task_type",
    "is_long_context_qa",
    "is_long_memory",
    "use_deterministic_fact_sheet",
    "lveval_dataset",
    "long_context_length_bucket",
    "long_context_search_limit",
    "long_context_window_radius",
    "multipass_allowed_for_task",
    "is_factrecall_long_context",
    "is_multidoc_long_context",
    "determine_memory_heat",
    "benchmark_profile",
    "task_profile",
    "lme_question_type",
    "lme_qtype_routing_enabled",
    "long_memory_verify_enabled",
    "long_memory_retry_enabled",
    "local_only_models_enabled",
    "select_notetaker_mode",
    "select_executor_mode",
    "verify_mode_for_question",
    "generalizer_mode_for_question",
]
