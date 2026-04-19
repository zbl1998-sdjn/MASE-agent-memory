from __future__ import annotations

import json

from executor import ExecutorAgent
from mase_tools.legacy import (
    _build_english_search_profile,
    _extract_english_money_difference,
    _extract_relevant_snippets,
    _extract_scalar_reasoning_notes,
    _extract_state_transition_count_reasoning,
    extract_question_scope_filters,
)
from orchestrator import _slot_contract_state
from planner import build_planner_decision
from planner_agent import PlannerAgent


def build_executor() -> ExecutorAgent:
    return ExecutorAgent(model_interface=None)  # type: ignore[arg-type]


class StubPlannerModelInterface:
    def chat(self, *_args, **_kwargs):
        return {
            "message": {
                "content": json.dumps(
                    {
                        "task_description": "remember budget",
                        "query_variants": ["budget"],
                        "topic_hints": ["budget"],
                        "recent_count": 1,
                        "expected_output_format": "direct",
                        "reasoning_hint": "",
                        "sub_tasks": ["retrieve evidence"],
                        "verification_focus": ["evidence coverage"],
                        "scope_filters": {
                            "months": None,
                            "weekdays": None,
                            "locations": ["United States"],
                            "relative_terms": None,
                            "strict": True,
                        },
                    },
                    ensure_ascii=False,
                )
            }
        }


def test_delta_money_difference_uses_question_anchors() -> None:
    result = _extract_english_money_difference(
        "How much more did I spend on accommodations per night in Hawaii compared to Tokyo?",
        [
            "I've already booked a luxurious resort in Maui that costs over $300 per night.",
            "I stayed in a hostel in Tokyo that cost around $30 per night when I went solo last January.",
        ],
    )
    assert result is not None
    left_label, left_value, right_label, right_value, delta = result
    assert "hawaii" in left_label
    assert "tokyo" in right_label
    assert (left_value, right_value, delta) == (300.0, 30.0, 270.0)


def test_planner_scope_filters_accept_null_lists_from_model() -> None:
    planner = PlannerAgent(model_interface=StubPlannerModelInterface())  # type: ignore[arg-type]
    plan = planner.plan_task(
        user_question="What was my budget in the United States this year?",
        task_type="grounded_answer",
        executor_role="memory_grounded",
        planner_strategy="zoom_in_out",
        query_variants=["budget"],
    )
    assert plan.scope_filters["months"] == []
    assert plan.scope_filters["weekdays"] == []
    assert plan.scope_filters["relative_terms"]
    assert "United States" in plan.scope_filters["locations"]


def test_autonomous_decision_chain_promotes_source_arbitration() -> None:
    decision = build_planner_decision(
        user_question="How should the autonomous decision chain arbitrate sources for this evidence?",
        route_action="search_memory",
        route_keywords=["autonomous", "decision", "chain"],
        task_type="grounded_analysis",
        executor_role="reasoning",
        use_memory=True,
        base_memory_limit=3,
    )
    lowered_variants = " ".join(decision.query_variants).lower()
    assert "autonomous decision chain" in lowered_variants
    assert decision.widen_search is True
    assert decision.collaboration_mode == "verify"
    assert any(step.step_id == "plan-arbitrate" for step in decision.steps)

    planner = PlannerAgent(model_interface=None)
    model_plan = planner.plan_task(
        user_question="How should the autonomous decision chain arbitrate sources for this evidence?",
        task_type="grounded_analysis",
        executor_role="reasoning",
        planner_strategy=decision.strategy,
        query_variants=decision.query_variants,
    )
    assert "source arbitration" in model_plan.verification_focus
    assert "arbitrate sources" in model_plan.sub_tasks


def test_update_resolution_builds_previous_and_current_states() -> None:
    notes = _extract_state_transition_count_reasoning(
        "How much more did I have to pay for the trip after the initial quote?",
        [
            "They initially quoted me $2,500 for the entire trip.",
            "The corrected price for the entire trip was $2,800.",
        ],
    )
    assert any("previous = $2500 amount ; current = $2800 amount" in note for note in notes)

    fact_sheet = "Aggregation worksheet:\n" + "\n".join(notes)
    executor = build_executor()
    assert executor._extract_deterministic_aggregation_answer(
        "How much more did I have to pay for the trip after the initial quote?",
        fact_sheet,
    ) == "$300"
    assert _slot_contract_state(
        "How much more did I have to pay for the trip after the initial quote?",
        [],
        fact_sheet,
    )["incomplete"] is False


def test_old_state_future_age_projection_resolves() -> None:
    notes = _extract_scalar_reasoning_notes(
        "How many years will I be when my friend Rachel gets married?",
        [
            "My friend Rachel's getting married next year.",
            "I'm 32, so I'm in my 30s.",
        ],
    )
    assert any("Deterministic future age: 33" in note for note in notes)

    fact_sheet = "Aggregation worksheet:\n" + "\n".join(notes)
    executor = build_executor()
    assert executor._extract_deterministic_aggregation_answer(
        "How many years will I be when my friend Rachel gets married?",
        fact_sheet,
    ) == "33"
    assert _slot_contract_state(
        "How many years will I be when my friend Rachel gets married?",
        [],
        fact_sheet,
    )["incomplete"] is False


def test_remaining_and_percentage_contracts_accept_formula_anchors() -> None:
    remaining_fact_sheet = """
Aggregation worksheet:
- Deterministic scalar remaining: 300 - 190 = 110 pages
"""
    remaining_state = _slot_contract_state(
        "How many pages do I have left to read?",
        [],
        remaining_fact_sheet,
    )
    assert remaining_state["contract_type"] == "remaining"
    assert remaining_state["incomplete"] is False

    percentage_fact_sheet = """
Aggregation worksheet:
- Deterministic percentage: 2 / 5 = 40%
"""
    percentage_state = _slot_contract_state(
        "What percentage of the shoes I packed did I wear?",
        [],
        percentage_fact_sheet,
    )
    assert percentage_state["contract_type"] == "percentage"
    assert percentage_state["incomplete"] is False


def test_temporal_delta_regressions_stay_out_of_refusal_gate() -> None:
    executor = build_executor()
    refusal = "The information provided is not enough. You did not mention this information."
    cases = [
        (
            "How many months have passed since I last visited a museum with a friend?",
            """
Aggregation worksheet:
- Deterministic delta: 5 months
- Intermediate verification: event_date=2022-10-22, reference_date=2023-03-25, delta_days=154

Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=contract_gate_fail,duration-total-gap,retrieval_gap
- contract_type=duration_total
- failure_bucket=retrieval_gap
- missing_slots=duration_rows
""",
            "5 months",
        ),
        (
            "How many days passed between the day I cancelled my FarmFresh subscription and the day I did my online grocery shopping from Instacart?",
            """
Aggregation worksheet:
- Deterministic delta: 2023-01-05 to 2023-02-28 = 54 days
- Intermediate verification: start_date=2023-01-05, end_date=2023-02-28, delta=54 days

Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=contract_gate_fail,duration-total-gap,retrieval_gap
- contract_type=duration_total
- failure_bucket=retrieval_gap
- missing_slots=duration_rows
""",
            "54 days",
        ),
        (
            "How many days ago did I buy a smoker?",
            """
Aggregation worksheet:
- Deterministic delta: 10 days
- Intermediate verification: event_date=2023-03-15, reference_date=2023-03-25, delta_days=10

Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=contract_gate_fail,duration-total-gap,retrieval_gap
- contract_type=duration_total
- failure_bucket=retrieval_gap
- missing_slots=duration_rows
""",
            "10 days",
        ),
    ]

    for question, fact_sheet, expected in cases:
        state = _slot_contract_state(question, [], fact_sheet)
        assert state["incomplete"] is False
        assert executor._extract_deterministic_aggregation_answer(question, fact_sheet) == expected
        assert executor._enforce_english_answer_shape(question, refusal, fact_sheet) == expected


def test_three_event_order_survives_disambiguation_refusal_when_order_is_deterministic() -> None:
    executor = build_executor()
    question = (
        "Which three events happened in the order from first to last: the day I helped my friend prepare the nursery, "
        "the day I helped my cousin pick out stuff for her baby shower, and the day I ordered a customized phone case "
        "for my friend's birthday?"
    )
    fact_sheet = """
Aggregation worksheet:
- Deterministic ordered events: helped my friend prepare the nursery -> helped my cousin pick out stuff for her baby shower -> ordered a customized phone case for my friend's birthday
- Deterministic chronology: earliest = **For Your Gamer Brother:** 1. New Game Release

Evidence chain assessment:
- evidence_confidence=low
- verifier_action=refuse
- reason_codes=relation_mismatch,missing_anchor,missing_cousin,competing_sister,family_relation
- threshold_profile=english-disambiguation-high-dynamic
- failure_bucket=unsupported_relation
- missing_slots=cousin
"""
    expected = (
        "First, I helped my friend prepare the nursery, then I helped my cousin pick out stuff for her baby shower, "
        "and lastly, I ordered a customized phone case for my friend's birthday."
    )

    assert executor._extract_deterministic_aggregation_answer(question, fact_sheet) == expected
    assert executor.execute(
        "grounded_disambiguation",
        question,
        fact_sheet,
        use_memory=True,
        collaboration_mode="off",
    ) == expected


def test_unique_direct_match_overrides_refusal_for_disambiguation_name_lookup() -> None:
    executor = build_executor()
    fact_sheet = """
    Evidence chain assessment:
    - evidence_confidence=low
    - verifier_action=refuse
    - reason_codes=no_direct_match
    - direct_match_count=1
    - top_candidate=Alice
    """.strip()

    assert (
        executor.execute(
            "grounded_disambiguation",
            "Which speaker is referenced at the end of the last sentence?",
            fact_sheet,
            use_memory=True,
            collaboration_mode="off",
        )
        == "Alice"
    )


def test_planned_to_purchased_state_transition_resolves() -> None:
    notes = _extract_state_transition_count_reasoning(
        "How many model kits did I plan to buy, and how many did I actually buy?",
        [
            "I planned to buy 4 model kits for the winter project.",
            "I ended up buying 3 model kits after the sale ended.",
        ],
    )
    assert any("previous = 4 model kits ; current = 3 model kits" in note for note in notes)

    fact_sheet = "Aggregation worksheet:\n" + "\n".join(notes)
    assert _slot_contract_state(
        "How many model kits did I plan to buy, and how many did I actually buy?",
        [],
        fact_sheet,
    )["incomplete"] is False


def test_ram_question_preserves_non_money_unit() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: Before the RAM upgrade to 16GB, I was getting around 6-7 hours of battery life.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How much RAM did I upgrade my laptop to?",
        fact_sheet,
    ) == "16GB"
    assert executor._enforce_english_answer_shape(
        "How much RAM did I upgrade my laptop to?",
        "16",
        fact_sheet,
    ) == "16GB"


def test_worth_question_prefers_relative_value_phrase() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: The painting of a sunset is worth triple what I paid for it.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How much is the painting of a sunset worth in terms of the amount I paid for it?",
        fact_sheet,
    ) == "The painting is worth triple what I paid for it."


def test_copy_question_prefers_explicit_numeric_quantity() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: My signed poster from my favorite artist's debut album is a limited edition of only 500 copies worldwide.
- Countable items:
- 1. edition only copy worldwide
- 2. signed poster
- 3. favorite artist debut album
- Deterministic count: 3 items
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How many copies of my favorite artist's debut album were released worldwide?",
        fact_sheet,
    ) == "500"


def test_ethnicity_answer_normalizes_to_mix_phrase() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: The Irish are known for their warm hospitality, while the Italians are famous for their passion for life.
- Atomic fact: Embracing your mixed ethnicity can broaden your perspective.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What is my ethnicity?",
        fact_sheet,
    ) == "A mix of Irish and Italian"


def test_gift_giver_relation_extracts_family_member() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I actually got my new stand mixer as a birthday gift from my sister last month.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Who gave me a new stand mixer as a birthday gift?",
        fact_sheet,
    ) == "my sister"


def test_academic_subject_is_not_treated_as_location_scope() -> None:
    scope = extract_question_scope_filters("Where did I complete my Bachelor's degree in Computer Science?")
    assert scope["locations"] == []
    assert scope["strict"] is False


def test_music_streaming_service_profile_expands_to_spotify() -> None:
    profile = _build_english_search_profile(
        ["music streaming service"],
        full_query="What is the name of the music streaming service have I been using lately?",
        query_variants=["music streaming service", "name of music streaming service"],
    )
    assert "spotify" in [item.lower() for item in profile["expanded_terms"]]


def test_music_streaming_service_extracts_spotify_from_evidence_memo() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-20 10-20-00
Summary：I'm really into indie and alternative rock right now, so Arctic Monkeys and The Neighbourhood sound great. I've been listening to their songs a lot on Spotify lately.
Relevant lines:
- I'm really into indie and alternative rock right now, so Arctic Monkeys and The Neighbourhood sound great
- Their music often features a mix of garage rock and post-punk influences, which might appeal to fans of Arctic Monkeys and The Neighbourhood
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What is the name of the music streaming service have I been using lately?",
        fact_sheet,
    ) == "Spotify"


def test_relevant_snippets_keep_spotify_sentence_for_music_service_lookup() -> None:
    snippets = _extract_relevant_snippets(
        "What is the name of the music streaming service have I been using lately?",
        {
            "summary": "I'm really into indie and alternative rock right now, so Arctic Monkeys and The Neighbourhood sound great.",
            "user_query": "I'm really into indie and alternative rock right now, so Arctic Monkeys and The Neighbourhood sound great. I've been listening to their songs a lot on Spotify lately.",
            "assistant_response": "Arctic Monkeys and The Neighbourhood are both fantastic live acts.",
        },
    )
    assert any("spotify" in snippet.lower() for snippet in snippets)


def test_relevant_snippets_keep_golden_retriever_tail_for_dog_breed_lookup() -> None:
    snippets = _extract_relevant_snippets(
        "What breed is my dog?",
        {
            "summary": "I'm thinking of getting Max a new collar with a nice name tag.",
            "user_query": "I'm thinking of getting Max a new collar with a nice name tag. Do you have any recommendations for a good collar brand or type that would suit a Golden Retriever like Max?",
            "assistant_response": "A new collar with a nice name tag is a great idea!",
        },
    )
    assert any("golden retriever" in snippet.lower() for snippet in snippets)


def test_relevant_snippets_keep_full_user_query_tail_for_color_lookup() -> None:
    snippets = _extract_relevant_snippets(
        "What color did I repaint my bedroom walls?",
        {
            "summary": "I've heard great things about Snake Plants, but I'm also curious about the ZZ Plant.",
            "user_query": "I've heard great things about Snake Plants, but I'm also curious about the ZZ Plant. Can you tell me more about its watering schedule and how often it needs to be fertilized? By the way, I've been doing some redecorating and recently repainted my bedroom walls a lighter shade of gray - it's made the room feel so much brighter!",
            "assistant_response": "The ZZ Plant is an excellent choice!",
        },
    )
    assert any("lighter shade of gray" in snippet.lower() for snippet in snippets)


def test_relevant_snippets_keep_previous_stance_tail_for_spirituality_lookup() -> None:
    snippets = _extract_relevant_snippets(
        "What was my previous stance on spirituality?",
        {
            "summary": "I'm trying to find some books on synchronicity and its connection to spirituality.",
            "user_query": "I'm trying to find some books on synchronicity and its connection to spirituality. Can you recommend some titles or authors? By the way, I've been reading a lot about Buddhism lately, which is a big shift from my previous stance on spirituality - I used to be a staunch atheist, but I've been exploring other possibilities.",
            "assistant_response": "What a fascinating journey you're on!",
        },
    )
    assert any("staunch atheist" in snippet.lower() for snippet in snippets)


def test_planner_expands_model_kit_focus_terms() -> None:
    decision = build_planner_decision(
        "How many model kits have I worked on or bought?",
        "search_memory",
        ["__FULL_QUERY__"],
        "grounded_answer",
        "reasoning",
        True,
        3,
    )
    lowered = " ".join(decision.query_variants).lower()
    assert "revell" in lowered or "tamiya" in lowered


def test_deterministic_money_total_prefers_structured_rows_over_budget_example() -> None:
    executor = build_executor()
    fact_sheet = "\n".join(
        [
            "Aggregation worksheet:",
            "- Atomic fact: For example, you could allocate $200-300 per month for discretionary spending on fashion or luxury items.",
            "Event cards:",
            f"- {json.dumps({'event_type': 'luxury_purchase', 'display_name': 'handbag', 'normalized_name': 'handbag', 'attributes': {'spend_amount': 1200}})}",
            f"- {json.dumps({'event_type': 'luxury_purchase', 'display_name': 'gown', 'normalized_name': 'gown', 'attributes': {'spend_amount': 800}})}",
            "Money ledger:",
            f"- money_ledger={json.dumps({'amount': 200.0, 'currency': 'USD', 'purpose': 'luxury', 'source': 'For example, you could allocate $200-300 per month for discretionary spending on fashion or luxury items'})}",
            f"- money_ledger={json.dumps({'amount': 1200.0, 'currency': 'USD', 'purpose': 'luxury', 'source': 'designer handbag from Gucci for $1,200'})}",
            f"- money_ledger={json.dumps({'amount': 800.0, 'currency': 'USD', 'purpose': 'luxury', 'source': 'luxury evening gown for $800'})}",
            "- contract_type=money_total_by_purpose",
            "- verifier_action=pass",
        ]
    )
    assert executor._extract_direct_money_answer(
        "What is the total amount I spent on luxury items in the past few months?",
        fact_sheet,
    ) == ""
    assert executor._extract_deterministic_aggregation_answer(
        "What is the total amount I spent on luxury items in the past few months?",
        fact_sheet,
    ) == "$2,000"


def test_handbag_lookup_ignores_total_by_purpose_contract_when_direct_value_exists() -> None:
    executor = build_executor()
    fact_sheet = "\n".join(
        [
            "Evidence memo (deduplicated):",
            "Money ledger:",
            f"- money_ledger={json.dumps({'amount': 800.0, 'currency': 'USD', 'purpose': 'luxury', 'source': 'I remember buying a designer handbag for a pretty penny - $800, to be exact', 'verb': 'money'})}",
            f"- money_ledger={json.dumps({'amount': 800.0, 'currency': 'USD', 'purpose': 'luxury', 'source': 'Those $800 handbags and designer clothing can add up quickly!', 'verb': 'money'})}",
            f"- money_ledger={json.dumps({'amount': 800.0, 'currency': 'USD', 'purpose': 'luxury', 'source': '$800 is a significant expense, and it is great that you are aware of it', 'verb': 'money'})}",
            "- contract_type=money_total_by_purpose",
            "- verifier_action=pass",
        ]
    )
    assert executor._extract_deterministic_aggregation_answer(
        "How much did I spend on a designer handbag?",
        fact_sheet,
    ) == "$800"


def test_bachelor_degree_location_extracts_ucla() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: With your background in CS from UCLA and experience in the tech industry, you're well-positioned to secure a good job after graduating from Stanford.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I complete my Bachelor's degree in Computer Science?",
        fact_sheet,
    ) == "University of California, Los Angeles (UCLA)"


def test_study_abroad_location_ignores_lightroom_distractor() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-23 10-24-00
Summary：That sounds amazing! I've been to the Great Ocean Road before, and it's definitely a must-see in Australia. I actually went there with some friends during my study abroad program at the University of Melbourne.
Relevant lines:
- It's great to hear that you have fond memories of your study abroad program at the University of Melbourne. Study abroad experiences can be life-changing, and it's wonderful that you got to explore Australia's beauty during your time there
- I actually went there with some friends during my study abroad program at the University of Melbourne

[2] Time：2023-05-30 12-57-00
Summary：I'm looking for some tips on editing portraits in Lightroom.
Relevant lines:
- I'm looking for some tips on editing portraits in Lightroom

Structured memory cards:
- entity=Australia
- entity=Lightroom
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I attend for my study abroad program?",
        fact_sheet,
    ) == "University of Melbourne in Australia"


def test_concert_artist_is_not_treated_as_location_scope() -> None:
    scope = extract_question_scope_filters("Where did I attend the Imagine Dragons concert?")
    assert scope["locations"] == []


def test_cat_name_lookup_extracts_luna() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, my cat's name is Luna, and she's been such a sweetie.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What is the name of my cat?",
        fact_sheet,
    ) == "Luna"


def test_largemouth_bass_count_extracts_trip_quantity() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: Also, I caught 12 largemouth bass on my last trip there.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How many largemouth bass did I catch on my fishing trip to Lake Michigan?",
        fact_sheet,
    ) == "12"


def test_conversation_with_destiny_extracts_sarah() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I was just talking to my friend Sarah recently and she was saying how everything happens for a reason.
- Atomic fact: I've been thinking about my conversation with Sarah, and I wanted to explore the concept of destiny a bit more.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Who did I have a conversation with about destiny?",
        fact_sheet,
    ) == "Sarah"


def test_evening_routine_time_extracts_7_pm() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: Speaking of unwinding, I've been trying to establish a better evening routine, stopping work emails and messages by 7 pm to separate my work and personal life.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What time do I stop checking work emails and messages?",
        fact_sheet,
    ) == "7 PM"


def test_move_duration_prefers_move_time_over_distance() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: My new apartment is about 20 minutes away from my old place.
- Atomic fact: It took me and my friends around 5 hours to move everything into the new apartment.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How long did it take to move to the new apartment?",
        fact_sheet,
    ) == "5 hours"


def test_commute_duration_extracts_each_way_from_evidence_memo() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-22 21-18-00
Summary：I've been listening to audiobooks during my daily commute, which takes 45 minutes each way.
Relevant lines:
- I've been listening to audiobooks during my daily commute, which takes 45 minutes each way
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How long is my daily commute to work?",
        fact_sheet,
    ) == "45 minutes each way"


def test_duration_questions_preserve_wording_from_fact() -> None:
    executor = build_executor()
    vintage_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I've been collecting vintage cameras for three months now.
"""
    japan_fact_sheet = """
Aggregation worksheet:
- Atomic fact: I actually visited Fushimi Inari Shrine when I was in Japan a few months ago.
- Atomic fact: I spent two weeks traveling solo around the country.
"""
    assert executor._extract_direct_fact_answer(
        "How long have I been collecting vintage cameras?",
        vintage_fact_sheet,
    ) == "three months"
    assert executor._extract_direct_fact_answer(
        "How long was I in Japan for?",
        japan_fact_sheet,
    ) == "two weeks"


def test_duration_questions_ignore_ledger_nine_hours_noise_for_japan() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-30 03-02-00
Summary：I actually visited Fushimi Inari Shrine when I was in Japan a few months ago. I spent two weeks traveling solo around the country and it was an incredible experience.
Relevant lines:
- I actually visited Fushimi Inari Shrine when I was in Japan a few months ago
Money ledger:
- money_ledger={"amount": 0.0, "currency": "USD", "location_scope": ["kyoto", "japan"], "source": "Nine Hours Kyoto: Starting from ¥2,000 per night.", "verb": "free"}
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How long was I in Japan for?",
        fact_sheet,
    ) == "two weeks"


def test_current_book_extracts_currently_devouring_title() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-23 11-27-00
Summary：I'm trying to figure out how to fit more reading time into my daily routine. By the way, I'm currently devouring "The Seven Husbands of Evelyn Hugo" and it's hard to put down.
Relevant lines:
- By the way, I'm currently devouring "The Seven Husbands of Evelyn Hugo" and it's hard to put down
- We're going to discuss "The Last House Guest" by Megan Miranda, which I've already read and really enjoyed
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What book am I currently reading?",
        fact_sheet,
    ) == "The Seven Husbands of Evelyn Hugo"


def test_dog_breed_extracts_golden_retriever_from_evidence_memo() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-25 23-07-00
Summary：I'm thinking of getting Max a new collar with a nice name tag. Do you have any recommendations for a good collar brand or type that would suit a Golden Retriever like Max?
Relevant lines:
- Do you have any recommendations for a good collar brand or type that would suit a Golden Retriever like Max
- Golden Retrievers like Max deserve a comfortable, durable, and stylish collar
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What breed is my dog?",
        fact_sheet,
    ) == "Golden Retriever"


def test_week_long_family_trip_extracts_hawaii() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I'm actually thinking of going back to Hawaii, I loved it so much when I went with my family for a week last month!
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I go on a week-long trip with my family?",
        fact_sheet,
    ) == "Hawaii"


def test_wedding_location_extracts_grand_ballroom_from_evidence_memo() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-28 19-17-00
Summary：I was just at my cousin's wedding at the Grand Ballroom last weekend, and my mom looked absolutely stunning.
Relevant lines:
- I was just at my cousin's wedding at the Grand Ballroom last weekend, and my mom looked absolutely stunning
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I attend my cousin's wedding?",
        fact_sheet,
    ) == "Grand Ballroom"


def test_action_figure_answer_drops_extra_rarity_adjective() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I've been on a roll with my collectibles lately, just got a rare blue Snaggletooth action figure from a thrift store a few weeks ago.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What type of action figure did I buy from a thrift store?",
        fact_sheet,
    ) == "a blue Snaggletooth"


def test_documentary_screen_time_extracts_hours() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, I think I spent 10 hours last month watching documentaries on Netflix.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How many hours did I spend watching documentaries on Netflix last month?",
        fact_sheet,
    ) == "10 hours"


def test_bike_count_prefers_word_form_for_owned_bikes() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I can keep an eye on my three bikes when I'm not around them.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "How many bikes do I own?",
        fact_sheet,
    ) == "three"


def test_grounded_answer_allows_grounded_direct_facts_under_strict_gate() -> None:
    executor = build_executor()
    assert executor.execute(
        "grounded_answer",
        "What is the name of my cat?",
        """
Aggregation worksheet:
- Atomic fact: By the way, my cat's name is Luna, and she's been such a sweetie.
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "Luna"
    assert executor.execute(
        "grounded_answer",
        "Who did I have a conversation with about destiny?",
        """
Aggregation worksheet:
- Atomic fact: By the way, I was just talking to my friend Sarah recently and she was saying how everything happens for a reason.
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "Sarah"
    assert executor.execute(
        "grounded_answer",
        "What time do I stop checking work emails and messages?",
        """
Aggregation worksheet:
- Atomic fact: Speaking of unwinding, I've been trying to establish a better evening routine, stopping work emails and messages by 7 pm to separate my work and personal life.
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "7 PM"


def test_grounded_answer_bypasses_false_abstention_for_location_and_quantity_cases() -> None:
    executor = build_executor()
    assert executor.execute(
        "grounded_answer",
        "Where did I go on a week-long trip with my family?",
        """
Aggregation worksheet:
- Atomic fact: I'm actually thinking of going back to Hawaii, I loved it so much when I went with my family for a week last month!
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "Hawaii"
    assert executor.execute(
        "grounded_answer",
        "Where did I attend the Imagine Dragons concert?",
        """
Aggregation worksheet:
- Atomic fact: I finally got to see Imagine Dragons live at Xfinity Center last weekend.
- Atomic fact: My Jonas Brothers show at House of Blues was still fun too.
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "Xfinity Center"
    assert executor.execute(
        "grounded_answer",
        "How many largemouth bass did I catch on my fishing trip to Lake Michigan?",
        """
Aggregation worksheet:
- Atomic fact: Also, I caught 12 largemouth bass on my last trip there.
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "12"
    assert executor.execute(
        "grounded_answer",
        "How many hours did I spend watching documentaries on Netflix last month?",
        """
Aggregation worksheet:
- Atomic fact: By the way, I think I spent 10 hours last month watching documentaries on Netflix.
""",
        use_memory=True,
        collaboration_mode="off",
    ) == "10 hours"


def test_coupon_redemption_location_extracts_target() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I actually redeemed a $5 coupon on coffee creamer last Sunday, which was a nice surprise since I didn't know I had it in my email inbox.
- Atomic fact: I shop at Target pretty frequently, maybe every other week.
- Atomic fact: I've been using the Cartwheel app from Target and it's been really helpful for saving money on household items.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I redeem a $5 coupon on coffee creamer?",
        fact_sheet,
    ) == "Target"


def test_cocktail_recipe_extracts_lavender_gin_fizz() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I'm particularly interested in the Lavender Dream, as I've been experimenting with lavender in my cocktails lately. Speaking of which, I tried a lavender gin fizz recipe last weekend, but it needed a little more citrus.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What type of cocktail recipe did I try last weekend?",
        fact_sheet,
    ) == "lavender gin fizz"


def test_bedside_lamp_bulb_extracts_philips_led_bulb() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I think I'll start with some warm white bulbs for my kitchen and see how that goes. I've been using a Philips LED bulb in my bedside lamp, and I really like the warm tone it provides.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What type of bulb did I replace in my bedside lamp?",
        fact_sheet,
    ) == "Philips LED bulb"


def test_sister_location_extracts_denver() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: I'm thinking of visiting my sister Emily in Denver soon, and I was wondering if you knew any kid-friendly attractions there.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where does my sister Emily live?",
        fact_sheet,
    ) == "Denver"


def test_meet_sophia_extracts_coffee_shop_from_table_row() -> None:
    fact_sheet = """
Evidence memo (deduplicated):

[1] Time：2023-05-21 16-24-00
Summary：Alex and I talked about our jobs and commutes, and he recommended some podcasts to listen to.
Relevant lines:
- Alex and I talked about our jobs and commutes, and he recommended some podcasts to listen to
- | Sophia | Coffee Shop (City) | Indie music, coffee | Send her a list of new indie music releases |
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I meet Sophia?",
        fact_sheet,
    ) == "coffee shop in the city"


def test_game_title_extracts_dark_souls_3_dlc() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: By the way, speaking of gaming, I finally beat that last boss in the Dark Souls 3 DLC last weekend, after weeks of trying.
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "What game did I finally beat last weekend?",
        fact_sheet,
    ) == "Dark Souls 3 DLC"


def test_family_trip_profile_adds_week_phrase_variant() -> None:
    profile = _build_english_search_profile(
        [],
        full_query="Where did I go on a week-long trip with my family?",
        query_variants=["Where did I go on a week-long trip with my family?"],
    )
    assert "with my family for a week" in profile["exact_phrases"]


def test_concert_snippets_can_surface_fact_card_event_segment() -> None:
    snippets = _extract_relevant_snippets(
        "Where did I attend the Imagine Dragons concert?",
        {
            "summary": "I've got tickets to see the Jonas Brothers at TD Garden and The Lumineers at House of Blues.",
            "user_query": "I'm trying to plan out my summer concert schedule.",
            "fact_card": {
                "event_segments": [
                    {
                        "resolved_text": "I just remembered I went to an amazing Imagine Dragons concert recently, it was at the Xfinity Center on June 15th.",
                        "text": "I just remembered I went to an amazing Imagine Dragons concert recently, it was at the Xfinity Center on June 15th.",
                        "scope_hints": {"locations": ["Xfinity Center"], "months": ["june"], "weekdays": []},
                        "entities": ["Imagine Dragons", "Xfinity Center"],
                        "polarity": "positive",
                    }
                ]
            },
        },
    )
    assert any("Xfinity Center" in snippet for snippet in snippets)


def test_imagine_dragons_location_allows_optional_article() -> None:
    fact_sheet = """
Aggregation worksheet:
- Atomic fact: Oh, and I just remembered I went to an amazing Imagine Dragons concert recently, it was at the Xfinity Center on June 15th - what a show!
"""
    executor = build_executor()
    assert executor._extract_direct_fact_answer(
        "Where did I attend the Imagine Dragons concert?",
        fact_sheet,
    ) == "Xfinity Center"
