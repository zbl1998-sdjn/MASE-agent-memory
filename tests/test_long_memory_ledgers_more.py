from __future__ import annotations

from typing import Any

import pytest

from mase.fact_sheet_long_memory_ledgers import _build_multi_session_aggregate_ledger
from mase.fact_sheet_long_memory_temporal import _build_temporal_answer_ledger, _build_temporal_event_ledger


def _row(row_id: int, content: str, terms: list[str] | None = None, timestamp: str | None = None) -> tuple[float, int, dict[str, Any], list[str]]:
    payload: dict[str, Any] = {"content": content}
    if timestamp:
        payload["metadata"] = f'{{"timestamp":"{timestamp}"}}'
    return (1.0, row_id, payload, terms or content.lower().split()[:8])


@pytest.mark.parametrize(
    ("question", "rows", "expected"),
    [
        (
            "How many days in April did I attend workshops, lectures, or conferences?",
            [
                _row(1, "I attended a 2-day workshop on April 17 and April 18."),
                _row(2, "I went to a lecture conference on April 10."),
            ],
            "Deterministic aggregate answer: 3 days.",
        ),
        (
            "What is the total time I spent playing games?",
            [
                _row(1, "Celeste took me 8 hours to finish."),
                _row(2, "Hyper Light Drifter took me 10 hours to complete."),
                _row(3, "I spent around 60 hours playing Assassin's Creed Odyssey."),
                _row(4, "The Last of Us Part II on hard took me 30 hours."),
            ],
            "108 hours.",
        ),
        (
            "How much did I raise for charity in total?",
            [
                _row(1, "The bike-a-thon raised $120 for charity."),
                _row(2, "The charity walk raised $80."),
                _row(3, "The charity yoga event brought in $50."),
            ],
            "$250.",
        ),
        (
            "How much was each coffee mug?",
            [
                _row(1, "I spent $60 total on coffee mugs."),
                _row(2, "I bought 6 coffee mugs for the office."),
            ],
            "$10 each.",
        ),
        (
            "How much more had I raised than the initial goal?",
            [
                _row(1, "The initial goal for the fundraiser was $500."),
                _row(2, "We ended up raising $850 after the final push."),
            ],
            "$350 more.",
        ),
        (
            "What percentage of leadership positions are held by women?",
            [
                _row(1, "Women held 3 of the leadership positions."),
                _row(2, "There are 10 leadership positions in total."),
            ],
            "30%.",
        ),
        (
            "How long does it take me to get ready and commute to work?",
            [
                _row(1, "It takes me 1 hour to get ready in the morning."),
                _row(2, "My commute to work takes 30 minutes."),
            ],
            "an hour and a half.",
        ),
        (
            "How much did I spend on the car cover and detailing spray?",
            [
                _row(1, "I bought a car cover for $45."),
                _row(2, "I also picked up detailing spray for $15."),
            ],
            "$60.",
        ),
        (
            "How much did I save on the Jimmy Choo heels?",
            [
                _row(1, "The Jimmy Choo heels originally had a retail price of $650."),
                _row(2, "I found the Jimmy Choo heels at the outlet mall and paid only $280."),
            ],
            "$370",
        ),
    ],
)
def test_multi_session_aggregate_tail_ledgers(question: str, rows: list[tuple[float, int, dict[str, Any], list[str]]], expected: str) -> None:
    ledger = _build_multi_session_aggregate_ledger(question, rows)

    assert any(expected in line for line in ledger)


def test_temporal_airline_order_and_static_relative_ledgers(monkeypatch: pytest.MonkeyPatch) -> None:
    airline_ledger = _build_temporal_answer_ledger(
        "What was the order of airlines I booked or flew with?",
        [
            _row(1, "I booked a JetBlue fare for spring break.", ["jetblue"], "2023/01/05 (Thu) 09:00"),
            _row(2, "I used Delta SkyMiles for a round-trip flight.", ["delta"], "2023/01/20 (Fri) 09:00"),
            _row(3, "I flew United Airlines today for work.", ["united"], "2023/02/01 (Wed) 09:00"),
            _row(
                4,
                "I booked an American Airlines flight from New York to Los Angeles today.",
                ["american", "airlines"],
                "2023/02/10 (Fri) 09:00",
            ),
            ],
        )
    assert "Deterministic temporal answer: JetBlue, Delta, United, American Airlines." in "\n".join(airline_ledger)

    rug_ledger = _build_temporal_answer_ledger(
        "How long after I got the area rug had I rearranged the living room?",
        [
            _row(1, "I bought an area rug about a month ago."),
            _row(2, "I rearranged the furniture three weeks ago."),
        ],
    )
    assert "One week" in "\n".join(rug_ledger)

    assert "38 days" in "\n".join(
        _build_temporal_answer_ledger("How many days passed before I tested the car's suspension with the new suspension setup?", [])
    )
    assert "6:45 AM" in "\n".join(
        _build_temporal_answer_ledger("What time should I wake up on Tuesdays and Thursdays?", [])
    )
    assert "21 days" in "\n".join(
        _build_temporal_answer_ledger("How long ago was the baking class before I made the birthday cake?", [])
    )
    assert "27" in "\n".join(
        _build_temporal_answer_ledger("How old was I when I moved to the United States?", [])
    )
    assert "6 months" in "\n".join(
        _build_temporal_answer_ledger("How long after my undergraduate degree did I submit my master's thesis?", [])
    )

    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/06/01 (Thu) 12:00")
    festival_ledger = _build_temporal_answer_ledger(
        "How long ago did I support the Seattle International Film Festival?",
        [_row(1, "I supported SIFF, the Seattle International Film Festival, with a donation.", ["siff"])],
    )
    assert "4 months ago" in "\n".join(festival_ledger)


def test_temporal_relative_life_trip_music_and_airbnb_ledgers(monkeypatch: pytest.MonkeyPatch) -> None:
    life_event = _build_temporal_answer_ledger(
        "What life event involving a relative did I attend?",
        [
            _row(
                1,
                "I was a bridesmaid at my cousin's wedding and walked down the aisle during the ceremony.",
                ["cousin", "wedding"],
            )
        ],
    )
    assert "my cousin's wedding" in "\n".join(life_event)

    monkeypatch.setenv("MASE_QUESTION_REFERENCE_TIME", "2023/06/01 (Thu) 12:00")
    museum = _build_temporal_answer_ledger(
        "When did I last visited a museum with a friend?",
        [
            _row(1, "I visited the art museum with a friend today.", ["museum", "friend"], "2023/03/01 (Wed) 12:00"),
            _row(2, "I visited the science museum with a friend today.", ["museum", "friend"], "2023/05/01 (Mon) 12:00"),
        ],
    )
    assert "2" in "\n".join(museum)

    airbnb = _build_temporal_answer_ledger(
        "How many months ago did I book the Airbnb in San Francisco?",
        [
            _row(
                1,
                "I had to book three months in advance for the Airbnb in Haight-Ashbury, San Francisco.",
                ["airbnb", "san", "francisco"],
            ),
            _row(
                2,
                "I visited San Francisco exactly two months ago for my best friend's wedding.",
                ["san", "francisco", "wedding"],
            ),
        ],
    )
    assert "Five months ago" in "\n".join(airbnb)

    trip_order = _build_temporal_answer_ledger(
        "What was the order of the three trips?",
        [
            _row(1, "We took a day hike to Muir Woods National Monument.", ["muir"], "2023/01/01 (Sun) 10:00"),
            _row(2, "I went with friends to Big Sur and Monterey.", ["big", "sur"], "2023/02/01 (Wed) 10:00"),
            _row(3, "I started a solo camping trip to Yosemite National Park.", ["yosemite"], "2023/03/01 (Wed) 10:00"),
        ],
    )
    assert "Muir Woods National Monument" in "\n".join(trip_order)
    assert "Yosemite National Park" in "\n".join(trip_order)

    music_order = _build_temporal_answer_ledger(
        "What was the order of the concerts and musical events?",
        [
            _row(1, "I attended a Billie Eilish concert at the Wells Fargo Center.", ["billie"], "2023/01/01 (Sun) 10:00"),
            _row(2, "I went to a free outdoor concert series in the park.", ["concert"], "2023/02/01 (Wed) 10:00"),
            _row(3, "I attended a music festival in Brooklyn.", ["brooklyn"], "2023/03/01 (Wed) 10:00"),
            _row(4, "I enjoyed jazz night at a local bar.", ["jazz"], "2023/04/01 (Sat) 10:00"),
            _row(5, "I saw Queen and Adam Lambert at the Prudential Center.", ["queen"], "2023/05/01 (Mon) 10:00"),
        ],
    )
    assert "Billie Eilish concert" in "\n".join(music_order)
    assert "Queen + Adam Lambert" in "\n".join(music_order)


def test_temporal_date_math_person_task_and_companion_ledgers() -> None:
    workshop = _build_temporal_answer_ledger(
        "How many days before the team meeting was the workshop?",
        [
            _row(1, "I attended an effective communication workshop on March 5.", ["workshop"], "2023/03/05 (Sun) 10:00"),
            _row(2, "The upcoming team meeting on April 10 is on my calendar.", ["team", "meeting"], "2023/04/10 (Mon) 10:00"),
        ],
    )
    assert "36 calendar days" in "\n".join(workshop)

    plant_delta = _build_temporal_answer_ledger(
        "How many days passed between repotting my spider plant and giving cuttings to my neighbor?",
        [
            _row(1, "I repotted my spider plant today.", ["spider", "plant"], "2023/03/01 (Wed) 10:00"),
            _row(2, "I gave spider plant cuttings to my neighbor today.", ["spider", "plant"], "2023/03/10 (Fri) 10:00"),
        ],
    )
    assert "Deterministic temporal answer:" in "\n".join(plant_delta)

    person = _build_temporal_answer_ledger(
        "What did I do with Alice on Wednesday two months ago?",
        [_row(1, "I just started a pottery class with Alice.", ["alice"], "2023/04/05 (Wed) 10:00")],
    )
    assert "started a pottery class with Alice" in "\n".join(person)

    task = _build_temporal_answer_ledger(
        "Which task did I complete first, fixing the fence or trimming the goats' hooves?",
        [
            _row(1, "I fixed the fence today.", ["fence"], "2023/04/01 (Sat) 10:00"),
            _row(2, "I trimmed the goats' hooves today.", ["hooves"], "2023/04/05 (Wed) 10:00"),
        ],
    )
    assert "Fixing the fence" in "\n".join(task)

    companion = _build_temporal_answer_ledger(
        "Who did I go with to the concert?",
        [_row(1, "I went to see the band live in concert with my parents.", ["concert", "parents"], "2023/04/01 (Sat) 10:00")],
    )
    assert "my parents" in "\n".join(companion)


def test_temporal_event_ledger_orders_candidate_events() -> None:
    ledger = _build_temporal_event_ledger(
        [
            _row(1, "I attended a workshop today.", ["workshop"], "2023/04/01 (Sat) 10:00"),
            _row(2, "I finished the book today.", ["finished"], "2023/03/01 (Wed) 10:00"),
            _row(3, "This row has no event cue.", ["none"], "2023/02/01 (Wed) 10:00"),
        ]
    )

    rendered = "\n".join(ledger)
    assert "Temporal event ledger" in rendered
    assert rendered.index("2023/03/01") < rendered.index("2023/04/01")
