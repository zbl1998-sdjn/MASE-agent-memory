from __future__ import annotations

from mase_tools.legacy import assess_evidence_chain


def _result(*, summary: str = "", user_query: str = "", assistant_response: str = "") -> dict[str, str]:
    return {
        "summary": summary,
        "user_query": user_query,
        "assistant_response": assistant_response,
        "date": "2026-04-14",
        "time": "00:00:00",
        "thread_label": "focus-test",
    }


def main() -> None:
    hamster_assessment = assess_evidence_chain(
        "What is the name of my hamster?",
        [
            _result(
                user_query="By the way, my cat's name is Luna.",
                assistant_response="Luna is a sweet cat and loves sitting by the window.",
            )
        ],
    )
    assert hamster_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in hamster_assessment["reason_codes"]
    assert "missing_hamster" in hamster_assessment["reason_codes"]

    vintage_assessment = assess_evidence_chain(
        "How long have I been collecting vintage films?",
        [
            _result(
                user_query="I've been collecting vintage cameras for three months now.",
                assistant_response="My vintage camera collection has grown quickly in three months.",
            )
        ],
    )
    assert vintage_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in vintage_assessment["reason_codes"]
    assert "missing_vintage_films" in vintage_assessment["reason_codes"]

    uncle_assessment = assess_evidence_chain(
        "What did I bake for my uncle's birthday party?",
        [
            _result(
                user_query="I recently made a lemon blueberry cake for my niece's birthday party.",
                assistant_response="The lemon blueberry cake for my niece was a huge hit.",
            )
        ],
    )
    assert uncle_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in uncle_assessment["reason_codes"]
    assert "missing_uncle" in uncle_assessment["reason_codes"]

    violin_assessment = assess_evidence_chain(
        "How much time do I dedicate to practicing violin every day?",
        [
            _result(
                user_query="I practice guitar for 30 minutes every day.",
                assistant_response="Daily guitar practice for 30 minutes has helped my rhythm.",
            )
        ],
    )
    assert violin_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in violin_assessment["reason_codes"]
    assert "missing_violin" in violin_assessment["reason_codes"]

    violin_underfire_assessment = assess_evidence_chain(
        "How much time do I dedicate to practicing violin every day?",
        [
            _result(
                user_query="Every other Thursday I spend 45 minutes on warmups before dinner.",
                assistant_response="That 45-minute routine has become part of my weekly rhythm.",
            )
        ],
    )
    assert violin_underfire_assessment["verifier_action"] == "refuse"
    assert "unsupported_relation" in violin_underfire_assessment["reason_codes"]
    assert "missing_violin" in violin_underfire_assessment["reason_codes"]

    doctor_assessment = assess_evidence_chain(
        "When did I see Dr. Johnson?",
        [
            _result(
                user_query="I saw Dr. Smith last Tuesday for a follow-up appointment.",
                assistant_response="Dr. Smith said the recovery is going well.",
            )
        ],
    )
    assert doctor_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in doctor_assessment["reason_codes"]
    assert "doctor_name" in doctor_assessment["reason_codes"]

    apartment_assessment = assess_evidence_chain(
        "When did I book the Airbnb in Sacramento?",
        [
            _result(
                user_query="I booked the Airbnb in San Francisco on March 5 for the conference weekend.",
                assistant_response="The San Francisco booking is confirmed for that weekend.",
            )
        ],
    )
    assert apartment_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in apartment_assessment["reason_codes"]
    assert "location" in apartment_assessment["reason_codes"]

    korea_duration_assessment = assess_evidence_chain(
        "How long was I in Korea for?",
        [
            _result(
                user_query="I'm actually thinking of visiting South Korea.",
                assistant_response="Seoul's subway system is efficient, and you can reach most attractions within 30 minutes.",
            )
        ],
    )
    assert korea_duration_assessment["verifier_action"] == "refuse"
    assert any(code in korea_duration_assessment["reason_codes"] for code in ("missing_anchor", "unsupported_relation"))

    tank_assessment = assess_evidence_chain(
        "How many fish are there in my 30-gallon tank?",
        [
            _result(
                user_query="I'm thinking of adding some live plants to my new 20-gallon tank, which currently has 10 neon tetras, 5 golden honey gouramis, and a small pleco catfish.",
                assistant_response="A 20-gallon tank can be a bit small for multiple species.",
            )
        ],
    )
    assert tank_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in tank_assessment["reason_codes"]

    google_job_assessment = assess_evidence_chain(
        "How long have I been working before I started my current job at Google?",
        [
            _result(
                user_query="I'm trying to free up some space on my phone and maybe use Google Drive.",
                assistant_response="Google Drive offers 15GB of free storage, and the 12 Days of Deals sale on Amazon is live now.",
            )
        ],
    )
    assert google_job_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in google_job_assessment["reason_codes"]

    paired_target_assessment = assess_evidence_chain(
        "How many plants did I initially plant for tomatoes and chili peppers?",
        [
            _result(
                user_query="I planted 5 tomato plants initially, and they've been producing like crazy.",
                assistant_response="My tomato plants are thriving this season.",
            )
        ],
    )
    assert paired_target_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in paired_target_assessment["reason_codes"]

    egg_tart_assessment = assess_evidence_chain(
        "How many times did I bake egg tarts in the past two weeks?",
        [
            _result(
                user_query="I started going to the gym three times a week.",
                assistant_response="That routine has improved my energy levels.",
            )
        ],
    )
    assert egg_tart_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in egg_tart_assessment["reason_codes"]

    ipad_case_assessment = assess_evidence_chain(
        "How many days did it take for my iPad case to arrive after I bought it?",
        [
            _result(
                user_query="I got a notification from Amazon about their 12 Days of Deals sale.",
                assistant_response="The sale lasts 12 days.",
            )
        ],
    )
    assert ipad_case_assessment["verifier_action"] == "refuse"
    assert "missing_anchor" in ipad_case_assessment["reason_codes"]

    museum_assessment = assess_evidence_chain(
        "How many different museums or galleries did I visit in December?",
        [
            _result(
                user_query="Do you know if there are any art galleries or museums that feature abstract art in December?",
                assistant_response="Can you suggest any local art museums or galleries that offer workshops or classes?",
            ),
            _result(
                user_query="I want more art inspiration this month.",
                assistant_response="Museums and galleries are great places to learn about abstract art.",
            ),
        ],
    )
    assert museum_assessment["verifier_action"] == "refuse"
    assert "unsupported_relation" in museum_assessment["reason_codes"]
    assert "museum_gallery_visit_missing" in museum_assessment["reason_codes"]

    italian_restaurant_assessment = assess_evidence_chain(
        "How many Italian restaurants have I tried in my city?",
        [
            _result(
                user_query="I've tried 3 Korean restaurants in my city this spring.",
                assistant_response="Those Korean restaurants have become my favorite local spots.",
            )
        ],
    )
    assert italian_restaurant_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in italian_restaurant_assessment["reason_codes"]
    assert "missing_italian" in italian_restaurant_assessment["reason_codes"]

    football_collection_assessment = assess_evidence_chain(
        "How many autographed football have I added to my collection in the first three months of collection?",
        [
            _result(
                user_query="I added 20 autographed baseball to my collection in the first three months.",
                assistant_response="That baseball collection grew quickly in the first quarter.",
            )
        ],
    )
    assert football_collection_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in football_collection_assessment["reason_codes"]
    assert "missing_football" in football_collection_assessment["reason_codes"]

    shinjuku_apartment_assessment = assess_evidence_chain(
        "How long have I been living in my current apartment in Shinjuku?",
        [
            _result(
                user_query="I've been living in my current apartment in Harajuku for 1 hour from the station.",
                assistant_response="The Harajuku apartment has been convenient for getting around Tokyo.",
            )
        ],
    )
    assert shinjuku_apartment_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in shinjuku_apartment_assessment["reason_codes"]
    assert "missing_shinjuku" in shinjuku_apartment_assessment["reason_codes"]

    table_tennis_assessment = assess_evidence_chain(
        "How often do I play table tennis with my friends at the local park?",
        [
            _result(
                user_query="I play tennis with my friends at the local park every weekend.",
                assistant_response="Those tennis games at the park have become part of our routine.",
            )
        ],
    )
    assert table_tennis_assessment["verifier_action"] == "refuse"
    assert "relation_mismatch" in table_tennis_assessment["reason_codes"]
    assert "missing_table_tennis" in table_tennis_assessment["reason_codes"]

    supported_name = assess_evidence_chain(
        "What is the name of my cat?",
        [
            _result(
                user_query="My cat's name is Luna.",
                assistant_response="Luna is a calm cat.",
            )
        ],
    )
    assert "relation_mismatch" not in supported_name["reason_codes"]
    assert "missing_anchor" not in supported_name["reason_codes"]

    supported_violin = assess_evidence_chain(
        "How much time do I dedicate to practicing violin every day?",
        [
            _result(
                user_query="I practice violin for 45 minutes every day.",
                assistant_response="My daily violin practice lasts 45 minutes.",
            )
        ],
    )
    assert supported_violin["verifier_action"] in {"pass", "verify"}

    print("abstention pre-gate focus tests passed")


if __name__ == "__main__":
    main()
