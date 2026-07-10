"""MASESystem 编排器：串起 router / notetaker / planner / executor。

本模块只保留生命周期、依赖装配、运行 trace 和最终问答主流程。事实表构建、
模式选择、长上下文规则、答案归一化等逻辑必须继续留在专门模块中，避免
编排层重新膨胀成上帝类。

依赖方向：
`engine` 调用 agent、mode、fact-sheet、trace 等下层能力；下层模块不应反向
持有 `MASESystem`，新增 math/code/multimodal agent 时应通过注册表接入。
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
    """单个 MASE 运行实例的顶层门面。

    实例级状态只保存配置、模型接口、agent 实例和后台 GC 线程。真正的检索、
    事实表压缩、执行器协作与答案抽取由 mixin 或独立模块承担。
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = resolve_config_path(config_path)
        # 启动时尽早校验配置；软问题只发事件，不中断本地 benchmark / runtime。
        # 结构化日志和指标订阅 event bus 后可以统一收集这些告警。
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
        # 记录 MASE_GC_AUTO 产生的后台线程，CLI 退出或 FastAPI shutdown 时可显式
        # join，避免 daemon 线程在 LLM 请求中途被进程回收。
        self._gc_threads: list[threading.Thread] = []
        # atexit 为 CLI、示例和集成默认提供安全 drain；超时限制避免慢模型让退出
        # 长时间卡住。
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

    def _maybe_spawn_write_time_extraction(self, thread_id: str) -> None:
        """写入时对话抽取(opt-in):后台把本会话 user 轮投影为治理 facts。

        ``MASE_WRITE_TIME_EXTRACTION=1`` 时,在 notetaker 写入后异步触发
        ``project_events(extractor='llm')``——hybrid 注入闭环的写入侧(POC
        取证:oracle 抽取假设下 knowledge-update judge 53.8→74.4,缺的正是
        写入时抽取)。幂等增量由 project_events 自带(只扫未投影事件),
        每轮触发只处理新事件。默认关;``MASE_BENCHMARK_MODE=1`` 时跳过
        (评测路径不被意外 LLM 抽取污染)。投影是派生路径,失败吞掉,
        不反向破坏主问答链路;线程挂 _gc_threads 复用 drain 基建。
        """
        if os.environ.get("MASE_WRITE_TIME_EXTRACTION", "0").strip().lower() not in {"1", "true", "on", "yes"}:
            return
        if os.environ.get("MASE_BENCHMARK_MODE", "0").strip().lower() in {"1", "true", "on", "yes"}:
            return

        def _projection_worker() -> None:
            try:
                from mase.governance.event_projection import project_events

                project_events(
                    thread_id=thread_id,
                    extractor="llm",
                    model_interface=self.model_interface,
                    # runtime 写入行是打包形态(role=assistant,"User: ..."),
                    # 必须走 dialogue-rows 扫描,否则恒零产出(真机取证)。
                    include_dialogue_rows=True,
                )
            except Exception:
                # 治理 facts 是派生索引;主 memory_log 已提交,投影失败不能
                # 反向破坏主写入(与 _gc_worker 同语义)。
                pass

        self._gc_threads = [t for t in self._gc_threads if t.is_alive()]
        _t = threading.Thread(target=_projection_worker, daemon=True, name="mase-write-time-extraction")
        _t.start()
        self._gc_threads.append(_t)

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

    @staticmethod
    def _evidence_pack_injection_mode() -> str:
        """注入模式:off / replace / hybrid。

        =1/true → replace(替换,向后兼容);=hybrid → pack 前置 + 原文 fact
        sheet 保留(行业消融实证:长对话逐字块优于纯抽取物,pack 给现行值与
        历史链,原文兜底召回缺口);企业模式默认 replace;显式 0 覆盖一切。
        """
        explicit = str(os.environ.get("MASE_EVIDENCE_PACK_INJECTION") or "").strip().lower()
        if explicit == "hybrid":
            return "hybrid"
        if explicit in {"1", "true", "yes", "on"}:
            return "replace"
        if explicit in {"0", "false", "no", "off"}:
            return "off"
        enterprise = str(os.environ.get("MASE_ENTERPRISE_MODE") or "").strip().lower()
        return "replace" if enterprise in {"1", "true", "yes", "on"} else "off"

    @staticmethod
    def _evidence_pack_injection_enabled() -> bool:
        """Return whether governed Evidence Pack should replace legacy fact sheets."""
        return MASESystem._evidence_pack_injection_mode() != "off"

    @staticmethod
    def _evidence_pack_sheet(*, user_question: str, keywords: list[str]) -> tuple[str, bool] | None:
        """编译治理层 Evidence Pack;返回 (markdown, has_substance),失败 None。

        has_substance = verified/历史链/弱线索任一非空;hybrid 模式据此决定
        是否前置(空 pack 不注入,无治理库场景零回归)。best-effort:治理层
        是增量真源,任何异常不得影响既有问答主链。
        """
        try:
            from .governance import evidence_pack as _ep

            pack = _ep.compile_evidence_pack(user_question, keywords or [user_question])
            has_substance = bool(pack.verified or pack.superseded_history or pack.semantic_hints)
            return _ep.render_markdown(pack), has_substance
        except Exception:
            return None

    def run_with_trace(
        self,
        user_question: str,
        log: bool = True,
        forced_route: dict[str, Any] | None = None,
    ) -> OrchestrationTrace:
        """执行一次完整问答并返回可审计 trace。

        主流程顺序固定为 route -> retrieve -> fact sheet -> plan -> execute ->
        record/log。每个阶段只协调下层模块，不直接内联复杂规则。
        """
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
        # 长记忆 benchmark 必须走记忆链路；小 router 偶尔会把偏好、时间线、多会话
        # 问题误判成 direct_answer，这里做最后一道保守纠偏。
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
            # 检索预算由任务类型决定，再交给 problem_classifier 做二次收敛。
            # 这样长文 QA、LongMemEval、多文档场景可以共享入口但保留不同召回宽度。
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

                # multipass 是召回增强，不是强制路径；只有返回量足够接近原检索时才
                # 替换，避免一次异常扩展把稳定召回结果覆盖掉。
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
                # LongMemEval 类任务需要完整时间线事实表。优先命中的行只作为
                # fact-sheet 构建时的高亮线索，不截断全量 chronological haystack。
                priority_ids = {int(r.get("id") or 0) for r in search_results if r.get("id") is not None}
                all_rows = self.notetaker_agent.fetch_all_chronological()
                fact_sheet = build_long_memory_full_fact_sheet(
                    user_question=user_question,
                    all_rows=all_rows,
                    priority_ids=priority_ids,
                )
                notetaker_mode = "long_memory_full_haystack"
                # hybrid 注入同样服务长记忆路径:pack(现行值/历史链)前置,
                # 完整时间线事实表保留兜底;空 pack 零注入(无治理事实的案例
                # 行为与基线逐字节一致)。replace 模式仍不进本分支(旧语义)。
                if self._evidence_pack_injection_mode() == "hybrid":
                    packed = self._evidence_pack_sheet(user_question=user_question, keywords=keywords)
                    if packed is not None:
                        pack_markdown, has_substance = packed
                        if has_substance:
                            fact_sheet = (
                                pack_markdown
                                + "\n\n---\n\n# Raw Memory Fact Sheet (fallback evidence)\n\n"
                                + fact_sheet
                            )
                            notetaker_mode = "long_memory_hybrid_pack"
            else:
                fact_sheet, notetaker_mode = self._build_fact_sheet_with_notetaker(
                    user_question=user_question,
                    search_results=search_results,
                    memory_heat=memory_heat,
                )
                # 治理层注入(P3,opt-in):executor 面对 Evidence Pack 而非记忆
                # 仓库(总纲 §4.7.1)。默认关闭,长记忆基准链路不走此分支。
                injection_mode = self._evidence_pack_injection_mode()
                if injection_mode != "off":
                    packed = self._evidence_pack_sheet(user_question=user_question, keywords=keywords)
                    if packed is not None:
                        pack_markdown, has_substance = packed
                        if injection_mode == "replace":
                            fact_sheet = pack_markdown
                            notetaker_mode = "evidence_pack"
                        elif has_substance:
                            # hybrid:pack 前置给现行值/历史链,原文 fact sheet
                            # 保留兜底;空 pack 不注入(无治理库路径零回归)。
                            fact_sheet = (
                                pack_markdown
                                + "\n\n---\n\n# Raw Memory Fact Sheet (fallback evidence)\n\n"
                                + fact_sheet
                            )
                            notetaker_mode = "evidence_pack_hybrid"
            bus.publish(
                Topics.NOTETAKER_FACT_SHEET_DONE,
                {"mode": notetaker_mode, "fact_sheet_chars": len(fact_sheet)},
                trace_id=trace_id,
            )
        executor_mode = select_executor_mode(user_question, fact_sheet)
        if use_deterministic_fact_sheet():
            # 确定性事实表模式用于 benchmark 对照；避免 planner LLM 额外噪声。
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
                # 本地小模型通常受益于 planner/workspace 提示，但默认仍少走额外 LLM
                # hop；只在问题类型路由明确允许时开启 split。
                if lme_qtype_routing_enabled() and lme_question_type() in {"single-session-preference", "multi-session"}:
                    collaboration_mode = "split"
            else:
                # 云端长记忆 executor 直接读取完整 chronological haystack；启发式
                # planner / reasoning workspace 在该链路上反而可能引入噪声。
                instruction_package = ""
                if lme_qtype_routing_enabled() and lme_question_type() in {"single-session-preference", "multi-session"}:
                    collaboration_mode = "split"
                # Iter2 逃生阀：仅环境变量显式开启 LME verifier，默认保持兼容。
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
        # evidence_assessment 是 trace 的“证据包”：记录路由、检索、模型调用、成本
        # 和工作区判断，便于之后复盘一次回答是否真的由记忆支持。
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
            # Trace 记录是可观测性增强，失败时不能影响主问答结果。
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
            # MASE_GC_AUTO=1 在写入后异步触发 entity-state fact extractor，让
            # memory_log -> entity_state 的派生索引无需 cron。默认关闭，避免每次
            # benchmark 写入都多一次 LLM 调用并污染成本/速度基线。
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
                        # entity_state 是派生索引；主 memory_log 已提交，GC 失败不能
                        # 反向破坏主写入。
                        pass

                # 记录 daemon，退出时可 join；否则 daemon=True 可能让 OS 在 LLM 请求
                # 中途回收线程，使 auto-GC 看似启动但没有可靠完成。
                self._gc_threads = [t for t in self._gc_threads if t.is_alive()]
                _t = threading.Thread(target=_gc_worker, daemon=True, name="mase-gc-auto")
                _t.start()
                self._gc_threads.append(_t)
            # 写入时对话抽取(opt-in,默认关):本会话 user 轮 → 治理 facts。
            self._maybe_spawn_write_time_extraction(thread.thread_id)
            # 人类可读审计轨迹（SQLite + Markdown 双白盒）。runtime 默认开启；
            # benchmark 应设置 MASE_AUDIT_MARKDOWN=0 或 MASE_BENCHMARK_MODE=1，
            # 避免把评测样本写进面向用户的日志。
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
