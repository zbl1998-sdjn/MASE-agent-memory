from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pytest

from mase.fact_sheet_long_memory_scan import (
    _build_direct_lookup_ledger,
    _build_list_lookup_ledger,
    _build_long_memory_evidence_scan,
    _build_preference_synthesis_hints,
    _build_structured_lookup_ledger,
    _build_update_resolution_ledger,
    _extract_direct_lookup_candidate_value,
    _extract_numbered_list_item,
    _extract_ordinal_index,
    _extract_question_bound_count,
    _extract_update_candidate_value,
    _filtered_update_rows,
    _normalize_lookup_phrase,
    _normalize_numeric_token,
    _support_strength,
)
from mase.fact_sheet_long_memory_temporal import (
    _best_temporal_row_for_phrase,
    _build_generic_temporal_pair_delta_ledger,
    _build_generic_temporal_relative_ledger,
    _build_temporal_answer_ledger,
    _extract_event_date_from_text,
    _extract_three_event_phrases,
    _format_temporal_elapsed_answer,
    _months_between,
    _parse_long_memory_date,
    _parse_small_number_phrase,
    _temporal_duration_label,
    _temporal_phrase_markers,
)
from mase.fact_sheet_long_memory_terms import (
    _is_update_semantic_question,
    _long_memory_evidence_terms,
)


def _row(
    row_id: int,
    content: str,
    terms: list[str] | None = None,
    timestamp: str | None = None,
) -> tuple[float, int, dict[str, Any], list[str]]:
    payload: dict[str, Any] = {"id": row_id, "content": content}
    if timestamp:
        payload["metadata"] = {"timestamp": timestamp}
    return (1.0, row_id, payload, terms or content.lower().split()[:8])


def _joined(lines: list[str]) -> str:
    return "\n".join(lines)


def test_long_memory_terms_cover_fallback_and_domain_expansions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "mase_tools.legacy", None)
    fallback_terms = _long_memory_evidence_terms("Which bike and current role changed?")
    assert {"bike", "current role", "road bike"}.issubset(set(fallback_terms))

    question = " ".join(
        [
            "jogging and yoga health-related devices faith-related activities markets earned money",
            "music albums EPs formal education average age department Alex was born Sephora current role",
            "Rachel gets married clinic on Monday airport to my hotel taxi page count novels",
            "spent playing games in total workshops lectures conferences April charity fundraiser coffee mug each",
            "model kit doctor visit movie festival leadership positions women get ready commute to work",
            "car cover camping trip bike-related expenses social media break accommodations per night Hawaii Tokyo",
            "workshops spent total money museum of modern art recommend accessories phone camera gear publications",
            "conferences hotel Miami cultural events battery life phone rearranging the furniture bedroom theme park",
            "activities commute to work furniture art-related dinner parties Jimmy Choo fitness classes days a week",
            "kitchen item rollercoaster July to October graduation ceremony past three months instagram followers",
            "favorite author discount older am I graduated from college fun run work commitments which bike",
            "streaming service business milestone competition what did I buy museum two months ago",
            "order from first to last nursery baby shower gardening-related activity networking event",
            "art-related event plankchallenge vegan chili religious activity sunday mass ash wednesday",
            "last friday artist life event relative charity events consecutive exchange program orientation",
            "kitchen appliance book finish book the airbnb in san francisco recovered from the flu jog",
            "graduation ceremony birthday gift valentine airline last saturday from whom sports events participated",
            "stand-up comedy open mic necklace for my sister photo album for my mom order of airlines",
            "area rug rearranged became a parent first Tom Alex Seattle International Film Festival",
            "car's suspension new suspension setup Tuesdays and Thursdays wake baking class birthday cake",
            "how old moved to the United States undergraduate degree master's thesis",
        ]
    )

    terms = set(_long_memory_evidence_terms(question))

    expected = {
        "jogging",
        "fitbit",
        "food drive",
        "homemade jam",
        "happier than ever",
        "high school",
        "average age",
        "sephora",
        "airport",
        "the last of us part ii",
        "lecture on sustainable development",
        "charity cycling",
        "coffee mug",
        "model kit",
        "primary care physician",
        "film festival",
        "leadership positions",
        "commute to work",
        "car cover",
        "yellowstone national park",
        "bike-related expenses",
        "social media break",
        "hawaii",
        "digital marketing workshop",
        "museum of modern art",
        "wireless charger",
        "tripod",
        "deep learning",
        "ocean view",
        "language skills",
        "battery-saving",
        "bedroom dresser",
        "thrill rides",
        "podcasts",
        "bookshelf",
        "art event",
        "dinner party",
        "jimmy choo",
        "weightlifting",
        "kitchen faucet",
        "mako",
        "instagram",
        "favorite author",
        "berkeley",
        "road bike",
        "disney+",
        "first client",
        "sculpting tools",
        "natural history museum",
        "prepare the nursery",
        "tomato saplings",
        "networking event",
        "metropolitan museum of art",
        "#plankchallenge",
        "episcopal church",
        "sunday mass",
        "bluegrass band",
        "cousin's wedding",
        "24-hour bike ride",
        "pre-departure orientation",
        "smoker",
        "the nightingale",
        "haight-ashbury",
        "recovered from the flu",
        "wireless headphone",
        "american airlines flight",
        "from my aunt",
        "spring sprint triathlon",
        "open mic night",
        "necklace from tiffany's",
        "jetblue",
        "area rug",
        "adopted a baby girl",
        "siff",
        "suspension settings",
        "7:00 am",
        "baking class",
        "living in the united states",
        "submitted my master's thesis",
    }
    assert expected.issubset(terms)


def test_scan_update_lookup_helpers_cover_extraction_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASE_QTYPE", "single-session-preference")
    assert "Preference synthesis rule:" in _build_preference_synthesis_hints("Can you recommend phone accessories?")[0]
    assert _build_preference_synthesis_hints("What did I buy?") == []

    strong = _row(1, "I currently use the new zoom lens.", ["currently", "zoom lens", "latest"])
    weak = _row(2, "I mentioned lens once.", ["lens"])
    assert _support_strength(strong) > _support_strength(weak)
    assert _filtered_update_rows([weak, strong]) == [strong]

    assert _normalize_lookup_phrase("a yarn store Assistant:") == "the yarn store"
    assert _normalize_numeric_token("fourth") == "4"
    assert _extract_question_bound_count("How many shirts did I pack?", "I packed four shirts and two jackets.") == "4"
    assert _extract_ordinal_index("What was the 2nd item?") == 2
    assert _extract_ordinal_index("What was the third item?") == 3
    assert _extract_numbered_list_item("1. Alpha 2. Beta option 3. Gamma", 2) == "Beta option"

    update_cases = [
        ("How often do I practice?", "I practice 2 times a week now.", "2 times a week."),
        ("What time was my race?", "My latest race time was 25 minutes and 40 seconds.", "25 minutes and 40 seconds"),
        ("What time is the meeting?", "The meeting is at 7:30 tomorrow.", "7:30"),
        ("What amount was I pre-approved for?", "The bank pre-approved me for $ 450,000.", "$450,000"),
        ("What day of the week was the clinic?", "The clinic appointment is Tuesday.", "Tuesday"),
        ("What is my latest lens?", "I bought my new 24-70mm zoom lens yesterday.", "a 24-70mm zoom lens"),
        ("How many shirts did I pack?", "I packed four shirts and one jacket.", "4"),
        ("Where did I move?", "I moved to the suburbs last month.", "the suburbs"),
        ("Is it the same method?", "This is the same method I used before.", "Yes."),
        ("Did the method stay the same?", "I stopped using it and picked a different method.", "No."),
    ]
    for question, content, expected in update_cases:
        assert _extract_update_candidate_value(question, {"content": content}) == expected


@pytest.mark.parametrize(
    ("question", "content", "expected"),
    [
        (
            "Where did I study abroad?",
            "I joined a study abroad program at the University of Sydney. It was in Australia.",
            "University of Sydney in Australia",
        ),
        ("What cocktail did I try last weekend?", "I tried a mezcal negroni recipe last weekend.", "mezcal negroni"),
        ("How long was I in Lisbon?", "I spent two weeks in Lisbon for the residency.", "two weeks"),
        ("What discount did I get?", "The bookstore offered a 25% discount.", "25%"),
        ("How many shirts did I pack?", "I packed four shirts for the trip.", "4"),
        ("What game did I beat last weekend?", "I beat the final boss in the Phantom Liberty DLC.", "Phantom Liberty DLC"),
        ("Which powwow dance had skilled dancers?", "The hoop dance had skilled dancers.", "Hoop Dance"),
        ("What was the fifth bottle in the gin-based list?", "5. Elderflower Collins: bright and gin-based.", "Elderflower Collins"),
        ("What was the influencer marketing budget for DHL Wellness Retreats?", "Influencer marketing: $12,000.", "$12,000"),
        (
            "What Instagram handle was UK-based and used unusual gemstones?",
            "Mira Stone (@mira\\_gems): UK-based maker using unusual gemstones.",
            "@mira_gems",
        ),
        (
            "Which online store based in India used those supplies?",
            "RangRiwaaz - based in India with traditional Indian fabrics, threads, and embellishments.",
            "RangRiwaaz",
        ),
        ("What year did the house began construction?", "The construction of the house began in 1890.", "1890."),
        (
            "What were the three objectives in the endometrial cancer study?",
            "The paper listed objectives: classify tumors, study outcomes, and build biomarkers.",
            "three objectives",
        ),
        (
            "Which Soviet cartoon mocked Western culture?",
            "The popular Soviet cartoon, 'Nu Pogodi' which mocked Western culture, came up.",
            "Nu Pogodi",
        ),
        ("What type of beer did you recommend for the recipe?", "Use a Pilsner or Lager in the recipe.", "Pilsner"),
        ("How many Music and Medicine subjects were there?", "Music and Medicine enrolled 128 subjects.", "128 subjects"),
        (
            "Which dessert shop in Orlando had giant milkshakes?",
            "Sugar Factory - located at ICON Park and known for giant milkshakes.",
            "Sugar Factory at ICON Park.",
        ),
        ("Where can I redeem the coupon?", "Many retailers, like Target, redeem coupons for coffee creamer.", "Target"),
        ("Where did I meet Leo?", "For Leo, it was outside the library.", "outside the library"),
        ("When was the event?", "The event happened on March 7th.", "March 7th"),
        ("When was Valentine's Day?", "We planned it for Valentine's Day.", "February 14th"),
        ("What color was the Plesiosaur?", "The Plesiosaur exhibit has a green scaly body.", "green scaly body"),
        ("What was my previous occupation?", "I worked as an ICU nurse before switching.", "ICU nurse"),
        ("How many subjects were in the study?", "The trial included 42 subjects.", "42 subjects"),
    ],
)
def test_direct_lookup_candidate_value_covers_specialized_patterns(question: str, content: str, expected: str) -> None:
    assert expected in _extract_direct_lookup_candidate_value(question, {"content": content})


def test_scan_ledgers_cover_structured_list_direct_update_and_full_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    table_ledger = _joined(
        _build_structured_lookup_ledger(
            "What shift was Alice assigned on Monday rotation sheet?",
            [
                _row(
                    1,
                    "| | Morning | Midday | Night | Backup |\n| Monday | Alice | Bob | Cara | Dan |",
                    ["monday", "alice", "rotation"],
                )
            ],
        )
    )
    assert "Alice was assigned to the Morning" in table_ledger

    list_ledger = _joined(
        _build_list_lookup_ledger(
            "What was the second item in the list of travel options?",
            [_row(1, "Assistant: Options list: 1. Train 2. Overnight bus 3. Ferry", ["list", "travel"])],
        )
    )
    assert "Overnight bus" in list_ledger

    direct_ledger = _joined(
        _build_direct_lookup_ledger(
            "When was the event?",
            [_row(1, "The event happened on April 11th.", ["event", "april"])],
        )
    )
    assert "deterministic_answer=April 11th" in direct_ledger

    monkeypatch.setenv("MASE_QTYPE", "knowledge-update")
    update_rows = [
        _row(1, "When I started, I led 3 engineers.", ["engineers", "initial", "started"], "2023/01/01 (Sun) 10:00"),
        _row(2, "For a while, I led 5 engineers.", ["engineers", "history", "middle"], "2023/02/01 (Wed) 10:00"),
        _row(3, "Now I lead 8 engineers.", ["engineers", "now", "latest", "current"], "2023/03/01 (Wed) 10:00"),
    ]
    both = _joined(
        _build_update_resolution_ledger(
            "What was my initial team size and how many engineers do I lead now?",
            update_rows,
        )
    )
    assert "Initially, it was 3. Now, it is 8." in both

    initial = _joined(_build_update_resolution_ledger("What was my initial team size?", update_rows))
    assert "earliest supported row" in initial
    assert "middle history row" in initial

    monkeypatch.setenv("MASE_LOCAL_ONLY", "1")
    scan = _joined(
        _build_long_memory_evidence_scan(
            "Which bike did I ride this past weekend?",
            [
                {
                    "id": 1,
                    "content": "User: I did a maintenance check on my road bike and adjusted the brakes last weekend.",
                    "metadata": {"timestamp": "2023/04/01 (Sat) 10:00"},
                },
                {
                    "id": 2,
                    "content": "User: I fixed my mountain bike a few weeks ago.",
                    "metadata": {"timestamp": "2023/03/01 (Wed) 10:00"},
                },
            ],
        )
    )
    assert "Question-focused evidence scan" in scan
    assert "Deterministic temporal answer: road bike." in scan


def test_temporal_low_level_helpers_cover_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _parse_long_memory_date("") is None
    assert _parse_long_memory_date("2023/99/99") is None
    assert _parse_small_number_phrase("7") == 7
    assert _parse_small_number_phrase("thirteen") is None
    assert _months_between(datetime(2023, 6, 1), datetime(2023, 4, 2)) == 1
    assert _temporal_phrase_markers('Visited "Ancient Civilizations" at MoMA (VIP)') == [
        "ancient civilizations",
        "moma",
        "vip",
    ]
    assert _extract_three_event_phrases("'Alpha', 'Beta', and 'Gamma'?") == ["Alpha", "Beta", "Gamma"]
    assert _extract_three_event_phrases(
        "What is the order of the three events: the day I booked, the day I flew, and the day I returned?"
    ) == ["the day I booked", "the day I flew", "the day I returned"]
    assert _best_temporal_row_for_phrase("", []) is None

    rows = [_row(1, "I adopted a puppy today.", ["adopted", "puppy"], "2023/05/01 (Mon) 10:00")]
    anchor = _best_temporal_row_for_phrase("adopted a puppy", rows)
    assert anchor is not None
    assert anchor[0] == datetime(2023, 5, 1)

    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/05/11 (Thu) 10:00")
    relative = _joined(_build_generic_temporal_relative_ledger("How many days ago did I adopted a puppy?", rows))
    assert "10 days" in relative

    pair_rows = [
        _row(1, "I started pottery class on March 1.", ["started", "pottery"], "2023/03/01 (Wed) 10:00"),
        _row(2, "I sold my first bowl on March 22.", ["sold", "bowl"], "2023/03/22 (Wed) 10:00"),
    ]
    pair = _joined(
        _build_generic_temporal_pair_delta_ledger(
            "How many weeks passed since I started pottery class when I sold my first bowl?",
            pair_rows,
        )
    )
    assert "3 weeks" in pair

    assert _extract_event_date_from_text("It happened on February 31.", datetime(2023, 1, 1)) == datetime(2023, 1, 1)
    assert _extract_event_date_from_text("It happened on 4/3.", datetime(2023, 1, 1)) == datetime(2023, 4, 3)
    assert _temporal_duration_label(14) == "2 weeks"
    assert _format_temporal_elapsed_answer("months", 61, ago=False) == "2 months"
    assert _is_update_semantic_question("what is the latest amount?") is True


def test_temporal_low_level_helpers_cover_empty_and_relative_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _temporal_phrase_markers("'Alpha' \"Beta\" (VIP)") == ["alpha", "beta", "vip"]
    assert _best_temporal_row_for_phrase(
        "concert",
        [_row(1, "", ["concert"]), _row(2, "Unrelated gardening note.", ["garden"])],
    ) is None

    monkeypatch.delenv("MASE_QUESTION_REFERENCE_TIME", raising=False)
    assert _build_generic_temporal_relative_ledger("How many days ago did I adopted a puppy?", []) == []
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/06/03 (Sat) 10:00")
    rows = [_row(1, "I adopted a puppy today.", ["adopted", "puppy"], "2023/03/02 (Thu) 10:00")]
    months = _joined(_build_generic_temporal_relative_ledger("How many months ago did I adopted a puppy?", rows))
    assert "3 months ago" in months

    assert _build_generic_temporal_pair_delta_ledger("How long between alpha and beta?", []) == []
    base = datetime(2023, 1, 15)
    assert _extract_event_date_from_text("It happened on 13/40.", base) == base
    assert _extract_event_date_from_text("I went last week.", base) == datetime(2023, 1, 8)
    assert _format_temporal_elapsed_answer("months", 65, ago=True) == "2 months ago"


@pytest.mark.parametrize(
    ("question", "rows", "expected"),
    [
        (
            "Which streaming service did I try most recently?",
            [
                _row(1, "I used Netflix a few months ago.", ["netflix"], "2023/01/01 (Sun) 10:00"),
                _row(2, "I started a Disney+ free trial last month.", ["disney+"], "2023/03/01 (Wed) 10:00"),
            ],
            "Disney+",
        ),
        (
            "What business milestone did I hit?",
            [_row(1, "I signed a contract with my first client today.", ["first", "client"])],
            "first client",
        ),
        (
            "After the competition, what did I buy?",
            [_row(1, "After the art competition, I got my own set of sculpting tools.", ["sculpting", "tools"])],
            "sculpting tools",
        ),
        (
            "How many weeks after starting sculpting classes did I get sculpting tools?",
            [
                _row(1, "I started taking sculpting classes today.", ["sculpting"], "2023/03/01 (Wed) 10:00"),
                _row(2, "I got my own set of sculpting tools today.", ["sculpting", "tools"], "2023/03/22 (Wed) 10:00"),
            ],
            "Deterministic temporal answer: 3",
        ),
        (
            "Which gardening-related activity did I do two weeks ago?",
            [_row(1, "I planted 12 new tomato saplings today.", ["tomato", "saplings"])],
            "planting 12 new tomato saplings",
        ),
        (
            "Where was the art-related event?",
            [_row(1, "I attended the Ancient Civilizations exhibit at the Metropolitan Museum of Art.", ["art", "event"])],
            "The Metropolitan Museum of Art",
        ),
        (
            "Which came first, #PlankChallenge or vegan chili?",
            [
                _row(1, "I posted a vegan chili recipe on Instagram with #FoodieAdventures.", ["vegan"], "2023/03/01 (Wed)"),
                _row(2, "I joined the #PlankChallenge on Instagram.", ["plankchallenge"], "2023/03/10 (Fri)"),
            ],
            "vegan chili",
        ),
        (
            "Where was the religious activity?",
            [_row(1, "I attended Maundy Thursday service at the Episcopal Church.", ["religious", "church"])],
            "the Episcopal Church",
        ),
        (
            "Which artist did I listen to last Friday?",
            [_row(1, "I started enjoying a bluegrass band with a banjo player.", ["bluegrass", "banjo"])],
            "bluegrass band",
        ),
        (
            "What kitchen appliance did I get 10 days ago?",
            [_row(1, "I got a smoker and BBQ sauce for the patio.", ["smoker"])],
            "a smoker",
        ),
        (
            "Which book did I finish?",
            [_row(1, 'I just finished "The Nightingale" by Kristin Hannah.', ["nightingale", "kristin"])],
            "The Nightingale",
        ),
        (
            "How many days did it take me to finish The Nightingale?",
            [
                _row(1, 'I started "The Nightingale" by Kristin Hannah today.', ["nightingale"], "2023/03/01 (Wed)"),
                _row(2, 'I finished "The Nightingale" by Kristin Hannah today.', ["nightingale"], "2023/03/12 (Sun)"),
            ],
            "11 days",
        ),
        (
            "How many days between recovered from the flu and my 10th jog outdoors?",
            [
                _row(1, "I recovered from the flu today.", ["flu"], "2023/03/01 (Wed)"),
                _row(2, "I completed my 10th jog outdoors today.", ["jog"], "2023/03/16 (Thu)"),
            ],
            "Deterministic temporal answer: 15",
        ),
        (
            "What airline did I fly on Valentine?",
            [_row(1, "I was recovering from my American Airlines flight today.", ["airline"], "2023/02/14 (Tue)")],
            "American Airlines",
        ),
        (
            "Who became a parent first, Tom or Alex?",
            [_row(1, "Alex just adopted a baby girl from China in January.", ["alex", "baby"])],
            "didn't mention anything about Tom",
        ),
        (
            "How long had I been a member of 'Book Lovers' before the meetup?",
            [
                _row(1, "I joined Book Lovers today.", ["book", "lovers"], "2023/03/01 (Wed)"),
                _row(2, "I attended a Book Lovers meetup today.", ["book", "meetup"], "2023/03/15 (Wed)"),
            ],
            "2 weeks",
        ),
        (
            "Who did I go with to the music event?",
            [_row(1, "I went to see a live concert with my friend Maya.", ["concert", "friend"])],
            "friend Maya",
        ),
        (
            "How many days ago was the networking event?",
            [_row(1, "I went to a networking event for designers.", ["networking", "event"], "2023/04/01 (Sat)")],
            "15 days",
        ),
        (
            "How long ago was Seattle International Film Festival?",
            [_row(1, "I attended SIFF, the Seattle International Film Festival.", ["siff"], "2023/01/01 (Sun)")],
            "4 months ago",
        ),
        (
            "What life event involving a relative did I mention?",
            [_row(1, "I was a bridesmaid at my cousin's wedding ceremony.", ["cousin", "wedding"])],
            "my cousin's wedding",
        ),
        (
            "What did I do with Sarah?",
            [_row(1, "I just started pottery class with my friend Sarah.", ["pottery", "sarah"])],
            "started pottery class with my friend Sarah",
        ),
        (
            "Who did I go with to the music event?",
            [_row(1, "I went to see a jazz concert with my parents.", ["jazz", "parents"])],
            "my parents",
        ),
    ],
)
def test_temporal_answer_ledger_covers_relative_event_branches(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    rows: list[tuple[float, int, dict[str, Any], list[str]]],
    expected: str,
) -> None:
    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/04/16 (Sun) 10:00")
    assert expected in _joined(_build_temporal_answer_ledger(question, rows))
