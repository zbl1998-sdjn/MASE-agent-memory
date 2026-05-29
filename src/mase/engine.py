"""MASESystem orchestrator — coordinates router/notetaker/planner/executor.

This module deliberately does NOT contain fact-sheet construction logic,
mode-selection rules, or marker tables.  Those live in dedicated modules so
new agent kinds (math/code/multimodal) can be added by writing a new
helper module + registering an agent, without editing this orchestrator.
"""
from __future__ import annotations

import atexit
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from .agent_registry import get_registry, register_builtin_agents
from .config_schema import validate_config_path
from .engine_execution import EngineExecutionMixin
from .engine_notetaker import EngineNotetakerMixin
from .event_bus import Topics, get_bus
from .fact_sheet import build_long_memory_full_fact_sheet
from .mode_selector import (
    determine_memory_heat,
    is_long_context_qa,
    is_long_memory,
    is_multidoc_long_context,
    lme_qtype_routing_enabled,
    lme_question_type,
    local_only_models_enabled,
    long_context_search_limit,
    multipass_allowed_for_task,
    select_executor_mode,
    use_deterministic_fact_sheet,
)
from .model_interface import ModelInterface, resolve_config_path
from .models import OrchestrationTrace, RouteDecision
from .notetaker import append_markdown_log
from .problem_classifier import build_retrieval_plan
from .reasoning_engine import build_reasoning_workspace
from .topic_threads import derive_thread_context
from .trace_recorder import build_trace_steps, record_trace_payload


class MASESystem(EngineNotetakerMixin, EngineExecutionMixin):
    """Top-level façade for one MASE benchmark/runtime instance."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = resolve_config_path(config_path)
        # Validate config early, but never crash on soft issues — warnings
        # surface via the event bus where the structured logger / metrics
        # can pick them up.
        validate_config_path(self.config_path, strict=False, emit_events=True)
        if os.environ.get("MASE_STRUCTURED_LOG"):
            from .structured_log import configure as _configure_structured_log

            _configure_structured_log()
        self.model_interface = ModelInterface(self.config_path)
        register_builtin_agents()
        self._agents: dict[str, Any] = get_registry().build_all(self.model_interface, self.config_path)
        self.router_agent = self._agents["router"]
        self.planner_agent = self._agents["planner"]
        self.notetaker_agent = self._agents["notetaker"]
        # Tracks live MASE_GC_AUTO daemon threads so callers (CLI exit handler,
        # FastAPI shutdown hook) can join them before the process dies and the
        # OS reaps daemon threads mid-LLM-request.
        self._gc_threads: list[threading.Thread] = []
        # atexit lets every CLI / example / integration get safe GC drain for
        # free; the timeout caps user-visible "hang" at 8s for slow LLMs.
        atexit.register(self._atexit_drain)

    def _atexit_drain(self) -> None:
        live = [t for t in self._gc_threads if t.is_alive()]
        if not live:
            return
        try:
            print(f"[mase] draining {len(live)} background GC task(s)...", flush=True)
        except Exception:
            pass
        self.join_background_tasks(timeout=8.0)

    def join_background_tasks(self, timeout: float = 8.0) -> int:
        """Block until live GC daemons finish (or timeout). Returns # joined.

        Safe to call from any thread; ignored when MASE_GC_AUTO is off and no
        threads were ever spawned. Use at CLI exit / FastAPI lifespan shutdown.
        """
        joined = 0
        for t in list(self._gc_threads):
            if t.is_alive():
                t.join(timeout=timeout)
            if not t.is_alive():
                joined += 1
        self._gc_threads = [t for t in self._gc_threads if t.is_alive()]
        return joined

    def reload(self) -> None:
        self.model_interface.reload()
        register_builtin_agents()
        self._agents = get_registry().build_all(self.model_interface, self.config_path)
        self.router_agent = self._agents["router"]
        self.planner_agent = self._agents["planner"]
        self.notetaker_agent = self._agents["notetaker"]

    def get_agent(self, name: str) -> Any:
        """Return any registered agent instance (e.g. future ``math``/``code``)."""
        return self._agents.get(name)

    def describe_models(self) -> dict[str, dict[str, Any]]:
        return {
            agent_type: self.model_interface.describe_agent(agent_type)
            for agent_type in ("router", "notetaker", "planner", "executor")
        }

    def run_with_trace(
        self,
        user_question: str,
        log: bool = True,
        forced_route: dict[str, Any] | None = None,
    ) -> OrchestrationTrace:
        bus = get_bus()
        trace_id = uuid.uuid4().hex
        model_call_start_index = len(self.model_interface.get_call_log())
        routed_payload = self.call_router(user_question)
        if forced_route:
            route_payload = {
                "action": forced_route.get("action", routed_payload.get("action", "direct_answer")),
                "keywords": list(forced_route.get("keywords") or routed_payload.get("keywords") or []),
            }
        else:
            route_payload = routed_payload
        action = str(route_payload.get("action") or "direct_answer")
        keywords = [str(item) for item in (route_payload.get("keywords") or []) if str(item).strip()]
        # Long-memory benchmarks always need memory; the tiny router sometimes
        # mis-routes preference / temporal / multi-session questions to direct_answer.
        if (is_long_memory() or is_long_context_qa()) and action != "search_memory":
            action = "search_memory"
            if not keywords:
                keywords = [user_question]
        route = RouteDecision(action=action, keywords=keywords)
        bus.publish(
            Topics.ROUTE_DECIDED,
            {"action": route.action, "keywords": route.keywords, "router_observed": routed_payload},
            trace_id=trace_id,
        )
        search_results: list[dict[str, Any]] = []
        fact_sheet = "无相关记忆。"
        memory_heat: str | None = None
        notetaker_mode = "none"
        retrieval_plan = None
        if route.action == "search_memory":
            memory_heat = determine_memory_heat(user_question)
            if is_multidoc_long_context():
                search_limit = max(15, long_context_search_limit(default=15))
            elif is_long_context_qa():
                search_limit = long_context_search_limit(default=10)
            elif is_long_memory():
                search_limit = 60
            else:
                search_limit = 5
            retrieval_plan = build_retrieval_plan(
                user_question,
                route_keywords=keywords,
                base_limit=search_limit,
            )
            search_limit = retrieval_plan.search_limit
            search_results = self.notetaker_agent.search(
                keywords or [user_question],
                full_query=user_question,
                limit=search_limit,
                **retrieval_plan.to_search_kwargs(),
            )
            try:
                from .multipass_retrieval import is_enabled as _mp_enabled
                from .multipass_retrieval import multipass_search as _mp_search
                if (retrieval_plan.use_multipass or multipass_allowed_for_task()) and _mp_enabled():
                    mp_rows = _mp_search(
                        self.notetaker_agent,
                        keywords or [user_question],
                        full_query=user_question,
                        limit=search_limit,
                    )
                    if mp_rows and len(mp_rows) >= max(1, len(search_results) // 2):
                        search_results = mp_rows
            except Exception:
                pass
            bus.publish(
                Topics.NOTETAKER_SEARCH_DONE,
                {
                    "hit_count": len(search_results),
                    "search_limit": search_limit,
                    "keywords": keywords,
                    "problem_type": retrieval_plan.classification.problem_type if retrieval_plan else "none",
                },
                trace_id=trace_id,
            )
            if is_long_memory():
                priority_ids = {int(r.get("id") or 0) for r in search_results if r.get("id") is not None}
                all_rows = self.notetaker_agent.fetch_all_chronological()
                fact_sheet = build_long_memory_full_fact_sheet(
                    user_question=user_question,
                    all_rows=all_rows,
                    priority_ids=priority_ids,
                )
                notetaker_mode = "long_memory_full_haystack"
            else:
                fact_sheet, notetaker_mode = self._build_fact_sheet_with_notetaker(
                    user_question=user_question,
                    search_results=search_results,
                    memory_heat=memory_heat,
                )
            bus.publish(
                Topics.NOTETAKER_FACT_SHEET_DONE,
                {"mode": notetaker_mode, "fact_sheet_chars": len(fact_sheet)},
                trace_id=trace_id,
            )
        executor_mode = select_executor_mode(user_question, fact_sheet)
        if use_deterministic_fact_sheet():
            planner = self._heuristic_plan(executor_mode, user_question, fact_sheet)
        else:
            planner = self._build_planner_snapshot(
                route_action=route.action, executor_mode=executor_mode, user_question=user_question, fact_sheet=fact_sheet
            )
        thread = derive_thread_context(user_question, route_keywords=keywords, search_results=search_results)
        collaboration_mode = self._select_collaboration_mode(user_question, fact_sheet, executor_mode)
        instruction_package = self._build_instruction_package(user_question, fact_sheet, planner)
        if is_long_memory():
            collaboration_mode = "off"
            if local_only_models_enabled():
                # Local small models benefit from the planner/workspace hints.
                # Keep the instruction package, but preserve the conservative
                # collaboration policy to avoid adding extra LLM hops by default.
                if lme_qtype_routing_enabled() and lme_question_type() in {"single-session-preference", "multi-session"}:
                    collaboration_mode = "split"
            else:
                # Long-memory cloud executor reads the full chronological
                # haystack itself; the heuristic planner / reasoning workspace
                # adds noise there.
                instruction_package = ""
                if lme_qtype_routing_enabled() and lme_question_type() in {"single-session-preference", "multi-session"}:
                    collaboration_mode = "split"
                # Iter2 escape hatch: env-gated verifier for LME (default off → backward compatible).
                elif str(os.environ.get("MASE_LME_VERIFY") or "").strip() in {"1", "true", "yes"}:
                    collaboration_mode = "verify"
        executor_target = self.describe_executor_target(
            mode=executor_mode,
            user_question=user_question,
            use_memory=route.action == "search_memory",
            memory_heat=memory_heat,
            executor_role="memory" if route.action == "search_memory" else "general",
        )
        executor_target["collaboration_mode"] = collaboration_mode
        bus.publish(
            Topics.EXECUTOR_CALL_START,
            {
                "executor_mode": executor_mode,
                "collaboration_mode": collaboration_mode,
                "use_memory": route.action == "search_memory",
            },
            trace_id=trace_id,
        )
        answer = self.call_executor(
            user_question=user_question,
            fact_sheet=fact_sheet,
            memory_heat=memory_heat,
            collaboration_mode=collaboration_mode,
            instruction_package=instruction_package,
        )
        bus.publish(
            Topics.EXECUTOR_CALL_DONE,
            {"executor_mode": executor_mode, "answer_chars": len(answer)},
            trace_id=trace_id,
        )
        model_calls = self.model_interface.get_call_log()[model_call_start_index:]
        evidence_assessment = {
            "router_observed": routed_payload,
            "notetaker_mode": notetaker_mode,
            "memory_heat": memory_heat,
            "collaboration_mode": collaboration_mode,
            "instruction_package": instruction_package,
            "retrieval_plan": retrieval_plan.to_dict() if retrieval_plan else None,
            "reasoning_workspace": build_reasoning_workspace(user_question, fact_sheet).to_dict(),
            "model_calls": model_calls,
            "model_call_summary": {
                "call_count": len(model_calls),
                "total_tokens": sum(int(item.get("total_tokens") or 0) for item in model_calls),
                "estimated_cost_usd": round(sum(float(item.get("estimated_cost_usd") or 0.0) for item in model_calls), 8),
                "cloud_call_count": sum(1 for item in model_calls if not item.get("is_local")),
            },
            "trace_id": trace_id,
        }
        trace_steps = build_trace_steps(
            user_question=user_question,
            route=route,
            planner=planner,
            thread=thread,
            executor_target=executor_target,
            answer=answer,
            search_results=search_results,
            fact_sheet=fact_sheet,
            evidence_assessment=evidence_assessment,
        )
        record_path = ""
        try:
            record_path = record_trace_payload(
                user_question=user_question,
                route=route,
                planner=planner,
                thread=thread,
                executor_target=executor_target,
                answer=answer,
                search_results=search_results,
                fact_sheet=fact_sheet,
                evidence_assessment=evidence_assessment,
                trace_id=trace_id,
                steps=trace_steps,
            )
        except (OSError, ValueError):
            record_path = ""
        if log:
            self.notetaker_agent.write(
                user_query=user_question,
                assistant_response=answer,
                summary=self.summarize_interaction(user_question, answer),
                thread_id=thread.thread_id,
                thread_label=thread.label,
                topic_tokens=thread.topic_tokens,
                metadata={"source": "runtime"},
            )
            # MASE_GC_AUTO=1 fires the entity-state fact extractor in a daemon
            # thread after each write so memory_log → entity_state upserts
            # happen without manual cron jobs. Default OFF to preserve the
            # benchmark baseline (LLM call per write would be a cost regression).
            if os.environ.get("MASE_GC_AUTO", "0").strip().lower() in {"1", "true", "on", "yes"}:
                try:
                    gc_limit = int(os.environ.get("MASE_GC_LIMIT", "5"))
                except ValueError:
                    gc_limit = 5

                def _gc_worker(limit: int = gc_limit) -> None:
                    try:
                        from mase_tools.memory.gc_agent import run_gc
                        run_gc(limit=limit)
                    except Exception:
                        # Best-effort; entity_state is a derived index, the
                        # primary memory_log write has already committed.
                        pass

                # Track the daemon so callers (CLI exit, FastAPI shutdown) can
                # join it before the process dies — otherwise daemon=True would
                # let the OS reap the GC mid-LLM-request, making auto-GC a ghost.
                self._gc_threads = [t for t in self._gc_threads if t.is_alive()]
                _t = threading.Thread(target=_gc_worker, daemon=True, name="mase-gc-auto")
                _t.start()
                self._gc_threads.append(_t)
            # Human-readable audit trail (SQLite + Markdown 双白盒).
            # Default ON for runtime; benchmarks should set MASE_AUDIT_MARKDOWN=0
            # (or MASE_BENCHMARK_MODE=1) to keep user-facing logs clean.
            audit_flag = os.environ.get("MASE_AUDIT_MARKDOWN", "1").strip().lower()
            bench_flag = os.environ.get("MASE_BENCHMARK_MODE", "0").strip().lower()
            if audit_flag not in {"0", "false", "off", "no"} and bench_flag not in {"1", "true", "on", "yes"}:
                try:
                    from datetime import datetime as _dt
                    today = _dt.now().strftime("%Y-%m-%d")
                    append_markdown_log(
                        today,
                        {
                            "timestamp": _dt.now().isoformat(timespec="seconds"),
                            "user_query": user_question,
                            "assistant_response": answer,
                            "semantic_summary": self.summarize_interaction(user_question, answer),
                        },
                    )
                except Exception:
                    # Audit log is best-effort; never break the main pipeline.
                    pass
        trace = OrchestrationTrace(
            route=route,
            planner=planner,
            thread=thread,
            executor_target=executor_target,
            answer=answer,
            search_results=search_results,
            fact_sheet=fact_sheet,
            evidence_assessment=evidence_assessment,
            record_path=record_path,
            trace_id=trace_id,
            steps=trace_steps,
        )
        bus.publish(
            Topics.RUN_DONE,
            {
                "executor_mode": executor_mode,
                "notetaker_mode": notetaker_mode,
                "answer_chars": len(answer),
                "search_hits": len(search_results),
            },
            trace_id=trace_id,
        )
        return trace

    def ask(self, user_question: str, log: bool = True) -> str:
        return self.run_with_trace(user_question, log=log).answer


# ---- Singleton cache ----
_SYSTEM_CACHE: dict[str, MASESystem] = {}
_SYSTEM_CACHE_LOCK = threading.Lock()


def get_system(config_path: str | Path | None = None, reload: bool = False) -> MASESystem:
    resolved_path = str(resolve_config_path(config_path))
    with _SYSTEM_CACHE_LOCK:
        system = _SYSTEM_CACHE.get(resolved_path)
        if system is None:
            system = MASESystem(resolved_path)
            _SYSTEM_CACHE[resolved_path] = system
        elif reload:
            system.reload()
    return system


def reload_system(config_path: str | Path | None = None) -> MASESystem:
    resolved_path = str(resolve_config_path(config_path))
    with _SYSTEM_CACHE_LOCK:
        system = MASESystem(resolved_path)
        _SYSTEM_CACHE[resolved_path] = system
    return system


__all__ = ["MASESystem", "get_system", "reload_system"]
