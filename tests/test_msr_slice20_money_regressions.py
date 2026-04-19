from __future__ import annotations

from mase_tools.legacy import _build_aggregation_notes

from mase_tools import legacy as tools


def _result(summary: str, *, session_id: str) -> dict[str, object]:
    return {
        "summary": summary,
        "user_query": summary,
        "assistant_response": "",
        "memory_profile": {},
        "date": "2023/05/05",
        "time": "12:00",
        "metadata": {
            "source": "benchmark_history",
            "benchmark_question_id": "gpt4_d84a3211",
            "session_id": session_id,
        },
    }


def test_bike_money_hydrates_benchmark_history_turns(monkeypatch) -> None:
    question = "How much total money have I spent on bike-related expenses since the start of the year?"

    resolved_by_session = {
        "bike-repair": (
            "Actually, I remember taking my bike in for a tune-up on April 20th because the gears were getting stuck. "
            "The mechanic told me I needed to replace the chain, which I did, and it cost me $25. "
            "While I was there, I also got a new set of bike lights installed, which were $40."
        ),
        "bike-helmet": (
            "I've had good experiences with the local bike shop downtown where I bought my Bell Zephyr helmet for $120."
        ),
    }

    monkeypatch.setattr(
        tools,
        "_resolve_longmemeval_session_text",
        lambda question_id, session_id, user_query: resolved_by_session.get(session_id, ""),
    )

    notes = _build_aggregation_notes(
        question,
        [
            _result(
                "Actually, I remember taking my bike in for a tune-up on April 20th. "
                "While I was there, I also got a new set of bike lights installed.",
                session_id="bike-repair",
            ),
            _result(
                "I've had good experiences with the local bike shop downtown where I bought my Bell Zephyr helmet.",
                session_id="bike-helmet",
            ),
        ],
    )

    joined = "\n".join(notes)
    assert "$185" in joined
    assert "$25" in joined and "$40" in joined and "$120" in joined
