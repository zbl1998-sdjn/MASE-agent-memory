"""检索补充阶段管线(架构切片⑤,2026-07-12)。

此前的补充召回是散落在 ``benchmark_notetaker.search`` 里的 if/env 块,新
能力(如 NoLiMa POC 验证的两级 judge 管道)没有干净落点。本模块把
"词法核心之外的补充召回"显式化为 stage 注册表:

- 词法核心路径不在此处(字节不动,所有 benchmark 走它);
- 每个 stage:opt-in env 开关 + 纯追加语义(不重排、不占用、不替换词法
  结果——2026-04-18 对抗排序倒置教训的延续);
- stage 之间与主检索互相隔离:单个 stage 异常吞掉并计入 warnings,不
  破坏主结果;
- 候选留痕:每个追加候选带 ``retrieval_reason``(stage 名),confidence
  low,审计可辨。

内置 stages:
- ``event_semantic``(env ``MASE_EVENT_SEMANTIC_RECALL``):bge-m3 事件行
  语义发现(原 benchmark_notetaker 内嵌逻辑收编,行为不变);
- ``llm_judge_recall``(env ``MASE_LLM_JUDGE_RECALL``):embedding 低阈值
  粗排 → 推理型 LLM 逐行精判(NoLiMa 反字面档 POC 0/68→18/68 的两级管道
  产品位;判定缓存/并行见 relevance_judge)。诊断/研发用途,延时以真机
  实测为准,对抗性跑分 lane 的 semantic-discovery 禁令同样适用。
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JUDGE_COARSE_THRESHOLD = 0.30  # 粗排低阈值:漏斗要宽,精判负责筛
JUDGE_COARSE_TOP_N = 30
JUDGE_CAP = 8


@dataclass
class StageContext:
    """stage 运行上下文:主检索已返回行的 id 集合 + DB 定位。"""

    db_path: str | Path | None
    existing_ids: set[int]
    warnings: list[str] = field(default_factory=list)


StageFn = Callable[[str, StageContext], list[dict[str, Any]]]


def _flag_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "on", "yes"}


def _fetch_rows_by_ids(ids: list[int], db_path: str | Path | None) -> dict[int, dict[str, Any]]:
    from mase_tools.memory.db_core import fetch_memory_rows

    wanted = set(ids)
    return {
        int(row["id"]): row
        for row in fetch_memory_rows(db_path=db_path, include_superseded=False)
        if int(row["id"]) in wanted
    }


def _event_semantic_stage(query: str, ctx: StageContext) -> list[dict[str, Any]]:
    """bge-m3 事件行语义发现(原 benchmark_notetaker 内嵌逻辑,行为不变)。"""
    from .event_semantic_recall import discover_events

    discovered = discover_events(query, exclude_ids=ctx.existing_ids, db_path=ctx.db_path)
    if not discovered:
        return []
    by_id = _fetch_rows_by_ids([log_id for log_id, _s in discovered], ctx.db_path)
    extras: list[dict[str, Any]] = []
    for log_id, similarity in discovered:
        row = by_id.get(log_id)
        if row is None:
            continue
        candidate = dict(row)
        candidate["_source"] = "memory_log"
        candidate["confidence"] = "low"
        candidate["retrieval_reason"] = "event_semantic_discovery"
        candidate["semantic_similarity"] = similarity
        extras.append(candidate)
    return extras


def _llm_judge_stage(query: str, ctx: StageContext) -> list[dict[str, Any]]:
    """两级管道:embedding 宽漏斗粗排 → 推理型 LLM 精判(yes 才追加)。"""
    from .event_semantic_recall import discover_events
    from .relevance_judge import judge_relevance_batch

    coarse = discover_events(
        query,
        exclude_ids=ctx.existing_ids,
        top_n=JUDGE_COARSE_TOP_N,
        threshold=JUDGE_COARSE_THRESHOLD,
        db_path=ctx.db_path,
    )
    if not coarse:
        return []
    by_id = _fetch_rows_by_ids([log_id for log_id, _s in coarse], ctx.db_path)
    ordered = [(log_id, by_id[log_id]) for log_id, _s in coarse if log_id in by_id]
    verdicts = judge_relevance_batch(
        query, [str(row["content"] or "") for _lid, row in ordered], db_path=ctx.db_path
    )
    extras: list[dict[str, Any]] = []
    for (_log_id, row), keep in zip(ordered, verdicts, strict=True):
        if not keep or len(extras) >= JUDGE_CAP:
            continue
        candidate = dict(row)
        candidate["_source"] = "memory_log"
        candidate["confidence"] = "low"
        candidate["retrieval_reason"] = "llm_judge_recall"
        extras.append(candidate)
    return extras


# 注册表:stage 名 → (opt-in env 开关, 实现)。顺序即执行顺序。
SUPPLEMENT_STAGES: dict[str, tuple[str, StageFn]] = {
    "event_semantic": ("MASE_EVENT_SEMANTIC_RECALL", _event_semantic_stage),
    "llm_judge_recall": ("MASE_LLM_JUDGE_RECALL", _llm_judge_stage),
}


def run_supplement_stages(
    query: str,
    *,
    db_path: str | Path | None,
    existing_ids: set[int],
) -> list[dict[str, Any]]:
    """执行全部已启用的补充 stage,返回追加候选(默认零 stage,零行为)。"""
    if not query:
        return []
    ctx = StageContext(db_path=db_path, existing_ids=set(existing_ids))
    extras: list[dict[str, Any]] = []
    for name, (flag, fn) in SUPPLEMENT_STAGES.items():
        if not _flag_on(flag):
            continue
        try:
            produced = fn(query, ctx)
        except Exception as exc:  # noqa: BLE001 - 补充召回失败不得破坏主检索
            ctx.warnings.append(f"stage {name} failed: {type(exc).__name__}: {exc}")
            continue
        for candidate in produced:
            cid = candidate.get("id")
            if cid is not None:
                ctx.existing_ids.add(int(cid))  # 后续 stage 不重复追加同一行
        extras.extend(produced)
    return extras


__all__ = [
    "SUPPLEMENT_STAGES",
    "StageContext",
    "run_supplement_stages",
]
