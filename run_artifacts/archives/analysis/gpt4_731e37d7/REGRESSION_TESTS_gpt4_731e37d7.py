"""
Regression tests for gpt4_731e37d7 money-amount-coverage-gap fix

Add these two test cases to test_longmemeval_failure_clusters.py
Location: After line 690 (after the existing hydrated_workshop_rows assertion)
"""

def test_workshop_split_turn_coverage_regression():
    """
    Regression test for gpt4_731e37d7: Event and money mentions from different 
    turns should not trigger coverage gap when amounts are sufficient.
    
    Scenario: User mentions events in one turn, amounts in another turn.
    The source-based key matching will fail, but amount heuristics should pass.
    """
    fact_sheet_split_turns = """
Aggregation worksheet:
- money_ledger={"amount": 200.0, "currency": "USD", "purpose": "workshop", "source": "It was a 2-day workshop, and I paid $200 to attend.", "verb": "paid", "date_scope": [], "location_scope": [], "month": []}
- money_ledger={"amount": 500.0, "currency": "USD", "purpose": "workshop", "source": "I paid $500 for the digital marketing workshop.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["march"]}
- money_ledger={"amount": 20.0, "currency": "USD", "purpose": "workshop", "source": "I paid $20 to attend, and got a workbook.", "verb": "paid", "date_scope": [], "location_scope": [], "month": []}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": ["november"], "month": ["november"], "source": "I attended a writing workshop in November at a literary festival"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "I attended a digital marketing workshop on March 15"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["february"], "source": "The photography workshop in February was free"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": [], "source": "I also attended a mini workshop last month"}
"""
    from orchestrator import _slot_contract_state as orchestrator_slot_contract_state
    
    state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        fact_sheet_split_turns,
    )
    
    # Assert: Should NOT be incomplete despite source key mismatch
    # Reason: 3 money entries ($200 + $500 + $20 = $720) with $720 total passes heuristic
    assert state["contract_type"] == "money_total_by_purpose", f"Unexpected contract type: {state.get('contract_type')}"
    assert state["incomplete"] is False, (
        f"Expected complete but got incomplete=True. "
        f"Reason: {state.get('reason')}. "
        f"This indicates the patch did not apply correctly or heuristic threshold is too strict."
    )


def test_workshop_minimal_money_entries_should_pass():
    """
    Regression: When we have 3+ substantial money entries ($100+ total),
    contract should pass even if event mentions are more numerous.
    
    Real-world scenario: User provides detailed event descriptions but only 
    mentions amounts for events that actually cost money (free events excluded).
    """
    fact_sheet_minimal_money = """
Aggregation worksheet:
- money_ledger={"amount": 250.0, "currency": "USD", "purpose": "workshop", "source": "I paid $250 for the first workshop.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["january"]}
- money_ledger={"amount": 150.0, "currency": "USD", "purpose": "workshop", "source": "Second workshop cost $150.", "verb": "cost", "date_scope": [], "location_scope": [], "month": ["february"]}
- money_ledger={"amount": 100.0, "currency": "USD", "purpose": "workshop", "source": "Third workshop was $100.", "verb": "paid", "date_scope": [], "location_scope": [], "month": ["march"]}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["january"], "source": "I attended a leadership workshop in January"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["february"], "source": "I went to a design thinking workshop in February"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "I participated in an agile workshop in March"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["march"], "source": "The agile workshop had two sessions over two days"}
- event_ledger={"count": null, "days": null, "event_type": "workshop", "location": [], "month": ["april"], "source": "I registered for an upcoming workshop in April"}
"""
    from orchestrator import _slot_contract_state as orchestrator_slot_contract_state
    
    state = orchestrator_slot_contract_state(
        "How much total money did I spend on attending workshops in the last four months?",
        [],
        fact_sheet_minimal_money,
    )
    
    # Assert: 3 money entries with $500 total should satisfy contract
    assert state["contract_type"] == "money_total_by_purpose"
    assert state["incomplete"] is False, (
        f"Expected complete with 3 money entries totaling $500. "
        f"Got incomplete=True with reason: {state.get('reason')}. "
        f"Missing slots: {state.get('missing_slots')}"
    )


# ============================================================================
# Integration point: Add to test_longmemeval_failure_clusters.py
# ============================================================================
# Location: Inside main() function, after line 690:
#
#     assert any(float(row.get("amount") or 0.0) == 20.0 for row in hydrated_workshop_rows)
#     
#     # ADD HERE:
#     test_workshop_split_turn_coverage_regression()
#     test_workshop_minimal_money_entries_should_pass()
#     
#     hydrated_travel_rows = _build_event_ledger_rows(
# ============================================================================


if __name__ == "__main__":
    print("=== Running gpt4_731e37d7 regression tests ===\n")
    
    try:
        test_workshop_split_turn_coverage_regression()
        print("[PASS] test_workshop_split_turn_coverage_regression")
    except AssertionError as e:
        print(f"[FAIL] test_workshop_split_turn_coverage_regression:")
        print(f"   {e}\n")
    
    try:
        test_workshop_minimal_money_entries_should_pass()
        print("[PASS] test_workshop_minimal_money_entries_should_pass")
    except AssertionError as e:
        print(f"[FAIL] test_workshop_minimal_money_entries_should_pass:")
        print(f"   {e}\n")
    
    print("\n=== Regression test suite completed ===")
