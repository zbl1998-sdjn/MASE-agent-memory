from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Benchmark runs MUST NOT pollute user-facing markdown audit logs
# (memory/logs/YYYY-MM-DD.md). Importing this module flips the flag once;
# explicit opt-in still possible via MASE_AUDIT_MARKDOWN=1.
os.environ.setdefault("MASE_BENCHMARK_MODE", "1")

try:
    from mase_tools.legacy import extract_key_entities
except Exception:
    def extract_key_entities(
        text: str,
        summary: str,
        existing: list[str] | None = None,
        limit: int = 8,
    ) -> list[str]:
        candidates = [*(existing or [])]
        for source in (text, summary):
            candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9_\-']{2,}|[\u4e00-\u9fff]{2,12}", str(source or "")))
        result: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            normalized = str(item or "").strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            result.append(normalized)
            if len(result) >= limit:
                break
        return result

from mase import MASESystem
from model_interface import load_config, resolve_config_path
from topic_threads import derive_thread_context, detect_text_language

from .baseline import baseline_ask_with_metrics
from .official_source_gap_audit import audit_official_source_gap
from .registry import load_benchmark_samples
from .schemas import BenchmarkSample, BenchmarkTurn
from .scoring import score_sample

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
MEMORY_RUNS_DIR = BASE_DIR / "memory_runs"


def _load_config_profiles() -> dict[str, Any]:
    registry_path = BASE_DIR / "config.profiles.json"
    if not registry_path.exists():
        return {}
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    return dict(payload.get("profiles") or {})


def _resolve_config_profile_name(config_path: Path, profiles: dict[str, Any]) -> str | None:
    normalized = config_path.name
    for name, data in profiles.items():
        if str(data.get("path")) == normalized:
            return name
    return None
BASELINE_SYSTEM_PROMPT = "你是一个直接回答用户问题的单体大模型。请尽量只输出最终答案，不要输出冗长思维链。"


def _merge_numeric_usage(usages: list[dict[str, Any] | None]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int | float):
                totals[key] = totals.get(key, 0.0) + float(value)
    return totals


def _aggregate_call_log(call_log: list[dict[str, Any]]) -> dict[str, Any]:
    by_agent: dict[str, dict[str, Any]] = {}
    for item in call_log:
        agent_type = str(item.get("agent_type") or "unknown")
        entry = by_agent.setdefault(
            agent_type,
            {
                "call_count": 0,
                "elapsed_seconds": 0.0,
                "usage_totals": {},
            },
        )
        entry["call_count"] += 1
        entry["elapsed_seconds"] = round(entry["elapsed_seconds"] + float(item.get("elapsed_seconds") or 0.0), 6)
        usage_totals = _merge_numeric_usage([entry.get("usage_totals"), item.get("usage")])
        entry["usage_totals"] = {key: round(value, 6) for key, value in usage_totals.items()}

    total_elapsed = round(sum(float(item.get("elapsed_seconds") or 0.0) for item in call_log), 6)
    usage_totals = {key: round(value, 6) for key, value in _merge_numeric_usage([item.get("usage") for item in call_log]).items()}
    return {
        "call_count": len(call_log),
        "elapsed_seconds": total_elapsed,
        "usage_totals": usage_totals,
        "calls": call_log,
        "by_agent": by_agent,
    }


def _load_benchmark_fallbacks() -> dict[str, Any]:
    try:
        config = load_config(resolve_config_path())
    except FileNotFoundError:
        return {}
    fallbacks = config.get("fallbacks")
    return dict(fallbacks) if isinstance(fallbacks, dict) else {}


def _summarize_sample_shapes(samples: list[BenchmarkSample]) -> dict[str, Any]:
    shape_counts: dict[str, int] = {}
    history_turn_counts: list[int] = []
    for sample in samples:
        metadata = sample.metadata if isinstance(sample.metadata, dict) else {}
        shape = str(metadata.get("history_shape") or "standard").strip() or "standard"
        shape_counts[shape] = shape_counts.get(shape, 0) + 1
        history_turn_counts.append(len(sample.history))

    if not shape_counts:
        primary_shape = "empty"
    elif len(shape_counts) == 1:
        primary_shape = next(iter(shape_counts))
    else:
        primary_shape = "mixed"

    turn_summary = {
        "min": min(history_turn_counts) if history_turn_counts else 0,
        "max": max(history_turn_counts) if history_turn_counts else 0,
        "avg": round(sum(history_turn_counts) / len(history_turn_counts), 2) if history_turn_counts else 0.0,
    }
    return {
        "primary_shape": primary_shape,
        "shape_counts": shape_counts,
        "history_turns": turn_summary,
    }


def _shape_tag(primary_shape: str) -> str:
    normalized = str(primary_shape or "").strip().lower()
    mapping = {
        "focused_input": "focused",
        "full_input": "fulltext",
        "haystack_sessions": "haystack",
        "mixed": "mixed",
        "empty": "empty",
        "standard": "standard",
    }
    return mapping.get(normalized, normalized or "standard")


def _classify_error_kind(error: str | None) -> str | None:
    if not error:
        return None
    lowered = str(error).strip().lower()
    if not lowered:
        return None
    infra_markers = [
        "connectionerror",
        "connecterror",
        "failed to connect to ollama",
        "server disconnected",
        "connection aborted",
        "connection reset",
        "connection refused",
        "actively refused",
        "10054",
        "10061",
        "remoteprotocolerror",
        "networkerror",
        "readtimeout",
        "timed out",
        "timeout",
        "httpstatuserror: server error",
        "503",
        "502",
        "504",
    ]
    if any(marker in lowered for marker in infra_markers):
        return "infra_error"
    if lowered == "baseline_skipped":
        return "skipped"
    return "execution_error"


def _count_completed(results: list[dict[str, Any]], side_key: str) -> int:
    return sum(1 for item in results if bool((item.get(side_key) or {}).get("completed")))


def _count_error_kind(results: list[dict[str, Any]], side_key: str, error_kind: str) -> int:
    return sum(1 for item in results if (item.get(side_key) or {}).get("error_kind") == error_kind)


def _collect_data_gap_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        mase = item.get("mase") or {}
        audit = mase.get("data_gap_audit") or {}
        status = str(audit.get("status") or "").strip()
        if not status:
            continue
        rows.append(
            {
                "id": item.get("id"),
                "question": item.get("question"),
                "route_action": mase.get("route_action"),
                "status": status,
                "gap_type": audit.get("gap_type"),
                "missing_from_haystack": audit.get("missing_from_haystack") or [],
                "missing_from_case_fact_sheet": audit.get("missing_from_case_fact_sheet") or [],
                "reason": audit.get("reason"),
            }
        )
    return rows


def _split_chunk_by_words(text: str, max_chars: int) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    words = cleaned.split()
    if not words:
        return [cleaned[index : index + max_chars] for index in range(0, len(cleaned), max_chars)]

    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(word) <= max_chars:
            current = word
            continue
        chunks.extend(word[index : index + max_chars] for index in range(0, len(word), max_chars))
        current = ""
    if current:
        chunks.append(current)
    return chunks


def _split_long_context_paragraph(paragraph: str, max_chars: int) -> list[str]:
    cleaned = " ".join(str(paragraph or "").split())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    fragments = [item.strip() for item in re.split(r"(?<=[.!?。！？;；:])\s+", cleaned) if item.strip()]
    if len(fragments) <= 1:
        fragments = [item.strip() for item in re.split(r"(?<=[,，])\s+", cleaned) if item.strip()]
    if len(fragments) <= 1:
        return _split_chunk_by_words(cleaned, max_chars)

    chunks: list[str] = []
    current = ""
    for fragment in fragments:
        if len(fragment) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_chunk_by_words(fragment, max_chars))
            continue
        candidate = f"{current} {fragment}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = fragment
    if current:
        chunks.append(current)
    return chunks


def _chunk_context(context: str, max_chars: int = 1200) -> list[str]:
    cleaned = context.strip()
    if not cleaned:
        return []
    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_context_paragraph(paragraph, max_chars))
            continue
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _compact_snippet(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    trimmed = cleaned[:limit].rsplit(" ", 1)[0].strip()
    return trimmed or cleaned[:limit]


def _benchmark_history_summary(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""

    language = detect_text_language(cleaned)
    if language == "en":
        return _compact_snippet(cleaned, 220)

    snippet = cleaned
    for marker in ("。", "！", "？", "!", "?"):
        position = cleaned.find(marker)
        if 0 <= position <= 180:
            snippet = cleaned[: position + 1].strip()
            break

    compact = _compact_snippet(snippet, 40)
    return f"基准历史：{compact}".strip()[:48]


def _dedupe_strings(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
    return result


def _ingest_turns_into_mase(system: MASESystem, turns: list[BenchmarkTurn], benchmark_question_id: str | None = None) -> None:
    benchmark_turn_index = 0

    def _write_turn(user_turn: BenchmarkTurn, assistant_response: str, source: str) -> None:
        nonlocal benchmark_turn_index
        benchmark_turn_index += 1
        thread = derive_thread_context(user_turn.content)
        language = detect_text_language(user_turn.content)
        summary = _benchmark_history_summary(user_turn.content)
        if language == "en":
            key_entities = _dedupe_strings(
                [
                    *extract_key_entities(user_turn.content, user_turn.content, existing=[], limit=12),
                    *thread.topic_tokens,
                ]
            )[:8]
        else:
            key_entities = _dedupe_strings(
                [
                    *thread.topic_tokens,
                    *extract_key_entities(user_turn.content, summary, existing=thread.topic_tokens, limit=8),
                ]
            )[:6]
        metadata: dict[str, Any] = {
            "source": source,
            "source_language": language,
            "benchmark_turn_index": benchmark_turn_index,
        }
        if user_turn.timestamp:
            metadata["timestamp"] = user_turn.timestamp
        if user_turn.session_id:
            metadata["session_id"] = user_turn.session_id
        if benchmark_question_id:
            metadata["benchmark_question_id"] = benchmark_question_id
        system.notetaker_agent.write(
            user_query=user_turn.content,
            assistant_response=assistant_response,
            summary=summary,
            key_entities=key_entities,
            thread_id=thread.thread_id,
            thread_label=thread.label,
            topic_tokens=thread.topic_tokens,
            metadata=metadata,
        )

    pending_user: BenchmarkTurn | None = None
    for turn in turns:
        if turn.role == "user":
            if pending_user is not None:
                _write_turn(pending_user, "", "benchmark_history_incomplete")
            pending_user = turn
            continue

        user_turn = pending_user or BenchmarkTurn(role="user", content="")
        _write_turn(user_turn, turn.content, "benchmark_history")
        pending_user = None

    if pending_user is not None:
        _write_turn(pending_user, "", "benchmark_history_incomplete")


def _ingest_context_into_mase(system: MASESystem, context: str) -> None:
    for index, chunk in enumerate(_chunk_context(context), start=1):
        thread = derive_thread_context(chunk)
        language = detect_text_language(chunk)
        summary = _benchmark_history_summary(chunk) or f"上下文片段{index}：{chunk[:18]}".strip()[:48]
        title = _compact_snippet(summary or chunk, 120 if language == "en" else 48)
        key_entities = _dedupe_strings(
            [
                *extract_key_entities(chunk, summary, existing=thread.topic_tokens, limit=12 if language == "en" else 8),
                *thread.topic_tokens,
            ]
        )[:8 if language == "en" else 6]
        system.notetaker_agent.write(
            user_query=title,
            assistant_response=chunk,
            summary=summary,
            key_entities=key_entities,
            thread_id=thread.thread_id,
            thread_label=thread.label,
            topic_tokens=thread.topic_tokens,
            metadata={
                "source": "benchmark_context",
                "chunk_index": index,
                "source_language": language,
                "chunk_title": title,
            },
        )


def _build_baseline_conversation(sample: BenchmarkSample) -> list[dict[str, str]]:
    conversation: list[dict[str, str]] = []
    for turn in sample.history:
        conversation.append({"role": turn.role, "content": turn.content})
    if sample.context:
        conversation.extend(
            [
                {"role": "user", "content": f"以下是你必须依赖的上下文：\n{sample.context}"},
                {"role": "assistant", "content": "好的，我会仅基于提供的上下文回答后续问题。"},
            ]
        )
    return conversation


def _format_question(sample: BenchmarkSample) -> str:
    return sample.question


class BenchmarkRunner:
    def __init__(
        self,
        baseline_profile: str = "ollama-qwen25-7b",
        baseline_timeout_seconds: float | None = None,
        sample_retry_count: int | None = None,
        sample_retry_delay_seconds: float | None = None,
    ) -> None:
        self.fallbacks = _load_benchmark_fallbacks()
        self.baseline_profile = baseline_profile
        self.baseline_timeout_seconds = baseline_timeout_seconds
        self.sample_retry_count = max(
            0,
            int(
                sample_retry_count
                if sample_retry_count is not None
                else self.fallbacks.get("benchmark_sample_retry_count", 2)
            ),
        )
        self.sample_retry_delay_seconds = float(
            sample_retry_delay_seconds
            if sample_retry_delay_seconds is not None
            else self.fallbacks.get("benchmark_sample_retry_delay", 6)
        )

    def _baseline_enabled(self) -> bool:
        normalized = str(self.baseline_profile or "").strip().lower()
        return normalized not in {"", "none", "disabled", "skip", "off"}

    def _safe_score(self, item: dict[str, Any], engine: str) -> dict[str, Any]:
        """Safely get score dict from a result item, returning zeroed defaults on error."""
        return ((item.get(engine) or {}).get("score") or {"all_matched": False, "score": 0.0})

    def _safe_metrics(self, item: dict[str, Any], engine: str) -> dict[str, Any]:
        """Safely get metrics dict from a result item."""
        return ((item.get(engine) or {}).get("metrics") or {})

    def _build_scoreboard(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        data_gap_count = sum(
            1 for item in results if ((item.get("mase") or {}).get("data_gap_audit") or {}).get("status") == "data_gap"
        )
        candidate_data_gap_count = sum(
            1 for item in results if ((item.get("mase") or {}).get("data_gap_audit") or {}).get("status") == "candidate_data_gap"
        )
        retrieval_gap_count = sum(
            1 for item in results if ((item.get("mase") or {}).get("data_gap_audit") or {}).get("status") == "retrieval_gap"
        )
        mase_pass_count = sum(1 for item in results if self._safe_score(item, "mase").get("all_matched"))
        return {
            "mase_pass_count": mase_pass_count,
            "mase_adjusted_pass_count": mase_pass_count + data_gap_count,
            "mase_effective_fail_count": sum(
                1
                for item in results
                if not self._safe_score(item, "mase").get("all_matched")
                and ((item.get("mase") or {}).get("data_gap_audit") or {}).get("status") != "data_gap"
            ),
            "mase_data_gap_count": data_gap_count,
            "mase_candidate_data_gap_count": candidate_data_gap_count,
            "mase_retrieval_gap_count": retrieval_gap_count,
            "baseline_pass_count": sum(1 for item in results if self._safe_score(item, "baseline").get("all_matched")),
            "mase_completed_count": _count_completed(results, "mase"),
            "baseline_completed_count": _count_completed(results, "baseline"),
            "mase_infra_error_count": _count_error_kind(results, "mase", "infra_error"),
            "baseline_infra_error_count": _count_error_kind(results, "baseline", "infra_error"),
            "mase_execution_error_count": _count_error_kind(results, "mase", "execution_error"),
            "baseline_execution_error_count": _count_error_kind(results, "baseline", "execution_error"),
            "mase_avg_score": round(sum(float(self._safe_score(item, "mase").get("score", 0.0)) for item in results) / max(1, len(results)), 4),
            "baseline_avg_score": round(sum(float(self._safe_score(item, "baseline").get("score", 0.0)) for item in results) / max(1, len(results)), 4),
            "mase_avg_wall_clock_seconds": round(
                sum(float(self._safe_metrics(item, "mase").get("wall_clock_seconds") or 0.0) for item in results) / max(1, len(results)),
                4,
            ),
            "baseline_avg_elapsed_seconds": round(
                sum(float(self._safe_metrics(item, "baseline").get("elapsed_seconds") or 0.0) for item in results) / max(1, len(results)),
                4,
            ),
            "mase_usage_totals": {
                key: round(value, 6)
                for key, value in _merge_numeric_usage([self._safe_metrics(item, "mase").get("usage_totals") for item in results]).items()
            },
            "baseline_usage_totals": {
                key: round(value, 6)
                for key, value in _merge_numeric_usage([self._safe_metrics(item, "baseline").get("usage") for item in results]).items()
            },
        }

    def _print_progress(
        self,
        benchmark_name: str,
        index: int,
        total: int,
        result: dict[str, Any],
        started_at: float,
        results: list[dict[str, Any]],
    ) -> None:
        elapsed_total = max(0.0, time.perf_counter() - started_at)
        avg_seconds = elapsed_total / max(1, index)
        remaining = max(0, total - index)
        eta_seconds = avg_seconds * remaining
        mase = result.get("mase") or {}
        mase_score = float(((mase.get("score") or {}).get("score")) or 0.0)
        mase_status = "PASS" if (mase.get("score") or {}).get("all_matched") else ("ERROR" if mase.get("error") else "FAIL")
        gap_status = str(((mase.get("data_gap_audit") or {}).get("status")) or "-")
        route_action = str(mase.get("route_action") or "-")
        pass_count = sum(1 for item in results if (item.get("mase") or {}).get("score", {}).get("all_matched"))
        pass_rate = (pass_count / max(1, len(results))) * 100
        wall_clock = float((mase.get("metrics") or {}).get("wall_clock_seconds") or 0.0)
        print(
            f"[benchmark:{benchmark_name}] {index}/{total} id={result.get('id')} "
            f"status={mase_status} score={mase_score:.2f} route={route_action} gap={gap_status} "
            f"case={wall_clock:.1f}s avg={avg_seconds:.1f}s eta={eta_seconds:.1f}s pass_rate={pass_rate:.1f}%",
            flush=True,
        )

    def _run_sample_once(self, sample: BenchmarkSample, run_root: Path, attempt: int) -> dict[str, Any]:
        case_memory_dir = run_root / sample.id
        if case_memory_dir.exists():
            shutil.rmtree(case_memory_dir)
        case_memory_dir.mkdir(parents=True, exist_ok=True)
        previous_memory_dir = os.environ.get("MASE_MEMORY_DIR")
        previous_question_reference_time = os.environ.get("MASE_QUESTION_REFERENCE_TIME")
        previous_task_type = os.environ.get("MASE_TASK_TYPE")
        previous_lveval_dataset = os.environ.get("MASE_LVEVAL_DATASET")
        os.environ["MASE_MEMORY_DIR"] = str(case_memory_dir.resolve())
        os.environ["MASE_TASK_TYPE"] = str(sample.task_type or "")
        ds_name = ""
        if isinstance(sample.metadata, dict):
            ds_name = str(sample.metadata.get("dataset") or "").strip().lower()
        os.environ["MASE_LVEVAL_DATASET"] = ds_name
        # iter3: expose question_id bucket so mode_selector can route verifier
        # (abstention / gpt4_gen / regular) — only active when
        # MASE_LME_ROUTE_BY_QID=1. Default off → no behaviour change.
        qid = str(sample.id or "")
        if qid.endswith("_abs"):
            os.environ["MASE_QID_BUCKET"] = "abstention"
        elif qid.startswith("gpt4_"):
            os.environ["MASE_QID_BUCKET"] = "gpt4_gen"
        else:
            os.environ["MASE_QID_BUCKET"] = "regular"
        os.environ["MASE_CURRENT_QID"] = qid
        # iter5: expose LongMemEval question_type (single-session-user / multi-session
        # / temporal-reasoning / single-session-preference / knowledge-update) so that
        # mode_selector + multipass_retrieval can apply per-type routing
        # (deep-reason executor for temporal, boosted rerank for multi-session).
        # Only active when MASE_LME_QTYPE_ROUTING=1. Default off → no behaviour change.
        try:
            qtype = (sample.metadata or {}).get("question_type") if isinstance(sample.metadata, dict) else None
        except Exception:
            qtype = None
        os.environ["MASE_QTYPE"] = str(qtype or "").strip().lower()
        try:
            system = MASESystem()
            if sample.history:
                _ingest_turns_into_mase(system, sample.history, benchmark_question_id=sample.id)
            if sample.context:
                _ingest_context_into_mase(system, sample.context)

            question = _format_question(sample)
            question_reference_time = ""
            if isinstance(sample.metadata, dict):
                question_reference_time = str(sample.metadata.get("question_date") or "").strip()
            if question_reference_time:
                os.environ["MASE_QUESTION_REFERENCE_TIME"] = question_reference_time
            else:
                os.environ.pop("MASE_QUESTION_REFERENCE_TIME", None)
            mase_trace = None
            mase_answer = ""
            mase_error: str | None = None
            system.model_interface.reset_call_log()
            mase_started = time.perf_counter()
            try:
                forced_route = None
                if sample.task_type in {"long_context_qa", "long_memory"}:
                    forced_route = {
                        "action": "search_memory",
                        "keywords": ["__FULL_QUERY__"],
                    }
                mase_trace = system.run_with_trace(question, log=False, forced_route=forced_route)
                mase_answer = mase_trace.answer
            except Exception as error:
                mase_error = f"{type(error).__name__}: {error}"
            mase_metrics = _aggregate_call_log(system.model_interface.get_call_log())
            mase_metrics["wall_clock_seconds"] = round(time.perf_counter() - mase_started, 6)

            baseline_conversation = _build_baseline_conversation(sample)
            baseline_answer = ""
            baseline_error: str | None = None
            baseline_overrides: dict[str, Any] | None = None
            if self._baseline_enabled() and sample.task_type in {"long_memory", "long_context_qa"} and self.baseline_timeout_seconds is not None:
                baseline_overrides = {"timeout_seconds": self.baseline_timeout_seconds}
            baseline_result: dict[str, Any] | None = None
            if self._baseline_enabled():
                try:
                    baseline_result = baseline_ask_with_metrics(
                        baseline_conversation,
                        question,
                        profile=self.baseline_profile,
                        system_prompt=BASELINE_SYSTEM_PROMPT,
                        overrides=baseline_overrides,
                    )
                    baseline_answer = str(baseline_result["answer"])
                except Exception as error:
                    baseline_error = f"{type(error).__name__}: {error}"
            else:
                baseline_error = "baseline_skipped"

            mase_score = score_sample(sample, mase_answer)
            baseline_score = score_sample(sample, baseline_answer)
            try:
                from .llm_judge import maybe_upgrade_score
                _qt = (sample.metadata or {}).get("question_type") if isinstance(sample.metadata, dict) else None
                mase_score = maybe_upgrade_score(
                    mase_score,
                    question=sample.question,
                    ground_truth=sample.ground_truth,
                    answer=mase_answer,
                    question_type=_qt,
                    benchmark=sample.benchmark,
                )
                baseline_score = maybe_upgrade_score(
                    baseline_score,
                    question=sample.question,
                    ground_truth=sample.ground_truth,
                    answer=baseline_answer,
                    question_type=_qt,
                    benchmark=sample.benchmark,
                )
            except Exception:
                pass
            mase_data_gap_audit = audit_official_source_gap(
                sample_id=sample.id,
                benchmark=sample.benchmark,
                ground_truth=sample.ground_truth,
                case_memory_dir=case_memory_dir,
            )
            mase_error_kind = _classify_error_kind(mase_error)
            baseline_error_kind = _classify_error_kind(baseline_error)
            return {
                "id": sample.id,
                "benchmark": sample.benchmark,
                "task_type": sample.task_type,
                "question": sample.question,
                "ground_truth": sample.ground_truth,
                "sample_metadata": sample.metadata,
                "case_memory_dir": str(case_memory_dir),
                "attempt_index": attempt,
                "mase": {
                    "answer": mase_answer,
                    "score": mase_score,
                    "route_action": mase_trace.route.action if mase_trace else None,
                    "keywords": mase_trace.route.keywords if mase_trace else [],
                    "planner": mase_trace.planner.to_dict() if mase_trace else None,
                    "thread": mase_trace.thread.to_dict() if mase_trace else None,
                    "executor_target": mase_trace.executor_target if mase_trace else None,
                    "metrics": mase_metrics,
                    "data_gap_audit": mase_data_gap_audit,
                    "error": mase_error,
                    "error_kind": mase_error_kind,
                    "completed": mase_error is None,
                },
                "baseline": {
                    "answer": baseline_answer,
                    "score": baseline_score,
                    "metrics": baseline_result,
                    "error": baseline_error,
                    "error_kind": baseline_error_kind,
                    "completed": baseline_result is not None,
                },
            }
        finally:
            if previous_memory_dir is None:
                os.environ.pop("MASE_MEMORY_DIR", None)
            else:
                os.environ["MASE_MEMORY_DIR"] = previous_memory_dir
            if previous_question_reference_time is None:
                os.environ.pop("MASE_QUESTION_REFERENCE_TIME", None)
            else:
                os.environ["MASE_QUESTION_REFERENCE_TIME"] = previous_question_reference_time
            if previous_task_type is None:
                os.environ.pop("MASE_TASK_TYPE", None)
            else:
                os.environ["MASE_TASK_TYPE"] = previous_task_type
            if previous_lveval_dataset is None:
                os.environ.pop("MASE_LVEVAL_DATASET", None)
            else:
                os.environ["MASE_LVEVAL_DATASET"] = previous_lveval_dataset

    def run_sample(self, sample: BenchmarkSample, run_root: Path) -> dict[str, Any]:
        max_attempts = self.sample_retry_count + 1
        attempt_rows: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None

        for attempt in range(1, max_attempts + 1):
            result = self._run_sample_once(sample=sample, run_root=run_root, attempt=attempt)
            final_result = result
            mase_infra_error = (result.get("mase") or {}).get("error_kind") == "infra_error"
            baseline_infra_error = (result.get("baseline") or {}).get("error_kind") == "infra_error"
            attempt_rows.append(
                {
                    "attempt": attempt,
                    "case_memory_dir": result.get("case_memory_dir"),
                    "mase_error": (result.get("mase") or {}).get("error"),
                    "mase_error_kind": (result.get("mase") or {}).get("error_kind"),
                    "baseline_error": (result.get("baseline") or {}).get("error"),
                    "baseline_error_kind": (result.get("baseline") or {}).get("error_kind"),
                    # Retry decision today only looks at MASE side; baseline flag is
                    # surfaced here so post-hoc analysis can spot runs where the
                    # baseline silently collapsed while MASE succeeded. Do NOT change
                    # retry semantics here without a product decision.
                    "mase_infra_error": mase_infra_error,
                    "baseline_infra_error": baseline_infra_error,
                }
            )
            if not mase_infra_error:
                break
            if attempt < max_attempts:
                time.sleep(self.sample_retry_delay_seconds * attempt)

        if final_result is None:
            raise RuntimeError(f"样本 {sample.id} 未产生任何结果。")

        final_result["attempt_count"] = len(attempt_rows)
        final_result["retry_summary"] = {
            "max_attempts": max_attempts,
            "used_retry": len(attempt_rows) > 1,
            "attempts": attempt_rows,
        }
        return final_result

    def run_benchmark(
        self,
        benchmark_name: str,
        sample_limit: int | None = None,
        path: str | None = None,
        config: str | None = None,
        split: str | None = None,
    ) -> dict[str, Any]:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        samples = load_benchmark_samples(
            benchmark_name,
            sample_limit=sample_limit,
            path=path,
            config=config,
            split=split,
        )
        sample_shape_summary = _summarize_sample_shapes(samples)
        run_label = f"{benchmark_name}-{_shape_tag(sample_shape_summary['primary_shape'])}"
        results: list[dict[str, Any]] = []
        run_root = MEMORY_RUNS_DIR / f"benchmark-{run_label}-{run_id}"
        if run_root.exists():
            shutil.rmtree(run_root)
        run_root.mkdir(parents=True, exist_ok=True)
        results_path = RESULTS_DIR / f"benchmark-{run_label}-{run_id}.json"
        started_at = time.perf_counter()
        print(
            f"[benchmark:{benchmark_name}] start samples={len(samples)} "
            f"shape={sample_shape_summary['primary_shape']} shape_counts={sample_shape_summary['shape_counts']} "
            f"history_turns={sample_shape_summary['history_turns']} path={path or 'hf-default'} "
            f"memory_dir={run_root} results_path={results_path}",
            flush=True,
        )
        for index, sample in enumerate(samples, start=1):
            result = self.run_sample(sample, run_root=run_root)
            results.append(result)
            self._print_progress(benchmark_name, index, len(samples), result, started_at, results)
            partial_summary = {
                "run_id": run_id,
                "benchmark": benchmark_name,
                "sample_count": len(results),
                "planned_sample_count": len(samples),
                "results": results,
                "scoreboard": self._build_scoreboard(results),
                "data_gap_audits": _collect_data_gap_rows(results),
                "memory_dir": str(run_root),
                "results_path": str(results_path),
                "dataset_path": path,
                "dataset_config": config,
                "dataset_split": split,
                "dataset_shape": sample_shape_summary["primary_shape"],
                "dataset_shape_counts": sample_shape_summary["shape_counts"],
                "history_turns": sample_shape_summary["history_turns"],
                "completed": index == len(samples),
            }
            results_path.write_text(json.dumps(partial_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {
            "run_id": run_id,
            "benchmark": benchmark_name,
            "sample_count": len(results),
            "results": results,
            "scoreboard": self._build_scoreboard(results),
            "data_gap_audits": _collect_data_gap_rows(results),
            "memory_dir": str(run_root),
            "dataset_path": path,
            "dataset_config": config,
            "dataset_split": split,
            "dataset_shape": sample_shape_summary["primary_shape"],
            "dataset_shape_counts": sample_shape_summary["shape_counts"],
            "history_turns": sample_shape_summary["history_turns"],
            "completed": True,
        }
        summary["results_path"] = str(results_path)
        profiles = _load_config_profiles()
        resolved_profile = _resolve_config_profile_name(resolve_config_path(), profiles)
        summary["config_profile"] = resolved_profile
        results_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"[benchmark:{benchmark_name}] done samples={len(results)} "
            f"shape={sample_shape_summary['primary_shape']} "
            f"mase_pass={summary['scoreboard']['mase_pass_count']} "
            f"data_gap={summary['scoreboard']['mase_data_gap_count']} "
            f"effective_fail={summary['scoreboard']['mase_effective_fail_count']} "
            f"avg={summary['scoreboard']['mase_avg_wall_clock_seconds']:.1f}s results_path={results_path}",
            flush=True,
        )
        return summary
