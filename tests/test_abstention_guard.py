from __future__ import annotations

from executor import ExecutorAgent


def test_refusal_message_builds_contrastive_pet_detail() -> None:
    agent = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = "Relevant snippets:\n- My cat Luna likes sleeping by the window."

    answer = agent._refusal_message("What is the name of my hamster?", fact_sheet)

    assert answer == "You did not mention this information. You mentioned your cat Luna but not your hamster."


def test_execute_refuses_when_evidence_gate_fails_even_with_deterministic_answer(monkeypatch) -> None:
    monkeypatch.delenv("MASE_BENCHMARK_PROFILE", raising=False)
    agent = ExecutorAgent(model_interface=None)  # type: ignore[arg-type]
    fact_sheet = """
Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=missing_anchor
Deterministic count: 3
""".strip()

    answer = agent.execute(
        mode="grounded_answer",
        user_question="How many weddings have I attended this year?",
        context=fact_sheet,
        use_memory=True,
        collaboration_mode="off",
    )

    assert answer == "You did not mention this information."
