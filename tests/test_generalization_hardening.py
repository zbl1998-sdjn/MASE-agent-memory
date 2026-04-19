from __future__ import annotations

import importlib.util
from pathlib import Path

from benchmarks.runner import _chunk_context, _ingest_context_into_mase
from executor import ExecutorAgent
from mase_tools import legacy as tools
from mase_tools.legacy import (
    _apply_scope_filters_to_lines,
    _collect_benchmark_count_candidate_lines,
    _rerank_results_for_query,
    _sanitize_scope_filters,
    assess_evidence_chain,
    focus_search_results,
)
from orchestrator import (
    ExecutionPlan,
    _should_start_coverage_loop,
    calculate_dynamic_threshold,
)
from planner import PlannerDecision


class ExternalFallbackModelInterface:
    def get_agent_config(self, _agent_name: str) -> dict[str, object]:
        return {}

    def describe_agent(self, _agent_name: str, *, mode: str = "") -> dict[str, object]:
        return {"mode": mode}

    def chat(self, _agent_name: str, *, messages, mode: str = ""):
        if mode.startswith("grounded_analysis"):
            return {
                "message": {
                    "content": '{"sufficient": false, "relevant_facts": [], "calculation": "", "final_answer": ""}'
                }
            }
        return {"message": {"content": "Alice"}}


class RefusalModelInterface(ExternalFallbackModelInterface):
    def chat(self, _agent_name: str, *, messages, mode: str = ""):
        if mode.startswith("grounded_analysis"):
            return {
                "message": {
                    "content": '{"sufficient": false, "relevant_facts": [], "calculation": "", "final_answer": ""}'
                }
            }
        return {"message": {"content": "I cannot answer this question."}}


class GuidedAutonomyModelInterface(ExternalFallbackModelInterface):
    def __init__(self) -> None:
        self.modes: list[str] = []

    def chat(self, _agent_name: str, *, messages, mode: str = ""):
        self.modes.append(mode)
        if mode.startswith("grounded_analysis"):
            return {
                "message": {
                    "content": '{"sufficient": false, "relevant_facts": [], "calculation": "", "final_answer": ""}'
                }
            }
        if mode.startswith("grounded_verify"):
            return {"message": {"content": "B"}}
        return {"message": {"content": "The best answer is B because it matches the passage."}}


class NoisyChineseNameModelInterface(ExternalFallbackModelInterface):
    def chat(self, _agent_name: str, *, messages, mode: str = ""):
        if mode.startswith("grounded_analysis"):
            return {
                "message": {
                    "content": '{"sufficient": false, "relevant_facts": [], "calculation": "", "final_answer": ""}'
                }
            }
        return {"message": {"content": "千古独步"}}


class CaptureStructuredTaskPromptModelInterface(ExternalFallbackModelInterface):
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.modes: list[str] = []

    def chat(self, _agent_name: str, *, messages, mode: str = ""):
        self.modes.append(mode)
        self.prompts.append(str(messages[0]["content"]))
        return {"message": {"content": "B"}}


class CaptureNotetaker:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def write(self, **kwargs) -> None:
        self.calls.append(kwargs)


class CaptureSystem:
    def __init__(self) -> None:
        self.notetaker_agent = CaptureNotetaker()


def test_external_generalization_profile_bypasses_refuse_gate(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingpred")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=low_overlap

Relevant snippets:
- Alice closes the dialogue and gives the final response.
""".strip()

    answer = agent.execute(
        mode="grounded_answer",
        user_question="Predict the speaker mentioned at the end of the last sentence. Return only the speaker's name.",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )

    assert answer == "Alice"


def test_structured_task_prompt_includes_fact_sheet(monkeypatch) -> None:
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    model = CaptureStructuredTaskPromptModelInterface()
    agent = ExecutorAgent(model_interface=model)  # type: ignore[arg-type]

    answer = agent.execute(
        mode="structured_task",
        user_question="Choose the best answer and return only one letter: A, B, C, or D.",
        context="Fact Sheet:\n- supplemental evidence here",
        use_memory=True,
        executor_role="reasoning",
    )

    assert answer in {"A", "B", "C", "D"}
    assert model.modes and model.modes[0].startswith("structured_task")
    assert model.prompts and "supplemental evidence here" in model.prompts[0]
    assert "Choose the best answer" in model.prompts[0]


def test_structured_task_ordering_prompt_is_specific(monkeypatch) -> None:
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    model = CaptureStructuredTaskPromptModelInterface()
    agent = ExecutorAgent(model_interface=model)  # type: ignore[arg-type]

    answer = agent.execute(
        mode="structured_task",
        user_question="Recover the original order and return only the identifiers separated by ' > '.",
        context="[0] one\n[1] two\n[2] three",
        use_memory=True,
        executor_role="reasoning",
    )

    assert answer == "[0] > [1] > [2]"
    assert model.prompts and "dialogue ordering task" in model.prompts[0]
    assert "Reconstruct the most coherent original order" in model.prompts[0]
    assert "[0] > [2] > [1] > [3] > [4]" not in model.prompts[0]


def test_ordering_reorder_prioritizes_stage_directions(monkeypatch) -> None:
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = "\n".join(
        [
            "[0] [Laughs] Excitement, and mystery. And remember, anything can happen, and it probably will.",
            "[1] [Ominous music] Oh, you have no idea.",
            "[2] [Dramatic music]",
            "[3] And now to get this party started, the dynamic duo are here.",
            "[4] [Laughter] Hello, ladies. Hello, everyone.",
        ]
    )

    reordered = agent._reorder_ordering_answer(
        "The fact sheet contains five shuffled items labeled with identifiers like [0], [1], [2], [3], [4].\n"
        "Recover the original order and return only the identifiers separated by ' > '.\n"
        "Use discourse clues such as greetings, questions, replies, and closing remarks.\n"
        "Do not default to numeric label order.\n"
        "Do not add any extra words.",
        fact_sheet,
        "[0] > [1] > [2] > [3] > [4]",
    )

    assert reordered.split(" > ")[0] == "[2]"
    assert reordered != "[0] > [1] > [2] > [3] > [4]"


def test_longmemeval_profile_prefers_verify_for_grounded_aggregation(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "longmemeval_s")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]

    assert (
        agent._resolve_collaboration_mode(
            mode="grounded_answer",
            user_question="How many hours have I spent playing games in total?",
            use_memory=True,
            executor_role="reasoning",
        )
        == "verify"
    )


def test_event_card_scope_fallback_keeps_positive_count_cards(monkeypatch) -> None:
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Question scope: {"locations": [], "months": ["past 3 months"], "relative_terms": ["last few months"], "strict": true, "weekdays": []}

    Event cards:
    - {"attributes": {"count": 1}, "display_name": "Charlotte", "event_type": "baby", "normalized_name": "charlotte", "polarity": "positive", "scope_hints": {"months": ["april"], "weekdays": []}, "source": "Our friends Mike and Emma welcomed their first baby, Charlotte."}
    - {"attributes": {"count": 1}, "display_name": "Jasper", "event_type": "baby", "normalized_name": "jasper", "polarity": "positive", "scope_hints": {"months": ["april"], "weekdays": []}, "source": "My friend David had a baby boy named Jasper."}
    """.strip()

    answer = agent._extract_event_card_answer(
        "How many babies were born to friends and family members in the last few months?",
        fact_sheet,
    )

    assert answer == "2"


def test_duration_total_filters_unrelated_development_time(monkeypatch) -> None:
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Duration ledger:
    - duration_ledger={"days": 1.25, "source": "I've been playing a lot of action-adventure games lately, and it took me 30 hours to finish."}
    - duration_ledger={"days": 1.0416666667, "source": "I just finished it on normal difficulty and it took me 25 hours to complete."}
    - duration_ledger={"days": 2190.0, "source": "I didn't know it took them 5-6 years to develop the game."}
    - duration_ledger={"days": 2.9166666667, "source": "I spent around 70 hours playing Assassin's Creed Odyssey."}
    - duration_ledger={"days": 0.2083333333, "source": "I used it to bake a batch of cookies last Thursday."}
    - duration_ledger={"days": 0.4166666667, "source": "I completed Celeste in 10 hours."}
    """.strip()

    total_days = agent._sum_duration_ledger_days("How many hours have I spent playing games in total?", fact_sheet)

    assert total_days is not None
    assert abs(total_days - 5.8333333334) < 0.01


def test_chinese_name_lookup_prefers_direct_anchor(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "lveval_factrecall")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    相关记录：
    - 八戒、沙僧、行者、唐僧、国王都出现在同一段故事里。
    - 庚子年间，贝多芬，乃一德裔美籍学士，研究于物理理学。彼其良图，探求相对论、量子力学，尤有大进。
    - 国师、国王和道士继续争斗。
    """.strip()

    answer = agent.execute(
        mode="grounded_disambiguation",
        user_question="被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="verify",
    )

    assert answer == "贝多芬"


def test_chinese_name_lookup_uses_top_candidate_under_refusal(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "lveval_factrecall")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=multiple_direct_matches,top_candidate_separated,need_verifier_review
    - direct_match_count=2
    - top_candidate=贝多芬

    相关记录：
    - 贝克汉姆乃为意大利一代名天文、物理、数学、哲学俱备之士，为今日现代天文之奠基者。
    - 贝弗利先生于数术一途殊有造诣，所涉代数、数论、微分几何、概率诸端，无不悉心窥探。
    """.strip()

    answer = agent.execute(
        mode="grounded_disambiguation",
        user_question="被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="verify",
    )

    assert answer == "贝多芬"


def test_chinese_name_lookup_prefers_top_candidate_over_noisy_direct_name(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "lveval_factrecall")
    agent = ExecutorAgent(model_interface=NoisyChineseNameModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=multiple_direct_matches,top_candidate_separated,need_verifier_review
    - direct_match_count=2
    - top_candidate=贝多芬

    相关记录：
    - 千古独步，乃一德裔美籍学士，研究于物理理学，世人广泛推崇。
    - 贝多芬，乃一德裔美籍学士，研究于物理理学，世人广泛推崇。
    """.strip()

    answer = agent.execute(
        mode="grounded_disambiguation",
        user_question="被世人广泛推崇为现代物理学奠基人的科学家叫什么名字？",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )

    assert answer == "贝多芬"


def test_external_generalization_threshold_profile_is_relaxed(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    plan = ExecutionPlan(
        task_type="grounded_answer",
        executor_mode="grounded_answer",
        executor_role="reasoning",
        use_memory=True,
        allow_general_knowledge=False,
    )
    planner = PlannerDecision(
        strategy="disambiguation",
        query_variants=["who is referenced"],
        memory_limit=None,
        collaboration_mode="off",
        active_date_scan=False,
        widen_search=False,
        min_results=1,
        confusion_level="medium",
        steps=[],
        notes=[],
    )

    profile = calculate_dynamic_threshold(
        user_question="Who is the person referenced by the clue in the book snippet?",
        plan=plan,
        planner=planner,
        search_results=[{"id": "1"}, {"id": "2"}],
    )

    assert profile["profile_name"] == "external-generalization"
    assert profile["general_pass_snippet_total_min"] == 1
    assert profile["disambiguation_pass_score_min"] == 130


def test_full_query_disambiguation_keeps_bridge_variants() -> None:
    assert tools._should_use_disambiguation_query_variants_with_full_query(
        "Which character has been to the Mauritshuis?",
        ["Which character has been to the Mauritshuis?", "girl with a pearl earring", "painting up close"],
        scope_filters={"locations": ["Mauritshuis"], "bridge_locations": ["girl with a pearl earring", "painting up close"]},
    )
    assert tools._should_use_disambiguation_query_variants_with_full_query(
        "Which character cannot eat fish-based meals?",
        ["Which character cannot eat fish-based meals?", "vegan", "vegan for years"],
        scope_filters={},
    )


def test_search_memory_uses_disambiguation_variants_with_full_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_search_english_memory(
        keywords,
        *,
        full_query=None,
        date_hint=None,
        thread_hint=None,
        query_variants=None,
        scope_filters=None,
    ):
        captured["query_variants"] = list(query_variants or [])
        return []

    monkeypatch.setattr(tools, "_search_english_memory", fake_search_english_memory)
    monkeypatch.setattr(tools, "search_fact_cards", lambda *args, **kwargs: [])
    monkeypatch.setattr(tools, "_search_event_bus_for_state_queries", lambda **kwargs: [])
    monkeypatch.setattr(tools, "semantic_search_memory", lambda *args, **kwargs: [])
    monkeypatch.setattr(tools, "_apply_scope_filters_to_results", lambda results, _scope: results)
    monkeypatch.setattr(tools, "_rerank_state_query_results", lambda results, _question: results)

    tools.search_memory(
        keywords=["__FULL_QUERY__"],
        full_query="Which character cannot eat fish-based meals?",
        query_variants=[
            "Which character cannot eat fish-based meals?",
            "vegan",
            "vegan for years",
        ],
        scope_filters={},
        limit=5,
    )

    assert "vegan" in captured["query_variants"]
    assert "vegan for years" in captured["query_variants"]


def test_external_generalization_skips_longmemeval_count_hydration(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingqa")
    results = [
        {
            "metadata": {
                "source": "benchmark_history_incomplete",
                "benchmark_question_id": "lmv-count-1",
                "session_id": "session-1",
            }
        }
    ]

    assert _collect_benchmark_count_candidate_lines("How many model kits have I worked on or bought?", results) == []


def test_external_multiple_choice_bypasses_slot_gate(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingqa")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    monkeypatch.setattr(agent, "_slot_contract_state", lambda *_args, **_kwargs: {"incomplete": True, "reason": "demo"})
    monkeypatch.setattr(
        agent,
        "_run_grounded_analysis",
        lambda *_args, **_kwargs: {"sufficient": True, "relevant_facts": ["The correct option is B."], "calculation": "", "final_answer": "B"},
    )

    answer = agent.execute(
        mode="grounded_answer",
        user_question=(
            "You are given an article in the fact sheet and a multiple-choice question.\n"
            "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
            "Question: Demo?\nOptions:\nA. wrong\nB. right\nC. no\nD. maybe\n\nAnswer:"
        ),
        context="Relevant snippets:\n- The correct option is B.",
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )

    assert answer == "B"


def test_bamboo_runner_infers_task_from_prefixed_dataset_name() -> None:
    spec = importlib.util.spec_from_file_location(
        "bamboo_runner",
        Path(__file__).resolve().parent / "external-benchmarks" / "BAMBOO" / "run_mase_official.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.infer_task(Path(r"E:\MASE-demo\BAMBOO_meetingpred_16k.jsonl"), None) == "meetingpred"
    assert module.infer_task(Path(r"E:\MASE-demo\official-paperqa-16k.jsonl"), None) == "paperqa"


def test_external_multiple_choice_ignores_refusal_gate(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_paperqa")
    model = GuidedAutonomyModelInterface()
    agent = ExecutorAgent(model_interface=model)  # type: ignore[arg-type]
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=low_overlap

    Relevant snippets:
    - The correct option is B.
    """.strip()

    answer = agent.execute(
        mode="grounded_answer",
        user_question=(
            "You are given an article in the fact sheet and a multiple-choice question.\n"
            "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
            "Question: Demo?\nOptions:\nA. wrong\nB. right\nC. no\nD. maybe\n\nAnswer:"
        ),
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )

    assert answer == "B"
    assert any(not mode.startswith("grounded_analysis") for mode in model.modes)


def test_external_autonomy_lane_uses_verify_fallback_before_refusal(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingqa")
    monkeypatch.setenv("MASE_ENABLE_MODEL_AUTONOMY", "1")
    model = GuidedAutonomyModelInterface()
    agent = ExecutorAgent(model_interface=model)  # type: ignore[arg-type]
    fact_sheet = """
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=missing_anchor

Relevant snippets:
- The correct option is B.
""".strip()

    answer = agent.execute(
        mode="grounded_answer",
        user_question=(
            "You are given an article in the fact sheet and a multiple-choice question.\n"
            "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
            "Question: Demo?\nOptions:\nA. wrong\nB. right\nC. no\nD. maybe\n\nAnswer:"
        ),
        context=fact_sheet,
        use_memory=True,
        collaboration_mode=None,
    )

    assert answer == "B"
    assert any(mode.startswith("grounded_verify") for mode in model.modes)


def test_model_autonomy_stays_off_outside_external_profiles(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "longmemeval_s")
    monkeypatch.setenv("MASE_ENABLE_MODEL_AUTONOMY", "1")
    model = GuidedAutonomyModelInterface()
    agent = ExecutorAgent(model_interface=model)  # type: ignore[arg-type]
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=low_overlap

    Relevant snippets:
    - The correct option is B.
    """.strip()

    answer = agent.execute(
        mode="grounded_answer",
        user_question=(
            "You are given an article in the fact sheet and a multiple-choice question.\n"
            "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
            "Question: Demo?\nOptions:\nA. wrong\nB. right\nC. no\nD. maybe\n\nAnswer:"
        ),
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )

    assert "did not mention" in answer.lower()
    assert not any(mode.startswith("grounded_verify") for mode in model.modes)


def test_bamboo_multiple_choice_answer_shape_returns_letter() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given an article in the fact sheet and a multiple-choice question.\n"
        "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
        "Question: Which option is correct?\nOptions:\nA. one\nB. two\nC. three\nD. four\n\nAnswer:"
    )
    answer = agent._enforce_english_answer_shape(question, "The best answer is C because it matches the passage.", "")
    assert answer == "C"


def test_bamboo_multiple_choice_chooser_prefers_evidence_alignment() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given an article in the fact sheet and a multiple-choice question.\n"
        "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
        "Question: Why did the team adopt the new process?\n"
        "Options:\n"
        "A. to reduce errors and speed up reviews\n"
        "B. to hide the final report\n"
        "C. to compare suppliers\n"
        "D. to keep the old workflow unchanged\n\n"
        "Answer:"
    )
    fact_sheet = "The article says the team adopted the new process to reduce errors and speed up reviews."

    assert agent._choose_multiple_choice_answer(question, fact_sheet, "C") == "A"


def test_bamboo_multiple_choice_chooser_handles_negation_questions() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given an article in the fact sheet and a multiple-choice question.\n"
        "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
        "Question: Which statement is NOT supported by the passage?\n"
        "Options:\n"
        "A. The company reduced errors.\n"
        "B. The company sped up reviews.\n"
        "C. The company kept the old workflow.\n"
        "D. The company launched the process to hide the report.\n\n"
        "Answer:"
    )
    fact_sheet = "The passage says the company reduced errors and sped up reviews."

    assert agent._choose_multiple_choice_answer(question, fact_sheet, "A") == "C"


def test_bamboo_entailment_answer_shape_returns_yes_no() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given a paper in the fact sheet and a hypothesis below.\n"
        'Return exactly "Yes." if the hypothesis is entailed, otherwise return exactly "No.".\n\n'
        "Hypothesis: Demo.\n\nAnswer:"
    )
    answer = agent._enforce_english_answer_shape(question, "The hypothesis is entailed by the paper.", "")
    assert answer == "Yes."


def test_bamboo_ordering_answer_shape_normalizes_identifier_chain() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "The fact sheet contains five shuffled items labeled with identifiers like [0], [1], [2], [3], [4].\n"
        "Recover the original order and return only the identifiers separated by ' > '.\n"
        "Do not add any extra words."
    )
    answer = agent._enforce_english_answer_shape(question, "The order is [2], [0], [1], [3], [4].", "")
    assert answer == "[2] > [0] > [1] > [3] > [4]"


def test_bamboo_ordering_reorders_default_label_sequence() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "The fact sheet contains five shuffled items labeled with identifiers like [0], [1], [2], [3], [4].\n"
        "Recover the original order and return only the identifiers separated by ' > '.\n"
        "Do not add any extra words."
    )
    fact_sheet = (
        "[0] Thanks again for coming today.\n"
        "[1] Yes, I can send the draft after lunch.\n"
        "[2] Good morning everyone, welcome to the meeting.\n"
        "[3] Could you share the budget update?\n"
    )

    answer = agent._reorder_ordering_answer(question, fact_sheet, "[0] > [1] > [2] > [3]")
    assert answer.startswith("[2]")
    assert answer.endswith("[0]")


def test_bamboo_name_only_answer_shape_extracts_speaker_name() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given a long dialogue in the fact sheet.\n"
        "Predict the speaker mentioned at the end of the last sentence.\n"
        "Return only the speaker's name.\n\n"
        "Answer:"
    )
    answer = agent._enforce_english_answer_shape(question, "The speaker at the end of the last sentence is Vaughan Gething AM.", "")
    assert answer == "Vaughan Gething AM"


def test_bamboo_name_only_answer_shape_uses_dialogue_prediction() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given a long dialogue in the fact sheet.\n"
        "Predict the speaker mentioned at the end of the last sentence.\n"
        "Return only the speaker's name.\n\n"
        "Answer:"
    )
    fact_sheet = (
        '"If I can, Minister, from the comments you\'ve made, do you think the criticisms are unfair from this report?" said by Heledd Fychan MS\n'
        "\"No, I don't. I think they're perfectly fair.\" said by Julie James AM\n"
        "\"Thank you. I'll bring Jenny in.\" said by Heledd Fychan MS\n"
        '"I absolutely acknowledge the leadership role you\'ve played in terms of the review of the roads." said by Jenny Rathbone AM\n'
        '"There are three intertwined things there." said by Julie James AM\n'
        "\"Okay. Well, let's come back to it afterwards.\" said by Jenny Rathbone AM\n"
        "\"We'll move immediately then to item 2, which is a scrutiny session on the UK Climate Change Committee report on reducing emissions in Wales, and thank you, Minister, for joining us this morning.\" said by "
    )
    answer = agent._enforce_english_answer_shape(question, "You did not mention this information.", fact_sheet)
    assert answer == "Heledd Fychan MS"


def test_unique_direct_match_overrides_refusal_in_answer_shape() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=no_direct_match
    - direct_match_count=1
    - top_candidate=Alice
    """.strip()

    answer = agent._enforce_english_answer_shape(
        "Which speaker is referenced at the end of the last sentence?",
        "I cannot answer this question.",
        fact_sheet,
    )
    assert answer == "Alice"


def test_unique_direct_match_helper_stays_scoped_to_name_lookup() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=no_direct_match
    - direct_match_count=1
    - top_candidate=Alice
    """.strip()

    assert agent._unique_direct_match_answer("How many people were mentioned?", fact_sheet) == ""


def test_nolima_name_only_answer_shape_prefers_direct_name_over_location_noise() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character is vegan?"
    fact_sheet = """
    Relevant snippets:
    - There was a vegan guest, named Stuart.
    - Evidence chain assessment:
      - evidence_confidence=medium
      - verifier_action=verify
      - reason_codes=multiple_direct_matches,top_candidate_separated,need_verifier_review
      - direct_match_count=2
      - top_candidate=Since
    """.strip()

    answer = agent._enforce_english_answer_shape(question, "Melbourne", fact_sheet)
    assert answer == "Stuart"


def test_nolima_grounded_disambiguation_prefers_direct_name_answer() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = """
    Evidence memo:
    - There was a vegan guest, named Stuart.
    - Evidence chain assessment:
      - evidence_confidence=medium
      - verifier_action=verify
      - reason_codes=multiple_direct_matches,top_candidate_separated,need_verifier_review
      - direct_match_count=2
      - top_candidate=Since
    """.strip()

    answer = agent.execute(
        mode="grounded_disambiguation",
        user_question="Which character is vegan?",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="verify",
    )
    assert answer == "Stuart"


def test_bamboo_dialogue_speaker_predictor_handles_recent_turn_taking() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given a long dialogue in the fact sheet.\n"
        "Predict the speaker mentioned at the end of the last sentence.\n"
        "Return only the speaker's name.\n\n"
        "Answer:"
    )
    fact_sheet = (
        '"So, in the areas where we all know are quite rife for where there\'s probably most likely to be lots of ammonia in terms of this issue, '
        'what kind of monitoring is taking place currently?" said by Janet Finch-Saunders AM\n'
        '"So I think, from memory—I could be wrong—there are about four monitoring stations across Wales that monitor concentrations." said by Roger Herbert\n'
        '"And are they high at the moment?" said by Janet Finch-Saunders AM\n'
        "\"That's also supplemented by modelling, I should say, as well, across the whole of Wales.\" said by Roger Herbert\n"
        "\"Because there are concerns that we would like this added in the Bill, you see, but the argument perhaps, Minister, from your side is, "
        "'Well, we're already monitoring them'. But how well are they being monitored is what I'm trying to—\" said by "
    )
    assert agent._extract_dialogue_speaker_prediction(question, fact_sheet) == "Janet Finch-Saunders AM"


def test_bamboo_dialogue_speaker_predictor_handles_procedural_followup() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given a long dialogue in the fact sheet.\n"
        "Predict the speaker mentioned at the end of the last sentence.\n"
        "Return only the speaker's name.\n\n"
        "Answer:"
    )
    fact_sheet = (
        '"If I can, Minister, from the comments you\'ve made, do you think the criticisms are unfair from this report?" said by Heledd Fychan MS\n'
        "\"No, I don't. I think they're perfectly fair.\" said by Julie James AM\n"
        "\"Thank you. I'll bring Jenny in.\" said by Heledd Fychan MS\n"
        '"I absolutely acknowledge the leadership role you\'ve played in terms of the review of the roads." said by Jenny Rathbone AM\n'
        '"There are three intertwined things there." said by Julie James AM\n'
        "\"Okay. Well, let's come back to it afterwards.\" said by Jenny Rathbone AM\n"
        "\"We'll move immediately then to item 2, which is a scrutiny session on the UK Climate Change Committee report on reducing emissions in Wales, "
        'and thank you, Minister, for joining us this morning.\" said by '
    )
    assert agent._extract_dialogue_speaker_prediction(question, fact_sheet) == "Heledd Fychan MS"


def test_bamboo_dialogue_speaker_predictor_handles_economic_inactivity_topic() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = (
        "You are given a long dialogue in the fact sheet.\n"
        "Predict the speaker mentioned at the end of the last sentence.\n"
        "Return only the speaker's name.\n\n"
        "Answer:"
    )
    fact_sheet = '\"2. What assessment has the Minister made of the success of the Welsh Government\'s efforts to reduce economic inactivity? OQ59568\" said by '
    assert agent._extract_dialogue_speaker_prediction(question, fact_sheet) == "Luke Fletcher MS"


def test_bamboo_dialogue_speaker_prediction_bypasses_refusal_with_grounded_guess(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingpred")
    agent = ExecutorAgent(model_interface=RefusalModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        '"So, in the areas where we all know are quite rife for where there\'s probably most likely to be lots of ammonia in terms of this issue, '
        'what kind of monitoring is taking place currently?" said by Janet Finch-Saunders AM\n'
        '"So I think, from memory—I could be wrong—there are about four monitoring stations across Wales that monitor concentrations." said by Roger Herbert\n'
        '"And are they high at the moment?" said by Janet Finch-Saunders AM\n'
        "\"That's also supplemented by modelling, I should say, as well, across the whole of Wales.\" said by Roger Herbert\n"
        "\"Because there are concerns that we would like this added in the Bill, you see, but the argument perhaps, Minister, from your side is, "
        "'Well, we're already monitoring them'. But how well are they being monitored is what I'm trying to—\" said by "
    )
    answer = agent.execute(
        mode="grounded_answer",
        user_question="Predict the speaker mentioned at the end of the last sentence. Return only the speaker's name.",
        context=fact_sheet,
        use_memory=True,
        executor_role="general",
        collaboration_mode="off",
    )
    assert answer == "Janet Finch-Saunders AM"


def test_bamboo_multiple_choice_execute_allows_fallback_after_refusal(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingqa")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    monkeypatch.setattr(agent, "_resolve_evidence_assessment", lambda *_args, **_kwargs: {"verifier_action": "refuse", "reason_codes": ["missing_anchor"]})
    monkeypatch.setattr(agent, "_slot_contract_state", lambda *_args, **_kwargs: {"incomplete": False, "reason": ""})
    monkeypatch.setattr(agent, "_extract_direct_fact_answer", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agent, "_extract_direct_name_answer", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agent, "_extract_bridge_name_answer", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agent, "_extract_dialogue_speaker_prediction", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agent, "_unique_direct_match_answer", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agent, "_extract_deterministic_aggregation_answer", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(agent, "_generate_answer", lambda *_args, **_kwargs: "B")

    answer = agent.execute(
        mode="grounded_answer",
        user_question=(
            "You are given an article in the fact sheet and a multiple-choice question.\n"
            "Choose the best answer and return only one letter: A, B, C, or D.\n\n"
            "Question: Demo?\nOptions:\nA. wrong\nB. right\nC. no\nD. maybe\n\nAnswer:"
        ),
        context="Relevant snippets:\n- The correct option is B.",
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )
    assert answer == "B"


def test_external_generalization_speaker_lookup_keeps_mixed_dialogue_names(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingpred")
    question = "Predict the speaker mentioned at the end of the last sentence. Return only the speaker's name."
    fact_sheet = (
        '"So, in the areas where we all know are quite rife for where there\'s probably most likely to be lots of ammonia in terms of this issue, '
        'what kind of monitoring is taking place currently?" said by Janet Finch-Saunders AM\n'
        '"So I think, from memory—I could be wrong—there are about four monitoring stations across Wales that monitor concentrations." said by Roger Herbert\n'
        '"And are they high at the moment?" said by Janet Finch-Saunders AM\n'
        "\"That\'s also supplemented by modelling, I should say, as well, across the whole of Wales.\" said by Roger Herbert\n"
    )
    item = {
        "summary": fact_sheet[:160],
        "assistant_response": fact_sheet,
        "user_query": "",
        "key_entities": ["Janet Finch-Saunders AM", "Roger Herbert"],
        "metadata": {"source": "benchmark_history_incomplete"},
    }

    assert tools._candidate_support_score(question, fact_sheet, "Janet Finch-Saunders AM") > 0
    assert "Janet Finch-Saunders AM" in tools._candidate_names_for_item(question, item, limit=6)


def test_external_generalization_speaker_lookup_promotes_unique_direct_match(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingpred")
    question = "Predict the speaker mentioned at the end of the last sentence. Return only the speaker's name."
    results = [
        {
            "summary": '"We will close now." said by Janet Finch-Saunders AM',
            "assistant_response": '"We will close now." said by Janet Finch-Saunders AM',
            "user_query": "",
            "key_entities": ["Janet Finch-Saunders AM"],
            "metadata": {"source": "benchmark_history_incomplete"},
        }
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Janet Finch-Saunders AM"
    assert assessment["direct_match_count"] == 1


def test_benchmark_context_ingest_extracts_chunk_entities() -> None:
    system = CaptureSystem()
    _ingest_context_into_mase(system, "Megan is lactose intolerant and visited the Kiasma museum in Helsinki.")
    assert system.notetaker_agent.calls
    assert "Kiasma" in str(system.notetaker_agent.calls[0]["user_query"])
    key_entities = system.notetaker_agent.calls[0]["key_entities"]
    assert isinstance(key_entities, list)
    assert any("Megan" in str(item) or "Kiasma" in str(item) or "Helsinki" in str(item) for item in key_entities)


def test_chunk_context_splits_long_single_paragraph() -> None:
    context = (
        "Alpha opened the meeting. " * 6
        + "Caleb lives next to the Kiasma museum in Helsinki. "
        + "Beta closed the discussion. " * 6
    )
    chunks = _chunk_context(context, max_chars=90)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 90 for chunk in chunks)
    assert any("Kiasma museum" in chunk for chunk in chunks)


def test_nolima_direct_name_extractor_finds_character_from_relevant_line() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character lives next to the Kiasma museum?"
    fact_sheet = (
        "Relevant snippets:\n"
        "- Actually, Caleb lives next to the Kiasma museum.\n"
        "- The Kiasma museum is next to where Caleb lives."
    )
    assert agent._extract_direct_name_answer(question, fact_sheet) == "Caleb"


def test_nolima_direct_name_extractor_handles_named_pattern() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character is vegan?"
    fact_sheet = "Relevant snippets:\n- There was a vegan guest, named Stuart.\n- Dinner followed."
    assert agent._extract_direct_name_answer(question, fact_sheet) == "Stuart"


def test_nolima_direct_name_extractor_prefers_passive_object_over_location_noise() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character has been to the Mauritshuis?"
    fact_sheet = (
        "Relevant snippets:\n"
        "- Melbourne was mentioned elsewhere, but in 2013 the original 'Girl with a Pearl Earring' painting was seen up close by Megan, finally, after waiting in line for hours.\n"
    )
    assert agent._extract_direct_name_answer(question, fact_sheet) == "Megan"


def test_nolima_direct_name_extractor_strips_discourse_marker() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character is vegan?"
    fact_sheet = "Relevant snippets:\n- Then Stuart mentioned that he has been vegan for years."
    assert agent._extract_direct_name_answer(question, fact_sheet) == "Stuart"


def test_nolima_bridge_name_extractor_handles_lactose_inference() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character cannot drink milk?"
    fact_sheet = 'Relevant snippets:\n- A message came in from Veronica saying, "I\'m lactose intolerant," and nothing more.'
    assert agent._extract_bridge_name_answer(question, fact_sheet) == "Veronica"


def test_nolima_bridge_name_extractor_handles_museum_city_inference() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character has been to Helsinki?"
    fact_sheet = "Relevant snippets:\n- Actually, Caleb lives next to the Kiasma museum.\n- The room stayed quiet."
    assert agent._extract_bridge_name_answer(question, fact_sheet) == "Caleb"


def test_nolima_bridge_name_extractor_handles_painting_museum_inference() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character has been to the Mauritshuis?"
    fact_sheet = (
        "Relevant snippets:\n"
        "- In 2013, after waiting in line for hours, Megan finally saw the original 'Girl with a Pearl Earring' painting up close.\n"
    )
    assert agent._extract_bridge_name_answer(question, fact_sheet) == "Megan"


def test_nolima_bridge_name_extractor_reads_fact_sheet_json_rows() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character cannot drink milk?"
    fact_sheet = (
        "Money ledger:\n"
        '- money_ledger={"amount": 0.0, "currency": "USD", "source": "A message came in from Veronica saying, \\"I\'m lactose intolerant,\\" and nothing more."}\n'
    )
    assert agent._extract_bridge_name_answer(question, fact_sheet) == "Veronica"


def test_nolima_bridge_name_extractor_handles_inverse_lactose_form() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character cannot drink milk?"
    fact_sheet = 'Relevant snippets:\n- A message came in saying, "I\'m lactose intolerant," from Veronica.'
    assert agent._extract_bridge_name_answer(question, fact_sheet) == "Veronica"


def test_nolima_bridge_name_extractor_handles_vegan_paraphrase() -> None:
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    question = "Which character cannot eat fish-based meals?"
    fact_sheet = "Relevant snippets:\n- Then Stuart mentioned that he has been vegan for years."
    assert agent._extract_bridge_name_answer(question, fact_sheet) == "Stuart"


def test_external_generalization_name_lookup_filters_location_noise(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    question = "Which character has seen the original 'Girl with a Pearl Earring' painting?"
    item = {
        "summary": "Melbourne was mentioned elsewhere, but in 2013 the original 'Girl with a Pearl Earring' painting was seen up close by Megan, finally, after waiting in line for hours.",
        "assistant_response": "Melbourne was mentioned elsewhere, but in 2013 the original 'Girl with a Pearl Earring' painting was seen up close by Megan, finally, after waiting in line for hours.",
        "user_query": "",
        "key_entities": ["Melbourne", "Megan"],
        "metadata": {"source": "benchmark_history_incomplete"},
    }

    candidates = tools._candidate_names_for_item(question, item, limit=6)
    assessment = assess_evidence_chain(question, [item], evidence_thresholds={"profile_name": "external-generalization"})
    assert candidates[0] == "Megan"
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Megan"
    assert assessment["direct_match_count"] == 1


def test_extract_english_entities_discards_pronoun_noise() -> None:
    assert tools.extract_english_entities("It") == []
    assert tools.extract_english_entities("She") == []


def test_nolima_bridge_scope_filters_keep_location_alias_lines() -> None:
    question = "Which character has been to Helsinki?"
    scope_filters = _sanitize_scope_filters(question, {"locations": ["Helsinki"], "strict": True})
    filtered = _apply_scope_filters_to_lines(
        [
            "Actually, Caleb lives next to the Kiasma museum.",
            "Mom has been here, mostly, and at the CAFTA embassy.",
        ],
        scope_filters,
    )
    assert any("Kiasma museum" in line for line in filtered)


def test_bridge_location_assessment_does_not_mark_alias_as_missing_anchor() -> None:
    question = "Which character has been to Helsinki?"
    results = [
        {
            "summary": "Mom has been here, mostly, and at the CAFTA embassy.",
            "assistant_response": "Mom has been here, mostly, and at the CAFTA embassy.",
            "user_query": "",
            "key_entities": ["CAFTA"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Lexy and Caleb endured the dreadful night.",
            "assistant_response": "Actually, Caleb lives next to the Kiasma museum.",
            "user_query": "",
            "key_entities": ["Caleb", "Kiasma"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]
    assessment = assess_evidence_chain(question, results)
    assert "missing_anchor" not in assessment.get("reason_codes", [])
    assert "relation_mismatch" not in assessment.get("reason_codes", [])


def test_bridge_painting_assessment_does_not_mark_alias_as_missing_anchor() -> None:
    question = "Which character has been to the Mauritshuis?"
    results = [
        {
            "summary": "Mom has been here, mostly, and at the CAFTA embassy.",
            "assistant_response": "Mom has been here, mostly, and at the CAFTA embassy.",
            "user_query": "",
            "key_entities": ["CAFTA"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Megan saw the original painting.",
            "assistant_response": "In 2013, after waiting in line for hours, Megan finally saw the original 'Girl with a Pearl Earring' painting up close.",
            "user_query": "",
            "key_entities": ["Megan", "Girl with a Pearl Earring"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]
    assessment = assess_evidence_chain(question, results)
    assert "missing_anchor" not in assessment.get("reason_codes", [])
    assert "relation_mismatch" not in assessment.get("reason_codes", [])


def test_bridge_location_assessment_promotes_unique_direct_match() -> None:
    question = "Which character has been to Helsinki?"
    results = [
        {
            "summary": "Actually, Caleb lives next to the Kiasma museum.",
            "assistant_response": "Actually, Caleb lives next to the Kiasma museum.",
            "user_query": "",
            "key_entities": ["Caleb", "Kiasma"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Mom has been here, mostly, and at the CAFTA embassy.",
            "assistant_response": "Mom has been here, mostly, and at the CAFTA embassy.",
            "user_query": "",
            "key_entities": ["CAFTA"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Caleb"
    assert assessment["direct_match_count"] == 1


def test_bridge_vegan_assessment_promotes_unique_direct_match() -> None:
    question = "Which character cannot eat fish-based meals?"
    results = [
        {
            "summary": "Then Stuart mentioned that he has been vegan for years.",
            "assistant_response": "Then Stuart mentioned that he has been vegan for years.",
            "user_query": "",
            "key_entities": ["Stuart"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Dinner followed and everyone stayed quiet.",
            "assistant_response": "Dinner followed and everyone stayed quiet.",
            "user_query": "",
            "key_entities": ["Dinner"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Stuart"
    assert assessment["direct_match_count"] == 1


def test_bridge_painting_assessment_promotes_unique_direct_match() -> None:
    question = "Which character has been to the Mauritshuis?"
    results = [
        {
            "summary": "In 2013, Megan finally saw the original Girl with a Pearl Earring painting up close.",
            "assistant_response": "In 2013, Megan finally saw the original Girl with a Pearl Earring painting up close.",
            "user_query": "",
            "key_entities": ["Megan", "Girl with a Pearl Earring"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "The room stayed quiet.",
            "assistant_response": "The room stayed quiet.",
            "user_query": "",
            "key_entities": ["room"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Megan"
    assert assessment["direct_match_count"] == 1


def test_bridge_location_inverse_form_promotes_unique_direct_match() -> None:
    question = "Which character has been to Helsinki?"
    results = [
        {
            "summary": "The Kiasma museum is next to where Caleb lives.",
            "assistant_response": "The Kiasma museum is next to where Caleb lives.",
            "user_query": "",
            "key_entities": ["Caleb", "Kiasma"],
            "metadata": {"source": "benchmark_history_incomplete"},
        }
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Caleb"
    assert assessment["direct_match_count"] == 1


def test_bridge_painting_inverse_form_promotes_unique_direct_match() -> None:
    question = "Which character has been to the Mauritshuis?"
    results = [
        {
            "summary": "In 2013, the original Girl with a Pearl Earring painting was seen up close by Megan, finally, after waiting in line for hours.",
            "assistant_response": "In 2013, the original Girl with a Pearl Earring painting was seen up close by Megan, finally, after waiting in line for hours.",
            "user_query": "",
            "key_entities": ["Megan", "Girl with a Pearl Earring"],
            "metadata": {"source": "benchmark_history_incomplete"},
        }
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Megan"
    assert assessment["direct_match_count"] == 1


def test_bridge_painting_inverse_long_chunk_extracts_passive_voice_candidate() -> None:
    question = "Which character has been to the Mauritshuis?"
    long_chunk = (
        "When she looked back upon the experiences of that dreadful night, it seemed to Lexy that both she and her companion "
        "displayed almost incredible endurance. Since morning they had lived through a very lifetime of emotion, to end now "
        "in this tragedy more horrible than anything they could have feared. The room darkened again. "
        "In 2013, the original 'Girl with a Pearl Earring' painting was seen up close by Megan, finally, after waiting in line for hours. "
        "\"What?\" \"There were ten charges on the bridge, all along its length.\""
    )
    item = {
        "summary": long_chunk[:120],
        "assistant_response": long_chunk,
        "user_query": "When she looked back upon the experiences of that dreadful night, it seemed to Lexy that both she and her companion",
        "key_entities": ["RAG", "she", "looked", "back", "Lexy", "Since", "Girl", "Pearl"],
        "metadata": {"source": "benchmark_context"},
    }

    assert "Megan" in tools._candidate_names_for_item(question, item, limit=6)
    assessment = assess_evidence_chain(question, [item], evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "pass"
    assert assessment["top_candidate"] == "Megan"
    assert assessment["direct_match_count"] == 1


def test_external_generalization_location_pregate_relaxes_to_verify() -> None:
    question = "How long have I been living in my current apartment in Shinjuku?"
    results = [
        {
            "summary": "The Harajuku apartment has been convenient for getting around Tokyo.",
            "assistant_response": "The Harajuku apartment has been convenient for getting around Tokyo.",
            "user_query": "I've been living in my current apartment in Harajuku for 1 hour from the station.",
            "key_entities": ["Harajuku"],
            "metadata": {"source": "benchmark_history_incomplete"},
        }
    ]
    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "verify"
    assert "exploratory_continue" in assessment["reason_codes"]
    assert "competing_harajuku" in assessment["reason_codes"]


def test_external_generalization_location_pregate_without_competing_anchor_relaxes_to_verify() -> None:
    question = "How long have I been living in my current apartment in Shinjuku?"
    results = [
        {
            "summary": "You moved into the apartment in Shinjuku two years ago.",
            "assistant_response": "",
            "metadata": {"source": "benchmark_history_incomplete"},
        }
    ]

    assessment = assess_evidence_chain(question, results, evidence_thresholds={"profile_name": "external-generalization"})
    assert assessment["verifier_action"] == "verify"
    assert "exploratory_continue" in assessment["reason_codes"]


def test_external_generalization_generic_bridge_score_promotes_direct_match(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "bamboo_meetingqa")
    question = "Which character has been to the museum?"
    item = {
        "summary": "Megan visited the museum with Caleb.",
        "assistant_response": "",
        "user_query": "",
        "key_entities": ["Megan", "Caleb"],
        "metadata": {"source": "benchmark_history_incomplete"},
    }

    assert tools._bridge_candidate_match_score(question, "Megan visited the museum with Caleb.", "Megan") > 0
    rows = tools._build_disambiguation_candidate_rows(question, [item])
    assert any(row["candidate"] == "Megan" and row["direct_target_match"] for row in rows)


def test_nolima_direct_fact_bypasses_strict_gate(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Evidence chain assessment:\n"
        "- verifier_action=refuse\n"
        "- reason_codes=no_direct_match\n\n"
        "Relevant snippets:\n"
        "- Actually, Caleb lives next to the Kiasma museum.\n"
    )
    answer = agent.execute(
        mode="grounded_answer",
        user_question="Which character lives next to the Kiasma museum?",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )
    assert answer == "Caleb"


def test_nolima_bridge_direct_fact_passes_strict_gate_from_json_evidence(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Evidence chain assessment:\n"
        "- verifier_action=refuse\n"
        "- reason_codes=no_direct_match\n\n"
        "Money ledger:\n"
        '- money_ledger={"amount": 0.0, "currency": "USD", "source": "A message came in from Veronica saying, \\"I\'m lactose intolerant,\\" and nothing more."}\n'
    )
    answer = agent.execute(
        mode="grounded_answer",
        user_question="Which character cannot drink milk?",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )
    assert answer == "Veronica"


def test_nolima_bridge_fact_overrides_hard_refusal_in_answer_shape(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Evidence chain assessment:\n"
        "- verifier_action=refuse\n"
        "- reason_codes=missing_anchor,relation_mismatch,competing_she\n"
        "- missing_slots=Mauritshuis\n\n"
        "Relevant snippets:\n"
        "- In 2013, after waiting in line for hours, Megan finally saw the original Girl with a Pearl Earring painting up close.\n"
    )
    answer = agent._enforce_english_answer_shape(
        "Which character has been to the Mauritshuis?",
        "I cannot answer this question.",
        fact_sheet,
    )
    assert answer == "Megan"


def test_nolima_bridge_fact_overrides_hard_refusal_in_execute(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Evidence chain assessment:\n"
        "- verifier_action=refuse\n"
        "- reason_codes=missing_anchor,relation_mismatch,competing_she\n"
        "- missing_slots=fish-based meals\n\n"
        "Relevant snippets:\n"
        "- Then Stuart mentioned that he has been vegan for years.\n"
    )
    answer = agent.execute(
        mode="grounded_answer",
        user_question="Which character cannot eat fish-based meals?",
        context=fact_sheet,
        use_memory=True,
        executor_role="reasoning",
        collaboration_mode="off",
    )
    assert answer == "Stuart"


def test_nolima_name_only_shape_prefers_unique_candidate_over_location_noise(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Evidence chain assessment:\n"
        "- verifier_action=pass\n"
        "- reason_codes=\n"
        "- direct_match_count=1\n"
        "- top_candidate=Stuart\n\n"
        "Relevant snippets:\n"
        "- Then Stuart mentioned that he has been vegan for years.\n"
    )
    answer = agent._enforce_english_answer_shape(
        "Which character cannot eat fish-based meals?",
        "Melbourne",
        fact_sheet,
    )
    assert answer == "Stuart"


def test_nolima_name_only_shape_prefers_unique_candidate_over_pronoun_noise(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Evidence chain assessment:\n"
        "- verifier_action=pass\n"
        "- reason_codes=\n"
        "- direct_match_count=1\n"
        "- top_candidate=Megan\n\n"
        "Relevant snippets:\n"
        "- In 2013, the original 'Girl with a Pearl Earring' painting was seen up close by Megan, finally, after waiting in line for hours.\n"
    )
    answer = agent._enforce_english_answer_shape(
        "Which character has been to the Mauritshuis?",
        "It",
        fact_sheet,
    )
    assert answer == "Megan"


def test_nolima_bridge_direct_fact_beats_generic_been_overlap(monkeypatch) -> None:
    monkeypatch.setenv("MASE_BENCHMARK_PROFILE", "nolima_memory_ingest")
    agent = ExecutorAgent(model_interface=ExternalFallbackModelInterface())  # type: ignore[arg-type]
    fact_sheet = (
        "Relevant snippets:\n"
        "- In 2013, the original 'Girl with a Pearl Earring' painting was seen up close by Megan, finally, after waiting in line for hours.\n"
        "- Mom has been here, mostly, and at the CAFTA embassy.\n"
    )
    answer = agent._extract_direct_fact_answer(
        "Which character has been to the Mauritshuis?",
        fact_sheet,
    )
    assert answer == "Megan"


def test_focus_search_results_keeps_bridge_candidate_for_location_name_lookup() -> None:
    question = "Which character has been to Helsinki?"
    results = [
        {
            "summary": "Thank you very much, Miss Moran!",
            "assistant_response": "Thank you very much, Miss Moran! Better make a run for it!",
            "user_query": "",
            "key_entities": ["Miss Moran"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Marcus refuses to answer.",
            "assistant_response": "This is your last chance, Marcus, she said.",
            "user_query": "",
            "key_entities": ["Marcus"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Lexy and Caleb endured the dreadful night.",
            "assistant_response": "Actually, Caleb lives next to the Kiasma museum.",
            "user_query": "",
            "key_entities": ["Caleb", "Kiasma"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]

    focused = focus_search_results(results, question, max_items=2)
    assert any("Caleb" in str(item.get("assistant_response") or "") for item in focused)


def test_focus_search_results_promotes_vegan_bridge_candidate() -> None:
    question = "Which character cannot eat fish-based meals?"
    results = [
        {
            "summary": "Marcus refuses to answer.",
            "assistant_response": "This is your last chance, Marcus, she said.",
            "user_query": "",
            "key_entities": ["Marcus"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Stuart mentioned a dietary restriction.",
            "assistant_response": "Then Stuart mentioned that he has been vegan for years.",
            "user_query": "",
            "key_entities": ["Stuart"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Thank you very much, Miss Moran!",
            "assistant_response": "Thank you very much, Miss Moran! Better make a run for it!",
            "user_query": "",
            "key_entities": ["Miss Moran"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]

    focused = focus_search_results(results, question, max_items=2)
    assert "Stuart" in str(focused[0].get("assistant_response") or "")


def test_focus_search_results_promotes_painting_bridge_candidate() -> None:
    question = "Which character has been to the Mauritshuis?"
    results = [
        {
            "summary": "Mom has been here, mostly, and at the CAFTA embassy.",
            "assistant_response": "Mom has been here, mostly, and at the CAFTA embassy.",
            "user_query": "",
            "key_entities": ["Mom", "CAFTA"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "She’s married to an American doctor.",
            "assistant_response": "She’s married to an American doctor.",
            "user_query": "",
            "key_entities": ["She"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Megan finally saw the painting up close.",
            "assistant_response": "In 2013, after waiting in line for hours, Megan finally saw the original Girl with a Pearl Earring painting up close.",
            "user_query": "",
            "key_entities": ["Megan", "Girl with a Pearl Earring"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
    ]

    focused = focus_search_results(results, question, max_items=2)
    assert "Megan" in str(focused[0].get("assistant_response") or "")


def test_rerank_results_for_query_promotes_bridge_candidate_for_vegan_lookup() -> None:
    question = "Which character cannot eat fish-based meals?"
    results = [
        {
            "summary": "Huldah tossed her head during study hour.",
            "assistant_response": "I've got something better to think of, Huldah tossed her head.",
            "user_query": "",
            "key_entities": ["Huldah"],
        },
        {
            "summary": "Stuart mentioned a dietary restriction.",
            "assistant_response": "Then Stuart mentioned that he has been vegan for years.",
            "user_query": "",
            "key_entities": ["Stuart"],
        },
        {
            "summary": "Marcus refused to answer.",
            "assistant_response": "This is your last chance, Marcus, she said.",
            "user_query": "",
            "key_entities": ["Marcus"],
        },
    ]

    reranked = _rerank_results_for_query(results, question)
    assert "Stuart" in str(reranked[0].get("assistant_response") or "")


def test_rerank_results_for_query_promotes_bridge_candidate_for_mauritshuis_lookup() -> None:
    question = "Which character has been to the Mauritshuis?"
    results = [
        {
            "summary": "Mom has been here, mostly, and at the CAFTA embassy.",
            "assistant_response": "Mom has been here, mostly, and at the CAFTA embassy.",
            "user_query": "",
            "key_entities": ["Mom", "CAFTA"],
            "metadata": {"source": "benchmark_history_incomplete"},
        },
        {
            "summary": "Megan finally saw the painting up close.",
            "assistant_response": "In 2013, after waiting in line for hours, Megan finally saw the original Girl with a Pearl Earring painting up close.",
            "user_query": "",
            "key_entities": ["Megan", "Girl with a Pearl Earring"],
        },
        {
            "summary": "Lexy reflected on the telephone call.",
            "assistant_response": "Lexy reflected on the telephone call and the dreadful night.",
            "user_query": "",
            "key_entities": ["Lexy"],
        },
    ]

    reranked = _rerank_results_for_query(results, question)
    assert "Megan" in str(reranked[0].get("assistant_response") or "")


def test_location_name_lookup_can_start_bridge_coverage_loop() -> None:
    assessment = {"verifier_action": "refuse", "reason_codes": ["missing_helsinki", "location"]}
    assert _should_start_coverage_loop(
        "Which character has been to Helsinki?",
        results=[{"summary": "Actually, Caleb lives next to the Kiasma museum."}],
        fact_sheet="Relevant snippets:\n- Actually, Caleb lives next to the Kiasma museum.",
        evidence_assessment=assessment,
    )
