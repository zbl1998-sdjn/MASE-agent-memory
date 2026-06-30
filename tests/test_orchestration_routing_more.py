from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from mase import answer_normalization as ans
from mase import multipass_retrieval as mp
from mase import router
from mase.problem_classifier import ProblemClassification, RetrievalPlan, ProblemClassifier, build_retrieval_plan
from src.mase import langgraph_orchestrator as orch
from mase_tools.cli import memory_diff


def test_answer_normalization_covers_fallbacks_and_candidate_tables() -> None:
    assert ans.normalize_abstention_answer("") == "You did not mention this information."
    assert ans.normalize_abstention_answer("I don't know from the notes.") == "You did not mention this information."
    assert ans.normalize_abstention_answer("You did not mention this information already.") == (
        "You did not mention this information already."
    )
    assert ans.normalize_abstention_answer("Keep this answer") == "Keep this answer"

    fact_sheet = "\n".join(
        [
            "[C1] name=Alice | evidence",
            "[C2] name=alice | duplicate",
            "[C3] name=Bob | evidence",
        ]
    )
    assert ans.candidate_names_from_fact_sheet(fact_sheet) == ["Alice", "Bob"]
    assert ans.extract_answer("plain", "", "What is this?") == "Based on current records, I can't answer this question."
    assert ans.extract_answer("plain", "", "这是什么？") == "根据现有记录，我无法回答这个问题。"
    assert ans.extract_answer("plain", "model text", "q", "- Deterministic temporal answer: Golden answer") == "Golden answer"
    assert ans.extract_answer("grounded_analysis", '{"final_answer": "final"}', "q") == "final"
    assert ans.extract_answer("grounded_analysis", '{"sufficient": false}', "What is the answer?") == (
        "Based on current records, I can't answer this question."
    )
    assert ans.extract_answer("grounded_disambiguation", "I choose bob because...", "q", fact_sheet) == "Bob"
    assert ans.extract_answer("grounded_disambiguation", "raw", "q", "候选裁决表\n[C1] name=Chen | only") == "Chen"


def test_answer_normalization_lookup_helpers_cover_edge_cases() -> None:
    order = ans.normalize_three_event_order_answer(
        "1. submitting the form 2. booking the room 3. hosting the event",
        "What is the order of the three events?",
    )
    assert order == "First, submitting the form. Then, booking the room. Finally, hosting the event."
    assert ans.normalize_three_event_order_answer("", "order from first to last") == ""
    assert ans.normalize_three_event_order_answer("1. only", "order from first to last") == ""
    assert ans.normalize_three_event_order_answer("1. A 2. B 3. C", "What happened?") == ""

    assert ans.normalize_preference_profile_answer("") == ""
    assert ans.normalize_preference_profile_answer("The user would prefer quiet hotels based on the evidence: x") == (
        "The user would prefer quiet hotels"
    )
    assert ans.normalize_preference_profile_answer("Unrelated answer") == ""

    assert ans.normalize_other_options_answer("1. Alpha - why 2. Beta. 3. Gamma 4. Delta", "What were the other four options?") == (
        "I suggested 'alpha', 'beta', 'gamma', and 'delta'."
    )
    assert ans.normalize_other_options_answer("1. Alpha 2. Beta", "What were the other four options?") == ""
    assert ans.normalize_other_options_answer("1. Alpha 2. Beta 3. Gamma 4. Delta", "What did I suggest?") == ""

    compact_cases = [
        ("Yes, that is correct", "Is that correct?", "Yes."),
        ("No, it changed", "Did it change?", "No."),
        ("The answer is Monday", "What day of the week was it?", "Monday"),
        ("Cafe Azul - located at Market Street", "Which cafe did I mention?", "Cafe Azul at Market Street."),
        ("GR-12", "Which trail did I hike?", "The GR-12 trail."),
        ("Maya wore a red coat", "What did Maya wear?", "Maya was wearing a red coat."),
        ("Ruby, Python, and PHP", "Which back-end programming language did you recommend?", "I recommended learning Ruby, Python, or PHP as a back-end programming language."),
        ("6S", "Which algorithm is implemented in SIAC_GEE?", "The 6S algorithm is implemented in the SIAC_GEE tool."),
        ("Pilsner and Lager", "What type of beer did you recommend for the recipe?", "I recommended using a Pilsner or Lager for the recipe."),
        ("1:10", "How should I dilute lavender with a carrier oil before use?", "The recommended ratio is 1:10, meaning one part lavender to ten parts carrier oil."),
        ("3", "How many times did the band play the anthem at Central Park?", "The Band played the Anthem 3 times at Central Park."),
        ("Blue jacket.", "What color jacket was it?", "Blue jacket."),
    ]
    for content, question, expected in compact_cases:
        assert ans.normalize_compact_lookup_answer(content, question) == expected
    assert ans.normalize_compact_lookup_answer("", "Is it?") == ""
    assert ans.normalize_compact_lookup_answer("plain answer", "Tell me") == ""

    assert ans.extract_ordinal_index_from_question("What was the 8th list item?") == 8
    assert ans.extract_ordinal_index_from_question("What was the twelfth list item?") == 12
    assert ans.extract_ordinal_index_from_question("No ordinal here") == 0
    assert ans.extract_numbered_list_item("1. **Alpha** 2. Beta", 1) == "Alpha"
    assert ans.extract_numbered_list_item("", 1) == ""
    assert ans.extract_numbered_list_item("no numbering", 1) == ""
    assert ans.extract_numbered_list_item("1. Alpha", 3) == ""


def test_fact_sheet_direct_lookup_helpers() -> None:
    fact_sheet = "\n".join(
        [
            "[1] row | packing list: 1. socks 2. charger 3. passport 4. adapter",
            "[2] row | grocery list: 1. apples 2. pears",
        ]
    )
    assert ans.extract_fact_sheet_list_lookup_answer("What was the third item from the packing list?", fact_sheet) == "passport"
    assert ans.extract_fact_sheet_list_lookup_answer("What item was it?", fact_sheet) == ""

    schedule = "\n".join(
        [
            "| | Lead | Backup | Notes | Owner |",
            "| Monday | Alice | Bob | clean | Carol |",
        ]
    )
    assert ans.extract_fact_sheet_shift_lookup_answer("What shift was Bob assigned on Monday?", schedule) == (
        "Bob was assigned to the Backup on Mondays."
    )
    assert ans.extract_fact_sheet_shift_lookup_answer("What shift was Bob assigned?", schedule) == ""
    assert ans.extract_fact_sheet_shift_lookup_answer("What shift was Bob assigned on Monday?", "no table") == ""


def test_router_parsing_and_agent_contracts() -> None:
    assert router.keyword_router_decision("我们之前聊的预算") == "search_memory"
    assert router.keyword_router_decision("写一个函数") == "direct_answer"
    assert router.filter_keywords(["", router.FULL_QUERY_SENTINEL, "预算"]) == ["预算"]
    assert router.parse_router_response('```json\n{"action":"search_memory","keywords":["端口"]}\n```') == {
        "action": "search_memory",
        "keywords": ["端口"],
    }
    assert router.parse_router_response('text "action": "bad", "keywords": ["a", "b", "c", "d"]') == {
        "action": "direct_answer",
        "keywords": ["a", "b", "c"],
    }
    assert router.parse_router_response("not json") == {"action": "direct_answer", "keywords": []}

    class FakeModel:
        def __init__(self, content: str) -> None:
            self.content = content
            self.calls: list[dict[str, Any]] = []

        def chat(self, agent_type: str, messages: list[dict[str, str]], override_system_prompt: str | None = None) -> dict[str, Any]:
            self.calls.append({"agent_type": agent_type, "messages": messages, "prompt": override_system_prompt})
            return {"message": {"content": self.content}}

    empty_model = FakeModel("{}")
    assert router.RouterAgent(empty_model).decide("   ") == {"action": "direct_answer", "keywords": []}
    model = FakeModel('{"action":"search_memory","keywords":"not-list"}')
    assert router.RouterAgent(model).decide("端口是多少？") == {"action": "search_memory", "keywords": []}
    assert model.calls[0]["agent_type"] == "router"


def test_problem_classifier_public_serialization_and_plan_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = ProblemClassifier()
    cases = [
        ("actually I corrected the port", "conflict"),
        ("之前几次我们都讨论了什么？", "cross_session"),
        ("list all budgets", "aggregate"),
        ("What do I prefer for coffee?", "preference"),
        ("what should I buy for camping?", "preference"),
        ("How do we run the release workflow?", "procedural"),
        ("那个值是什么？", "current_state"),
        ("完全普通的问题", "general_recall"),
    ]
    for question, expected in cases:
        assert classifier.classify(question).problem_type == expected

    monkeypatch.setenv("MASE_QTYPE", "single-session-preference")
    assert classifier.classify("recommend a camera").problem_type == "preference"
    pref_plan = build_retrieval_plan("recommend a camera", base_limit=1)
    assert pref_plan.search_limit == 10
    assert "__FULL_QUERY__" in pref_plan.query_variants

    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")
    assert classifier.classify("What is the setting?").problem_type == "update"
    update_style = build_retrieval_plan("What was it initially and what is it currently?", route_keywords=["setting"], base_limit=2)
    assert update_style.include_history is True
    assert "setting" in update_style.query_variants

    monkeypatch.delenv("MASE_QTYPE", raising=False)
    low_plan = build_retrieval_plan("那个", base_limit=0)
    assert low_plan.search_limit >= 8
    assert low_plan.use_hybrid_rerank is True
    assert low_plan.to_search_kwargs()["scope_filters"]["problem_type"] == "low_confidence"
    assert isinstance(low_plan.to_dict()["classification"]["signals"], list)

    serialized = RetrievalPlan(
        classification=ProblemClassification("custom", ("a",), "high"),
        search_limit=3,
        include_history=True,
        use_hybrid_rerank=False,
        use_multipass=True,
        query_variants=("x",),
        reasons=("r",),
    ).to_dict()
    assert serialized["classification"] == {"problem_type": "custom", "signals": ["a"], "confidence": "high"}


@pytest.fixture()
def orch_state() -> dict[str, Any]:
    return {
        "messages": [],
        "user_query": "项目代号是什么",
        "router_decision": "",
        "memory_context": "",
        "task_plan": "",
        "action_results": "",
        "executor_result": "",
        "error_log": [],
    }


def test_langgraph_singletons_seed_keywords_and_fallback_nodes(monkeypatch: pytest.MonkeyPatch, orch_state: dict[str, Any]) -> None:
    class FakeMI:
        pass

    class FakeExecutor:
        def __init__(self, model_interface: Any) -> None:
            self.model_interface = model_interface

        def execute(self, *, query: str, memory_context: str) -> str:
            return f"{query}|{memory_context}"

    class FakeRouterAgent:
        def __init__(self, model_interface: Any) -> None:
            self.model_interface = model_interface

    class FakePlanner:
        def __init__(self, model_interface: Any) -> None:
            self.model_interface = model_interface

        def plan(self, *, query: str, memory_context: str) -> str:
            raise RuntimeError("planner down")

    fake_default_notetaker = SimpleNamespace(model_interface=None)

    monkeypatch.setattr(orch, "mase_model_interface", None)
    monkeypatch.setattr(orch, "executor_agent", None)
    monkeypatch.setattr(orch, "_router_agent", None)
    monkeypatch.setattr(orch, "_notetaker_agent", None)
    monkeypatch.setattr(orch, "_planner_agent", None)
    monkeypatch.setattr(orch, "ModelInterface", lambda: FakeMI())
    monkeypatch.setattr(orch, "ExecutorAgent", FakeExecutor)
    monkeypatch.setattr(orch, "RouterAgent", FakeRouterAgent)
    monkeypatch.setattr(orch, "PlannerAgent", FakePlanner)
    monkeypatch.setattr(orch, "DEFAULT_NOTETAKER", fake_default_notetaker)

    assert orch._get_model_interface() is orch._get_model_interface()
    assert isinstance(orch._ensure_executor(), FakeExecutor)
    assert isinstance(orch._get_router_agent(), FakeRouterAgent)
    assert orch._get_notetaker_agent() is fake_default_notetaker
    assert fake_default_notetaker.model_interface is orch._get_model_interface()
    assert isinstance(orch._get_planner_agent(), FakePlanner)

    orch_state["memory_context"] = '{"_router_keywords": ["alpha", "", 3]}'
    assert orch._seed_keywords(orch_state, "fallback") == ["alpha", "3"]
    orch_state["memory_context"] = "{bad-json"
    assert orch._seed_keywords(orch_state, "fallback") == ["fallback"]

    planner = orch.planner_node(orch_state)
    assert "planner_llm_failed" in planner["error_log"][0]
    assert planner["task_plan"].startswith("1.")

    direct = orch.executor_node({**orch_state, "router_decision": "direct_answer", "action_results": ""})
    assert direct["executor_result"].endswith("无相关记忆。")
    with_actions = orch.executor_node({**orch_state, "router_decision": "direct_answer", "memory_context": "记忆", "action_results": "工具"})
    assert "【外部工具结果】" in with_actions["executor_result"]
    assert orch.route_after_router({"router_decision": "search_memory"}) == "notetaker"
    assert orch.route_after_router({"router_decision": "direct_answer"}) == "executor"


def test_langgraph_notetaker_fallback_and_action_error_branches(monkeypatch: pytest.MonkeyPatch, orch_state: dict[str, Any]) -> None:
    class FallbackNotetaker:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def chat_with_tools(self, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("llm failed")

        def execute_tool(self, name: str, args: dict[str, Any]) -> list[dict[str, str]]:
            self.calls.append((name, args))
            if name == "mase2_search_memory":
                return [{"content": "Alpha memory"}]
            return [{"category": "project", "key": "code", "value": "Alpha"}]

    fake = FallbackNotetaker()
    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)
    monkeypatch.setattr(orch, "_get_notetaker_agent", lambda: fake)
    orch_state["memory_context"] = '{"_router_keywords": ["Alpha"]}'
    out = orch.notetaker_node(orch_state)
    assert "Alpha memory" in out["memory_context"]
    assert "project.code: Alpha" in out["memory_context"]
    assert "notetaker_llm_failed" in out["error_log"][0]

    class BrokenFallback(FallbackNotetaker):
        def execute_tool(self, name: str, args: dict[str, Any]) -> list[dict[str, str]]:
            raise RuntimeError("db down")

    monkeypatch.setattr(orch, "_get_notetaker_agent", lambda: BrokenFallback())
    out = orch.notetaker_node({**orch_state, "memory_context": ""})
    assert out["memory_context"] == "无相关记忆。"
    assert any("notetaker_fallback_failed" in item for item in out["error_log"])

    monkeypatch.setenv("MASE_ORCHESTRATOR_FAST", "yes")
    fast_time = orch.action_node({**orch_state, "user_query": "现在几点"})
    assert "get_current_time" in fast_time["action_results"]

    fake_module = ModuleType("mase_tools.mcp.tools")
    fake_module.TOOL_REGISTRY = {
        "ok": lambda value="": f"ok:{value}",
        "bad_args": lambda required: required,
        "boom": lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    }
    monkeypatch.setitem(sys.modules, "mase_tools.mcp.tools", fake_module)

    class FakeMI:
        def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "missing", "arguments": "{}"}},
                        {"function": {"name": "ok", "arguments": '{"value": "A"}'}},
                        {"function": {"name": "bad_args", "arguments": "{}"}},
                        {"function": {"name": "boom", "arguments": {}}},
                        {"function": {"name": "ok", "arguments": "{bad-json"}},
                    ]
                }
            }

    monkeypatch.delenv("MASE_ORCHESTRATOR_FAST", raising=False)
    monkeypatch.setattr(orch, "_get_model_interface", lambda: FakeMI())
    action = orch.action_node(orch_state)
    assert "unknown tool 'missing'" in action["action_results"]
    assert "ok:{'value': 'A'}" not in action["action_results"]
    assert "ok:A" in action["action_results"]
    assert "bad args for bad_args" in action["action_results"]
    assert "boom" in action["action_results"]

    class BrokenMI:
        def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("model down")

    monkeypatch.setattr(orch, "_get_model_interface", lambda: BrokenMI())
    failed = orch.action_node(orch_state)
    assert failed["action_results"] == ""
    assert "action_llm_failed" in failed["error_log"][0]


def test_multipass_generation_and_reranker_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MASE_MULTIPASS", raising=False)
    assert mp.is_enabled() is False
    monkeypatch.setenv("MASE_MULTIPASS", "on")
    assert mp.is_enabled() is True
    assert mp._int_env("MISSING_INT_ENV", 7) == 7
    monkeypatch.setenv("MISSING_INT_ENV", "bad")
    assert mp._int_env("MISSING_INT_ENV", 7) == 7
    monkeypatch.setenv("BOOL_ENV", "off")
    assert mp._bool_env("BOOL_ENV", True) is False
    monkeypatch.delenv("BOOL_ENV", raising=False)
    assert mp._bool_env("BOOL_ENV", True) is True

    mp._generate_query_variants_cached.cache_clear()
    mp._generate_hyde_keywords_cached.cache_clear()

    class FakeMI:
        def chat(self, **kwargs: Any) -> dict[str, str]:
            prompt = kwargs["messages"][0]["content"]
            if "生成 2 个不同表述" in prompt:
                return {"content": "1. same question\n- variant one\n2) variant two\nvariant three"}
            return {"content": "alpha alpha beta-term 中文词 Gamma"}

    monkeypatch.setattr("mase.model_interface.ModelInterface", FakeMI)
    assert mp._generate_query_variants_cached("same question", 2) == ("variant one", "variant two")
    assert mp._generate_query_variants_cached("", 2) == ()
    assert mp._generate_query_variants_cached("q", 0) == ()
    assert mp._generate_hyde_keywords_cached("q")[:4] == ("alpha", "beta-term", "中文词", "Gamma")
    assert mp._generate_hyde_keywords_cached("") == ()

    class FakeReranker:
        def predict(self, pairs: list[tuple[str, str]], show_progress_bar: bool = False) -> list[float]:
            assert show_progress_bar is False
            assert pairs[0][0] == "question"
            return [0.1, 0.9]

    monkeypatch.setattr(mp, "_RERANKER", FakeReranker())
    monkeypatch.setattr(mp, "_RERANKER_LOAD_FAILED", False)
    reranked = mp._rerank_cross_encoder(
        "question",
        [{"id": 1, "summary": "s1", "content": "c1"}, {"id": 2, "summary": "s2", "content": "c2"}],
        2,
    )
    assert reranked and [row["id"] for row in reranked] == [2, 1]
    assert reranked[0]["rerank_score"] == 0.9

    class BrokenReranker:
        def predict(self, *args: Any, **kwargs: Any) -> list[float]:
            raise RuntimeError("nope")

    monkeypatch.setattr(mp, "_RERANKER", BrokenReranker())
    assert mp._rerank_cross_encoder("q", [{"id": 1}], 1) is None
    monkeypatch.setattr(mp, "_RERANKER", None)
    monkeypatch.setattr(mp, "_RERANKER_LOAD_FAILED", True)
    assert mp._load_reranker() is None


def test_memory_diff_git_and_snapshot_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser()
    memory_diff.add_memory_diff_args(parser)
    parsed = parser.parse_args(["--from", "a", "--to", "b", "--vault", str(tmp_path)])
    assert parsed.from_ref == "a"
    assert parsed.to_ref == "b"
    assert parsed.vault == str(tmp_path)

    monkeypatch.delenv("MASE_MEMORY_VAULT", raising=False)
    monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))
    assert memory_diff._resolve_vault(None) == (tmp_path / "runs" / "memory").resolve()

    vault = tmp_path / "vault"
    (vault / "context").mkdir(parents=True)
    (vault / "context" / "same.json").write_text('{"same": true}\n', encoding="utf-8")
    assert memory_diff._list_snapshots(vault) == []
    assert memory_diff._resolve_snapshot(vault, None, default_to_working=True) == vault
    assert memory_diff._resolve_snapshot(vault, None, default_to_working=False) == vault
    with pytest.raises(SystemExit):
        memory_diff._resolve_snapshot(vault, "missing", default_to_working=False)
    assert memory_diff._read_lines(tmp_path / "missing.json") == []

    repo = tmp_path / "repo"
    vault_git = repo / "memory"
    vault_git.mkdir(parents=True)

    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append((path, args))
        if args[0] == "log":
            return subprocess.CompletedProcess(["git"], 0, stdout="new\nold\n", stderr="")
        if args[:2] == ("diff", "--numstat"):
            return subprocess.CompletedProcess(["git"], 0, stdout="2\t1\tmemory/context/a.json\n-\t-\tmemory/sessions/bin\n", stderr="")
        return subprocess.CompletedProcess(["git"], 1, stdout="diff body\n", stderr="")

    monkeypatch.setattr(memory_diff, "_git", fake_git)
    assert memory_diff._resolve_git_refs(repo, vault_git, None, None) == ("old", None)
    assert memory_diff._resolve_git_refs(repo, vault_git, "base", "head") == ("base", "head")
    assert memory_diff._diff_git(repo, vault_git, "base", "head") == 0
    out = capsys.readouterr().out
    assert "# tri-vault diff (git): base -> head" in out
    assert "context: +2 -1" in out
    assert "diff body" in out

    def fake_is_git(path: Path) -> tuple[bool, Path | None]:
        return True, repo

    monkeypatch.setattr(memory_diff, "_is_git_dir", fake_is_git)
    assert memory_diff.run_memory_diff(argparse.Namespace(from_ref="base", to_ref=None, vault=str(vault_git))) == 0
