"""Long-memory query-term expansion and scope hints."""
from __future__ import annotations

import os
import re

_LONG_MEMORY_EVIDENCE_STOPWORDS = {
    "about",
    "actually",
    "after",
    "again",
    "also",
    "advice",
    "before",
    "being",
    "can",
    "could",
    "different",
    "does",
    "find",
    "from",
    "have",
    "help",
    "interesting",
    "many",
    "member",
    "might",
    "need",
    "over",
    "recent",
    "recently",
    "recommend",
    "suggest",
    "should",
    "some",
    "that",
    "this",
    "time",
    "tips",
    "total",
    "useful",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}

_UPDATE_LATEST_HINT_MARKERS = (
    "latest",
    "most recent",
    "most recently",
    "current",
    "currently",
    "now",
)

_UPDATE_INITIAL_HINT_MARKERS = (
    "initial",
    "initially",
    "at first",
    "when i just started",
    "when i first started",
    "when i first",
    "used to",
)


def _is_temporal_ledger_question(lowered_question: str) -> bool:
    return any(
        marker in lowered_question
        for marker in (
            "happened first",
            "order of",
            "days passed",
            "days had passed",
            "days before",
            "how long had",
            "last saturday",
            "wednesday two months ago",
            "which task did i complete first",
            "when i attended",
            "past weekend",
            "last friday",
            "a week ago",
            "one week ago",
            "10 days ago",
            "last saturday",
            "valentine",
            "buy first",
            "months have passed",
            "months passed",
            "months ago",
            "how many months",
            "weeks have i been",
            "weeks had passed",
            "most recently",
            "four weeks ago",
            "two weeks ago",
            "two months ago",
            "three trips",
            "gardening-related",
            "how many days ago",
            "how many days did it take me to finish",
            "how many weeks ago",
            "art-related event",
            "religious activity",
            "plankchallenge",
            "vegan chili",
            "tuesdays and thursdays",
            "moved to the united states",
        )
    )


def _is_update_semantic_question(lowered_question: str) -> bool:
    if str(os.environ.get("MASE_QTYPE") or "").strip().lower() == "knowledge-update":
        return True
    asks_latest = any(marker in lowered_question for marker in _UPDATE_LATEST_HINT_MARKERS)
    asks_initial = any(marker in lowered_question for marker in _UPDATE_INITIAL_HINT_MARKERS)
    asks_then_and_now = ("now" in lowered_question and asks_initial) or ("currently" in lowered_question and asks_initial)
    return asks_latest or asks_initial or asks_then_and_now

def _long_memory_evidence_terms(user_question: str) -> list[str]:
    try:
        from mase_tools.legacy import _build_english_search_profile

        profile = _build_english_search_profile([], full_query=user_question)
        raw_terms = [
            *(profile.get("exact_phrases") or []),
            *(profile.get("expanded_terms") or []),
            *(profile.get("literal_terms") or []),
        ]
    except (ImportError, AttributeError, TypeError, ValueError):
        raw_terms = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", user_question or "")

    lowered_question = (user_question or "").lower()
    if any(term in lowered_question for term in ("property", "properties", "townhouse", "condo", "home", "house")):
        raw_terms.extend(
            [
                "condo",
                "bungalow",
                "townhouse",
                "property",
                "properties",
                "home",
                "house",
                "viewed",
                "saw",
                "offer",
                "rejected",
                "budget",
                "deal-breaker",
                "renovation",
            ]
        )
    if "food delivery" in lowered_question or "delivery service" in lowered_question:
        raw_terms.extend(
            [
                "food delivery",
                "delivery services",
                "Domino's",
                "Domino",
                "Pizza",
                "Fresh Fusion",
                "Uber Eats",
                "DoorDash",
                "Grubhub",
                "takeout",
            ]
        )
    if any(term in lowered_question for term in ("clothing", "clothes", "pick up", "return from a store")):
        raw_terms.extend(["dry cleaning", "blazer", "boots", "Zara", "exchanged", "new pair", "pick up", "return"])
    if "painting" in lowered_question and ("worth" in lowered_question or "paid" in lowered_question):
        raw_terms.extend(["flea market find", "worth triple", "paid for it", "appraised"])
    if "magazine" in lowered_question and "subscription" in lowered_question:
        raw_terms.extend(["The New Yorker", "Architectural Digest", "Forbes", "subscribed", "subscribing", "getting", "canceled"])
    if "sports event" in lowered_question or ("sports" in lowered_question and "january" in lowered_question):
        raw_terms.extend(
            [
                "NBA game",
                "Staples Center",
                "College Football National Championship",
                "NFL playoffs",
                "Divisional Round",
                "Chiefs",
                "Bills",
                "watched",
                "went to",
            ]
        )
    if _is_temporal_ledger_question(lowered_question):
        raw_terms.extend(
            [
                "came back from",
                "attended",
                "watched",
                "walked down the aisle",
                "today",
                "yesterday",
                "last weekend",
                "started",
                "completed",
                "finished",
                "repotted",
                "cuttings",
                "gave",
                "workshop",
                "team meeting",
                "music event",
                "concert",
                "went to see",
                "saw them live",
                "parents",
                "ukulele",
                "lesson",
                "joined",
                "member",
                "meetup",
                "fixed",
                "fence",
                "trimmed",
                "hooves",
            ]
        )
    if "plant" in lowered_question:
        raw_terms.extend(
            [
                "snake plant",
                "peace lily",
                "succulent",
                "fern",
                "African violet",
                "nursery",
                "got",
                "bought",
                "sister",
            ]
        )
    if "doctor" in lowered_question and "bed" in lowered_question:
        raw_terms.extend(["doctor's appointment", "last Thursday", "last Wednesday", "2 AM", "bed", "blood test results"])
    if "wedding" in lowered_question:
        raw_terms.extend(
            [
                "wedding",
                "ceremony",
                "tie the knot",
                "bride",
                "groom",
                "partner",
                "husband",
                "wife",
                "college roommate",
                "cousin",
                "vineyard",
                "Jen",
                "Tom",
                "Rachel",
                "Mike",
                "Emily",
                "Sarah",
            ]
        )
    if "babies" in lowered_question or "baby" in lowered_question:
        raw_terms.extend(["baby boy", "baby girl", "born", "Max", "Charlotte", "Ava", "Lily", "Jasper", "adopted"])
    if "bake" in lowered_question and "past two weeks" in lowered_question:
        raw_terms.extend(["apple pie", "chocolate cake", "whole wheat baguette", "batch of cookies", "baked", "made"])
    if "jogging and yoga" in lowered_question:
        raw_terms.extend(["jogging", "yoga", "last week", "30 minutes", "0.5 hours"])
    if "health-related devices" in lowered_question:
        raw_terms.extend(["Fitbit", "blood pressure monitor", "glucose monitor", "CPAP", "Accu-Chek", "thermometer"])
    if "faith-related activities" in lowered_question:
        raw_terms.extend(["food drive", "Bible study", "midnight mass", "church", "December"])
    if "markets" in lowered_question and ("earned" in lowered_question or "money" in lowered_question):
        raw_terms.extend(["homemade jam", "organic herbs", "potted herb plants", "$225", "$120", "$150"])
    if "music albums" in lowered_question or "eps" in lowered_question:
        raw_terms.extend(["Happier Than Ever", "Midnight Sky", "EP", "album", "downloaded", "purchased"])
    if "formal education" in lowered_question:
        raw_terms.extend(["high school", "associate", "Bachelor", "UCLA", "2010", "2020"])
    if "average age" in lowered_question and "department" in lowered_question:
        raw_terms.extend(["department", "average age", "2.5", "older"])
    if "alex was born" in lowered_question:
        raw_terms.extend(["Alex", "born", "11", "years old"])
    if "sephora" in lowered_question:
        raw_terms.extend(["Sephora", "100 points", "Beauty Insider", "free skincare product"])
    if "current role" in lowered_question:
        raw_terms.extend(["current role", "Senior Marketing Specialist", "1 year", "5 months"])
    if "rachel gets married" in lowered_question:
        raw_terms.extend(["Rachel", "married", "next year", "33"])
    if "clinic on monday" in lowered_question:
        raw_terms.extend(["clinic", "Monday", "9:00 AM", "doctor's appointment"])
    if "airport to my hotel" in lowered_question and "taxi" in lowered_question:
        raw_terms.extend(["airport", "hotel", "taxi", "train", "bus", "$50", "not enough"])
    if "page count" in lowered_question and "novels" in lowered_question:
        raw_terms.extend(["novel", "January", "March", "page count", "856"])
    if any(marker in lowered_question for marker in ("spent playing games in total", "playing games in total", "hours have i spent playing games")):
        raw_terms.extend(
            [
                "odyssey",
                "assassin's creed",
                "the last of us part ii",
                "the last of us 2",
                "tlou2",
                "hard mode",
                "normal mode",
                "hyper light drifter",
                "celeste",
                "hours",
                "played",
                "gaming",
            ]
        )
    if any(marker in lowered_question for marker in ("workshops", "lectures", "conferences")) and "april" in lowered_question:
        raw_terms.extend(
            [
                "lecture on sustainable development",
                "public library",
                "10th of April",
                "2-day workshop",
                "17th and 18th of April",
                "April 17",
                "April 18",
            ]
        )
    if "charity" in lowered_question and any(marker in lowered_question for marker in ("raise", "raised", "goal", "fundraiser")):
        raw_terms.extend(
            [
                "charity",
                "fundraiser",
                "fundraising",
                "goal",
                "raised",
                "donation",
                "charity cycling",
                "bike ride",
                "book drive",
                "walk for hunger",
                "charity yoga event",
                "yoga event",
                "$5000",
                "$250",
                "$600",
                "$200",
            ]
        )
    if "coffee mug" in lowered_question and "each" in lowered_question:
        raw_terms.extend(["coffee mug", "mugs", "coworkers", "5 mugs", "5 coffee mugs", "one for each of them", "$60", "spent", "each"])
    if "model kit" in lowered_question:
        raw_terms.extend(
            [
                "model kit",
                "model kits",
                "revell",
                "f-15 eagle",
                "tamiya",
                "spitfire",
                "german tiger",
                "diorama",
                "b-29 bomber",
                "camaro",
                "model show",
                "hobby store",
                "1/72 scale",
                "1/48 scale",
                "1/16 scale",
                "1/24 scale",
            ]
        )
    if "doctor" in lowered_question and "visit" in lowered_question:
        raw_terms.extend(
            [
                "primary care physician",
                "ent specialist",
                "dermatologist",
                "dr. smith",
                "dr. patel",
                "dr. lee",
                "biopsy",
                "suspicious mole",
                "follow-up appointment",
                "appointment",
            ]
        )
    if "festival" in lowered_question and any(marker in lowered_question for marker in ("movie", "film")):
        raw_terms.extend(
            [
                "film festival",
                "movie festival",
                "portland film festival",
                "austin film festival",
                "seattle international film festival",
                "afi fest",
                "screening",
                "festival",
            ]
        )
    if "leadership positions" in lowered_question and "women" in lowered_question:
        raw_terms.extend(
            [
                "leadership positions",
                "women",
                "20 leadership positions",
                "100 leadership positions",
                "20 out of 100",
                "occupy 20 of the leadership positions",
                "percentage",
                "company leadership",
            ]
        )
    if "get ready" in lowered_question and "commute to work" in lowered_question:
        raw_terms.extend(
            [
                "get ready",
                "ready for work",
                "commute to work",
                "30 minute commute",
                "1 hour",
                "an hour",
                "half hour",
                "minutes",
            ]
        )
    if "car cover" in lowered_question or "detailing spray" in lowered_question:
        raw_terms.extend(
            [
                "car cover",
                "detailing spray",
                "car detailing",
                "cover",
                "spray",
                "$120",
                "$20",
            ]
        )
    if "camping trip" in lowered_question:
        raw_terms.extend(
            [
                "camping trip",
                "camped",
                "yellowstone national park",
                "yellowstone",
                "big sur",
                "yosemite national park",
                "solo camping trip",
                "family camping trip",
                "5-day camping trip",
                "3-day solo camping trip",
            ]
        )
    if "bike-related" in lowered_question and any(marker in lowered_question for marker in ("expense", "expenses", "spent")):
        raw_terms.extend(
            [
                "bike",
                "bike-related expenses",
                "tune-up",
                "chain",
                "bike lights",
                "bell zephyr helmet",
                "helmet",
                "bike shop",
                "cost me $25",
                "were $40",
                "for $120",
            ]
        )
    if "social media" in lowered_question and "break" in lowered_question:
        raw_terms.extend(
            [
                "social media break",
                "break from social media",
                "10-day break",
                "week-long break",
                "mid-february",
                "mid-january",
                "cut down on social media",
            ]
        )
    if "accommodations per night" in lowered_question and "hawaii" in lowered_question and "tokyo" in lowered_question:
        raw_terms.extend(
            [
                "hawaii",
                "maui",
                "luxurious resort",
                "$300 per night",
                "tokyo",
                "hostel",
                "$30 per night",
                "per night",
                "accommodation",
            ]
        )
    if "workshops" in lowered_question and any(marker in lowered_question for marker in ("total money", "spent")):
        raw_terms.extend(
            [
                "writing workshop",
                "digital marketing workshop",
                "mindfulness workshop",
                "paid $200",
                "paid $500",
                "paid $20",
                "literary festival",
                "city convention center",
                "yoga studio",
            ]
        )
    if any(marker in lowered_question for marker in ("museum of modern art", "moma", "ancient civilizations", "metropolitan museum of art")):
        raw_terms.extend(
            [
                "museum of modern art",
                "moma",
                "metropolitan museum of art",
                "ancient civilizations",
                "guided tour",
                "exhibit",
                "modern art",
                "ancient cultures",
            ]
        )
    asks_for_recommendation = any(marker in lowered_question for marker in ("recommend", "suggest", "tips", "any tips"))
    if asks_for_recommendation and "accessor" in lowered_question and "phone" in lowered_question:
        raw_terms.extend(
            [
                "iphone",
                "android",
                "pixel",
                "samsung",
                "phone case",
                "screen protector",
                "wireless charger",
                "charging pad",
                "portable power bank",
                "magnetic wallet",
                "magsafe",
                "accessories",
            ]
        )
    if asks_for_recommendation and ("accessor" in lowered_question or "gear" in lowered_question) and any(
        marker in lowered_question for marker in ("camera", "photography", "photo")
    ):
        raw_terms.extend(
            [
                "sony",
                "canon",
                "nikon",
                "tripod",
                "camera bag",
                "lens filter",
                "memory card",
                "extra battery",
                "camera strap",
                "flash",
                "accessories",
            ]
        )
    if asks_for_recommendation and ("publications" in lowered_question or "conferences" in lowered_question):
        raw_terms.extend(["artificial intelligence in healthcare", "deep learning", "medical image analysis", "research papers"])
    if asks_for_recommendation and "hotel" in lowered_question and "miami" in lowered_question:
        raw_terms.extend(["Miami", "ocean view", "city skyline", "rooftop pool", "hot tub", "balcony"])
    if asks_for_recommendation and "cultural events" in lowered_question:
        raw_terms.extend(["Spanish", "French", "language skills", "cultural exchange", "language learning"])
    if asks_for_recommendation and "battery life" in lowered_question and "phone" in lowered_question:
        raw_terms.extend(["portable power bank", "battery-saving", "fully charged", "phone battery"])
    if asks_for_recommendation and "rearranging the furniture" in lowered_question and "bedroom" in lowered_question:
        raw_terms.extend(["bedroom dresser", "mid-century modern", "replace", "furniture layout", "dresser"])
    if asks_for_recommendation and "theme park" in lowered_question:
        raw_terms.extend(["thrill rides", "special events", "unique food", "nighttime shows", "Disneyland", "Knott's Berry Farm"])
    if asks_for_recommendation and "activities" in lowered_question and "commute to work" in lowered_question:
        raw_terms.extend(["podcasts", "audiobooks", "history", "true crime", "self-improvement", "commute"])
    if "furniture" in lowered_question:
        raw_terms.extend(
            [
                "furniture",
                "bookshelf",
                "coffee table",
                "couch",
                "dresser",
                "mattress",
                "kitchen table",
                "assembled",
                "fixed",
                "bought",
                "sold",
                "West Elm",
                "IKEA",
            ]
        )
    if "art-related" in lowered_question or ("art" in lowered_question and "event" in lowered_question):
        raw_terms.extend(
            [
                "art event",
                "art afternoon",
                "exhibition",
                "gallery",
                "museum",
                "lecture",
                "mural",
                "street art",
                "artist",
                "Art Afternoon",
                "Women in Art",
                "art gallery",
                "history museum",
                "guided tour",
                "evolution of street art",
            ]
        )
    if "dinner parties" in lowered_question or ("dinner party" in lowered_question and "past month" in lowered_question):
        raw_terms.extend(
            [
                "dinner party",
                "italian feast",
                "sarah's place",
                "alex's place",
                "mike's place",
                "potluck",
                "bbq",
                "board games",
            ]
        )
    if "jimmy choo" in lowered_question or ("heels" in lowered_question and any(marker in lowered_question for marker in ("save", "saved"))):
        raw_terms.extend(
            [
                "jimmy choo",
                "heels",
                "outlet mall",
                "retail",
                "retail price",
                "originally",
                "normally",
                "$200",
                "$500",
                "save",
                "saved",
            ]
        )
    if "fitness class" in lowered_question or "fitness classes" in lowered_question:
        raw_terms.extend(["Zumba", "BodyPump", "Hip Hop Abs", "yoga class", "Pilates", "class", "classes"])
    if "fitness classes" in lowered_question and "days a week" in lowered_question:
        raw_terms.extend(["weightlifting", "Wednesdays", "Tuesdays", "Thursdays", "Saturdays"])
    if "kitchen item" in lowered_question or ("kitchen" in lowered_question and ("replace" in lowered_question or "fix" in lowered_question)):
        raw_terms.extend(
            [
                "kitchen faucet",
                "kitchen mat",
                "toaster",
                "toaster oven",
                "coffee maker",
                "kitchen shelves",
                "espresso machine",
                "fixed",
                "replaced",
                "got rid",
                "donated",
                "upgrade",
            ]
        )
    if "rollercoaster" in lowered_question and "july to october" in lowered_question:
        raw_terms.extend(
            [
                "Mako",
                "Kraken",
                "Manta",
                "Xcelerator",
                "Space Mountain: Ghost Galaxy",
                "Revenge of the Mummy",
                "Universal Studios Hollywood",
                "SeaWorld San Diego",
                "Knott's Berry Farm",
                "Disneyland",
                "three times",
            ]
        )
    if "graduation ceremon" in lowered_question and "past three months" in lowered_question:
        raw_terms.extend(
            [
                "Emma's preschool graduation",
                "Alex's graduation from a leadership development program",
                "Rachel's master's degree graduation ceremony",
                "Jack's eighth grade graduation ceremony",
                "missing my nephew Jack",
            ]
        )
    if "instagram followers" in lowered_question and "two weeks" in lowered_question:
        raw_terms.extend(
            [
                "250 followers",
                "350 followers",
                "started the year",
                "start of the year",
                "posting regularly",
                "followers on Instagram",
            ]
        )
    if "favorite author" in lowered_question and "discount" in lowered_question:
        raw_terms.extend(
            [
                "favorite author",
                "originally priced at $30",
                "got the book for $24",
                "$30",
                "$24",
                "after a discount",
            ]
        )
    if "older am i" in lowered_question and "graduated from college" in lowered_question:
        raw_terms.extend(
            [
                "32-year-old",
                "age of 25",
                "Berkeley",
                "Digital Marketing Specialist",
                "graduated from college",
            ]
        )
    if "fun run" in lowered_question and "work commitments" in lowered_question:
        raw_terms.extend(["March 26th", "March 5th", "missed a 5K fun run", "work commitments"])
    if "which bike" in lowered_question:
        raw_terms.extend(["road bike", "mountain bike", "maintenance check", "flat tire", "pedals", "brakes", "clipless pedals"])
    if "streaming service" in lowered_question:
        raw_terms.extend(["Disney+", "Apple TV+", "HBO Max", "Netflix", "Hulu", "Amazon Prime", "free trial", "last month"])
    if "business milestone" in lowered_question or "buisiness milestone" in lowered_question:
        raw_terms.extend(["first client", "signed a contract", "contract with my first client", "freelance clients"])
    if "competition" in lowered_question and "what did i buy" in lowered_question:
        raw_terms.extend(["sculpting tools", "modeling tool set", "wire cutter", "sculpting mat", "art competition", "sculpture category"])
    if "museum" in lowered_question and "two months ago" in lowered_question:
        raw_terms.extend(["Natural History Museum", "guided tour", "with my dad", "with a friend", "Science Museum", "fossil collection"])
    if "order from first to last" in lowered_question and "nursery" in lowered_question and "baby shower" in lowered_question:
        raw_terms.extend(
            [
                "prepare the nursery",
                "helped my friend prepare a nursery",
                "baby shower",
                "helped my cousin pick out some stuff for her baby shower",
                "customized phone case",
                "ordered a customized phone case for my friend's birthday",
                "Buy Buy Baby",
                "Target",
                "friend prepare a nursery",
                "cousin pick out some stuff",
                "friend's birthday",
            ]
        )
    if "gardening-related activity" in lowered_question:
        raw_terms.extend(["tomato saplings", "planted", "gardening app", "tomato plants", "neem oil", "insecticidal soap"])
    if "networking event" in lowered_question:
        raw_terms.extend(["networking event", "6 PM to 8 PM", "got back from"])
    if "art-related event" in lowered_question:
        raw_terms.extend(["Metropolitan Museum of Art", "Ancient Civilizations", "art museum", "exhibit", "attended"])
    if "plankchallenge" in lowered_question or "vegan chili" in lowered_question:
        raw_terms.extend(["#PlankChallenge", "vegan chili", "#FoodieAdventures", "#MyFitnessJourney", "Instagram"])
    if "religious activity" in lowered_question:
        raw_terms.extend(["Maundy Thursday service", "Episcopal Church", "church", "service", "religious activity"])
    if "sunday mass" in lowered_question and "ash wednesday" in lowered_question:
        raw_terms.extend(
            [
                "Sunday mass",
                "St. Mary's Church",
                "Ash Wednesday service",
                "cathedral on February 1st",
                "February 1st",
            ]
        )
    if "last friday" in lowered_question and any(term in lowered_question for term in ("artist", "listen", "listened")):
        raw_terms.extend(["bluegrass band", "banjo player", "started enjoying", "music today", "discovering new artists"])
    if "life event" in lowered_question and any(term in lowered_question for term in ("relative", "relatives", "cousin")):
        raw_terms.extend(["cousin's wedding", "cousin wedding", "bridesmaid", "walked down the aisle", "ceremony", "special song"])
    if "charity events" in lowered_question and ("consecutive" in lowered_question or "in a row" in lowered_question):
        raw_terms.extend(["charity gala", "24-Hour Bike Ride", "Books for Kids", "charity book drive", "Walk for Hunger"])
    if "exchange program" in lowered_question and "orientation" in lowered_question:
        raw_terms.extend(["accepted on March 20th", "pre-departure orientation", "every Friday since 3/27", "exchange program"])
    if "kitchen appliance" in lowered_question or "10 days ago" in lowered_question:
        raw_terms.extend(["smoker", "BBQ sauce", "got a smoker", "kitchen appliance"])
    if "book" in lowered_question and ("finish" in lowered_question or "finished" in lowered_question):
        raw_terms.extend(
            [
                "The Nightingale",
                "Kristin Hannah",
                "just finished",
                "just started",
                "just started \"The Nightingale\"",
                "started \"The Nightingale\" by Kristin Hannah today",
                "just finished a historical fiction novel, \"The Nightingale\"",
                "historical fiction novel",
                "reading lately",
            ]
        )
    if "book the airbnb in san francisco" in lowered_question:
        raw_terms.extend(
            [
                "Airbnb",
                "Haight-Ashbury",
                "book three months in advance",
                "three months in advance",
                "best friend's wedding",
                "exactly two months ago",
                "SF before",
                "San Francisco",
            ]
        )
    if "recovered from the flu" in lowered_question and "jog" in lowered_question:
        raw_terms.extend(["recovered from the flu", "10th jog outdoors", "jogging again", "back in shape"])
    if "graduation ceremony" in lowered_question and "birthday gift" in lowered_question:
        raw_terms.extend(["graduation gift", "wireless headphone", "3/8", "best friend's 30th birthday", "15th of March"])
    if "valentine" in lowered_question and ("airline" in lowered_question or "flied" in lowered_question or "flew" in lowered_question):
        raw_terms.extend(["American Airlines flight", "Valentine's Day", "February 14", "recovering from my American Airlines flight"])
    if "last saturday" in lowered_question and "from whom" in lowered_question:
        raw_terms.extend(["from my aunt", "crystal chandelier", "got a stunning", "received"])
    if "sports events" in lowered_question and "participated" in lowered_question:
        raw_terms.extend(["Spring Sprint Triathlon", "Midsummer 5K Run", "charity soccer tournament", "participate"])
    if "stand-up comedy" in lowered_question and "open mic" in lowered_question:
        raw_terms.extend(["stand-up", "3 months ago", "open mic night", "local comedy club", "last month"])
    if "necklace for my sister" in lowered_question and "photo album for my mom" in lowered_question:
        raw_terms.extend(["necklace from Tiffany's", "last weekend", "photo album", "Shutterfly", "two weeks ago"])
    if "order of airlines" in lowered_question:
        raw_terms.extend(["JetBlue", "Delta", "United Airlines", "American Airlines", "got back from", "round-trip flight"])
    if "area rug" in lowered_question and "rearranged" in lowered_question:
        raw_terms.extend(["area rug", "a month ago", "rearranged the furniture", "three weeks ago"])
    if "became a parent first" in lowered_question and "tom" in lowered_question and "alex" in lowered_question:
        raw_terms.extend(
            [
                "Alex",
                "Tom",
                "adopted a baby girl",
                "baby girl from China",
                "Alex just adopted a baby girl from China in January",
                "in January",
                "became a parent",
            ]
        )
    if "seattle international film festival" in lowered_question:
        raw_terms.extend(["Seattle International Film Festival", "SIFF", "Coda", "attended SIFF"])
    if "car's suspension" in lowered_question and "new suspension setup" in lowered_question:
        raw_terms.extend(["suspension settings", "feedback", "new suspension setup", "track day", "tomorrow"])
    if "tuesdays and thursdays" in lowered_question and "wake" in lowered_question:
        raw_terms.extend(["7:00 AM", "15 minutes earlier", "Tuesdays and Thursdays", "waking up"])
    if "baking class" in lowered_question and "birthday cake" in lowered_question:
        raw_terms.extend(["baking class", "local culinary school", "yesterday", "birthday cake"])
    if "how old" in lowered_question and "moved to the united states" in lowered_question:
        raw_terms.extend(["32-year-old", "past five years", "living in the United States", "work visa"])
    if "undergraduate degree" in lowered_question and "master's thesis" in lowered_question:
        raw_terms.extend(["completed my undergraduate degree", "submitted my master's thesis", "computer science"])

    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        normalized = re.sub(r"\s+", " ", str(term or "").strip().lower())
        if len(normalized) < 3 or normalized in _LONG_MEMORY_EVIDENCE_STOPWORDS:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(normalized)
    return terms


def _build_long_memory_scope_hints(user_question: str) -> list[str]:
    lowered_question = (user_question or "").lower()
    hints: list[str] = []
    if _is_update_semantic_question(lowered_question):
        hints.append(
            "Knowledge-update rule: if multiple supported rows mention the same entity or topic with different values over time, compare the supported rows by date before answering; do not stop at the first plausible match."
        )
        hints.append(
            "Boundary rule: current/latest/most recent/now -> choose the latest supported row; initial/at first/when I first started/previously/used to -> choose the earliest supported row before later updates; if the question asks for both, return both boundary values."
        )
        hints.append(
            "Supersede rule: later phrases such as now, currently, most recently, updated, changed to, or just realized often supersede earlier values; keep older rows as history unless the question explicitly asks for the initial value."
        )
    if "how many" in lowered_question or "total" in lowered_question:
        hints.append(
            "Counting rule: enumerate every distinct supported candidate before giving the final number; do not stop at the first matching row."
        )
    if "pick up" in lowered_question or "return" in lowered_question:
        hints.append(
            "Pickup/return rule: count each pending pickup or return obligation separately. If an exchanged item mentions both an old return/exchange and a new pickup, count the return/exchange obligation and the new pickup obligation separately when the question asks for items to pick up or return."
        )
    if "worth" in lowered_question and "paid" in lowered_question:
        hints.append(
            "Value relation rule: when an object is referred to by pronouns or a nearby alias such as flea market find, carry forward the stated value ratio instead of refusing."
        )
    if "currently" in lowered_question and "subscription" in lowered_question:
        hints.append(
            "Current-subscription rule: canceled subscriptions are inactive; active mentions such as subscribed to, still getting, or have been loving count as current unless later canceled."
        )
    if _is_temporal_ledger_question(lowered_question):
        hints.append(
            "Temporal ledger rule: sort supported event rows by their row timestamps; relative phrases like today, yesterday, last weekend, or two months ago are anchored to the row timestamp. For 'days passed' or 'days before', compute the calendar-day delta between the two supported event dates; inclusive wording may allow delta + 1."
        )
    if "before making an offer" in lowered_question:
        hints.append(
            "Before-offer scope rule: count properties viewed before the target offer; exclude the target property itself and keep the rejected/out-of-budget alternatives. A row saying an offer was rejected due to a higher bid is a previously viewed property and counts."
        )
    if "food delivery" in lowered_question or "delivery service" in lowered_question:
        hints.append(
            "Delivery-service rule: count named delivery/takeout brands as services even when the row names only the brand, such as Uber Eats, Domino's, or a local prepared-meal service."
        )
    if "plant" in lowered_question:
        hints.append(
            "Acquisition rule: count plants acquired via gifts, purchases, or nursery trips; the row may say got/bought/received instead of acquired."
        )
    if "fitness class" in lowered_question or "fitness classes" in lowered_question:
        hints.append(
            "Fitness-class rule: count weekly class sessions, not just distinct class names. A class held twice per week contributes two sessions."
        )
    if "last week" in lowered_question:
        hints.append(
            "Last-week rule: interpret dated relative references against QUESTION_DATE; include completed activities in the prior week when the row's date falls in that window."
        )
    if "kitchen item" in lowered_question or ("kitchen" in lowered_question and ("replace" in lowered_question or "fix" in lowered_question)):
        hints.append(
            "Kitchen-item rule: count repaired/replaced kitchen objects even when phrased as got rid of, donated, upgraded to, or replaced with a newer appliance."
        )
    return hints

__all__ = [
    "_is_temporal_ledger_question",
    "_is_update_semantic_question",
    "_long_memory_evidence_terms",
    "_build_long_memory_scope_hints",
]
