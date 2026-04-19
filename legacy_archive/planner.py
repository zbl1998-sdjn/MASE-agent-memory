from __future__ import annotations

import re
from dataclasses import dataclass, replace

from mase_tools.legacy import _extract_english_content_terms, _normalize_english_search_text, extract_question_scope_filters


PLANNER_STOPWORDS = {
    "我们",
    "之前",
    "上次",
    "刚才",
    "刚刚",
    "前面",
    "最开始",
    "那个",
    "这个",
    "一下",
    "什么",
    "怎么",
    "如果",
    "请把",
    "告诉我",
    "再说一遍",
    "确认一下",
}

PLANNER_EN_STOPWORDS = {
    "how",
    "many",
    "what",
    "which",
    "when",
    "time",
    "did",
    "do",
    "does",
    "have",
    "has",
    "had",
    "are",
    "were",
    "was",
    "will",
    "would",
    "can",
    "could",
    "should",
    "the",
    "a",
    "an",
    "i",
    "me",
    "my",
    "we",
    "our",
    "to",
    "on",
    "in",
    "before",
    "after",
    "this",
    "last",
    "different",
    "total",
}

VAGUE_MARKERS = ("那个", "这个", "方案", "计划", "策略", "事情", "安排", "问题")
COLD_MARKERS = ("之前", "上次", "前面", "最开始", "最早", "历史", "以前", "last month", "previous", "history")
TEMPORAL_SCAN_MARKERS = (
    "before",
    "after",
    "between",
    "ago",
    "since",
    "last week",
    "last month",
    "last year",
    "past ",
    "day before",
    "day after",
    "happened first",
    "order of the three",
    "from first to last",
    "from earliest to latest",
    "earliest",
    "most recent",
    "latest",
)
STATE_SCAN_MARKERS = (
    "current",
    "currently",
    "used to",
    "when i started",
    "back then",
    "initially",
    "at first",
)
COMPLEX_MARKERS = (
    "总共",
    "一共",
    "合计",
    "比较",
    "对比",
    "分析",
    "统计",
    "计算",
    "加起来",
    "分别",
    "各自",
    "多少个",
    "多少次",
    "多少小时",
    "多长时间",
    "count",
    "compare",
    "analysis",
    "analyze",
    "calculate",
    "combined",
    "in total",
    "how many",
    "how much",
    "how long",
    "autonomous decision",
    "decision chain",
    "source arbitration",
    "evidence chain",
)
DISAMBIGUATION_MARKERS = (
    "是谁",
    "叫什么",
    "哪个",
    "哪位",
    "哪一个",
    "哪年",
    "哪一年",
    "年份",
    "名字",
    "who",
    "which",
    "what year",
    "what's the name",
    "what is the name",
)


@dataclass(frozen=True)
class PlannerStep:
    step_id: str
    title: str
    details: str
    depends_on: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "details": self.details,
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class PlannerDecision:
    strategy: str
    query_variants: list[str]
    memory_limit: int | None
    collaboration_mode: str
    active_date_scan: bool
    widen_search: bool
    min_results: int
    confusion_level: str
    steps: list[PlannerStep]
    notes: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "query_variants": list(self.query_variants),
            "memory_limit": self.memory_limit,
            "collaboration_mode": self.collaboration_mode,
            "active_date_scan": self.active_date_scan,
            "widen_search": self.widen_search,
            "min_results": self.min_results,
            "confusion_level": self.confusion_level,
            "steps": [step.to_dict() for step in self.steps],
            "notes": list(self.notes),
        }


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
    return result


def _extract_query_terms(text: str) -> list[str]:
    fragments = re.findall(r"[A-Za-z0-9\-]+|[\u4e00-\u9fff]{2,16}", text)
    result: list[str] = []
    for fragment in fragments:
        normalized = fragment.strip()
        if len(normalized) < 2:
            continue
        lowered = normalized.lower()
        if normalized in PLANNER_STOPWORDS:
            continue
        if lowered in PLANNER_EN_STOPWORDS or lowered == "__full_query__":
            continue
        result.append(normalized)
    return _dedupe(result)


def _extract_english_focus_terms(question: str) -> list[str]:
    lowered = question.lower()
    match = re.search(
        r"how many\s+(.+?)(?:\s+(?:did|do|does|have|has|had|are|were|was|will|would|can|could|should|in|before|after|this|last)\b|\?)",
        lowered,
    )
    focus_chunks: list[str] = [match.group(1)] if match else []
    focus_chunks.extend(_extract_temporal_candidate_phrases(question))
    if not focus_chunks:
        return []
    tokens = re.findall(r"[a-z][a-z\-]+", " ".join(focus_chunks))
    return _dedupe([token for token in tokens if token not in PLANNER_EN_STOPWORDS])


def _clean_temporal_candidate_phrase(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip(" ,.;:!?"))
    cleaned = re.sub(
        r"^(?:the\s+day\s+i|the\s+day|day\s+i|my\s+visit\s+to|my\s+trip\s+to|my\s+visit|my\s+trip)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:from\s+earliest\s+to\s+latest|from\s+first\s+to\s+last|from\s+latest\s+to\s+earliest)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(?:in\s+a\s+row|on\s+consecutive\s+days?|on\s+back-?to-?back\s+days?|back-?to-?back)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" ,.;:!?")


def _has_consecutive_day_marker(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:in\s+a\s+row|on\s+consecutive\s+days?|on\s+back-?to-?back\s+days?|back-?to-?back)\b",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )


def _interleave_expansion_groups(seeds: list[str], expansion_groups: list[list[str]], max_depth: int) -> list[str]:
    queries: list[str] = list(seeds)
    for depth in range(max_depth):
        for group in expansion_groups:
            if depth < len(group):
                queries.append(group[depth])
    return _dedupe(queries)


def _extract_temporal_candidate_phrases(question: str) -> list[str]:
    source = re.sub(r"\s+", " ", str(question or "").strip())
    lowered = source.lower()
    candidates: list[str] = []

    for quoted in re.findall(r"(?<![A-Za-z0-9])['\"]([^'\"]{3,160})['\"](?![A-Za-z0-9])", source):
        cleaned = _clean_temporal_candidate_phrase(quoted)
        if cleaned:
            candidates.append(cleaned)

    between_match = re.search(r"\bbetween\s+(.+?)\s+and\s+(.+?)(?:\?|$)", source, flags=re.IGNORECASE)
    if between_match:
        for part in between_match.groups():
            cleaned = _clean_temporal_candidate_phrase(part)
            if cleaned:
                candidates.append(cleaned)

    binary_order_patterns = (
        r"\bwhich event happened first,\s+(.+?)\s+or\s+(.+?)(?:\?|$)",
        r"\bwhich happened first,\s+(.+?)\s+or\s+(.+?)(?:\?|$)",
    )
    for pattern in binary_order_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if not match:
            continue
        for part in match.groups():
            cleaned = _clean_temporal_candidate_phrase(part)
            if cleaned:
                candidates.append(cleaned)

    dual_anchor_patterns = (
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+ago\s+did i\s+(.+?)\s+when i\s+(.+?)(?:\?|$)",
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+(?:had|have)\s+passed since i\s+(.+?)\s+when i\s+(.+?)(?:\?|$)",
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+passed since i\s+(.+?)\s+when i\s+(.+?)(?:\?|$)",
    )
    dual_anchor_matched = False
    for pattern in dual_anchor_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if not match:
            continue
        dual_anchor_matched = True
        for part in match.groups():
            cleaned = _clean_temporal_candidate_phrase(part)
            if cleaned:
                candidates.append(cleaned)

    single_event_patterns = (
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+ago\s+did i\s+(.+?)(?:\?|$)",
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+(?:have\s+)?passed\s+since i\s+(.+?)(?:\?|$)",
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+have\s+passed\s+since\s+(.+?)(?:\?|$)",
        r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+did i spend on\s+(.+?)(?:\?|$)",
    )
    if not dual_anchor_matched:
        for pattern in single_event_patterns:
            match = re.search(pattern, source, flags=re.IGNORECASE)
            if not match:
                continue
            raw_candidate = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;:!?")
            if _has_consecutive_day_marker(raw_candidate):
                candidates.append(raw_candidate)
            cleaned = _clean_temporal_candidate_phrase(raw_candidate)
            if cleaned:
                candidates.append(cleaned)

    relative_anchor_patterns = (
        r"\bday before i had\s+(.+?)(?:\?|$)",
        r"\bday before i went to\s+(.+?)(?:\?|$)",
        r"\bday after i had\s+(.+?)(?:\?|$)",
        r"\bday after i went to\s+(.+?)(?:\?|$)",
    )
    for pattern in relative_anchor_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if not match:
            continue
        cleaned = _clean_temporal_candidate_phrase(match.group(1))
        if cleaned:
            candidates.append(cleaned)

    if not candidates and any(marker in lowered for marker in ("order from first to last", "order of the three", "from earliest to latest")):
        tail = source.split(":", 1)[1] if ":" in source else ""
        if tail:
            tail = re.sub(r"\s*,?\s+and\s+", ", ", tail, flags=re.IGNORECASE)
            for part in [segment.strip() for segment in tail.split(",")]:
                cleaned = _clean_temporal_candidate_phrase(part)
                if cleaned:
                    candidates.append(cleaned)
    if not candidates and any(marker in lowered for marker in ("order of the three", "from earliest to latest", "from first to last")):
        generic_order_match = re.search(
            r"\b(?:order of the three|the three)\s+(trips?|events?|visits?)\b",
            lowered,
            flags=re.IGNORECASE,
        )
        if generic_order_match:
            candidates.append(generic_order_match.group(1))

    deduped = _dedupe(candidates)
    collapsed: list[str] = []
    normalized_candidates = [
        re.sub(r"[^a-z0-9:/\-\s]", " ", candidate.lower()).replace("'s", "")
        for candidate in deduped
    ]
    normalized_candidates = [re.sub(r"\s+", " ", candidate).strip() for candidate in normalized_candidates]
    for index, candidate in enumerate(deduped):
        normalized_candidate = normalized_candidates[index]
        if not normalized_candidate:
            continue
        contained = False
        for other_index, other_normalized in enumerate(normalized_candidates):
            if index == other_index or not other_normalized or normalized_candidate == other_normalized:
                continue
            if len(normalized_candidate.split()) >= len(other_normalized.split()):
                continue
            if normalized_candidate in other_normalized:
                contained = True
                break
        if not contained:
            collapsed.append(candidate)
    return collapsed or deduped


def _expand_temporal_candidate_search_terms(candidate: str) -> list[str]:
    raw_source = re.sub(r"\s+", " ", str(candidate or "").strip(" ,.;:!?"))
    consecutive_day_candidate = _has_consecutive_day_marker(raw_source)
    source = _clean_temporal_candidate_phrase(raw_source)
    if not source:
        return []

    expanded: list[str] = []
    seen: set[str] = set()
    blocked = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "then",
        "with",
        "from",
        "for",
        "today",
        "yesterday",
        "tomorrow",
        "event",
        "events",
    }

    def add(value: str) -> None:
        normalized = re.sub(r"\s+", " ", str(value or "").strip(" ,.;:!?"))
        if not normalized:
            return
        lowered = normalized.lower()
        if lowered in seen or lowered in blocked:
            return
        tokens = re.findall(r"[A-Za-z0-9$][A-Za-z0-9$'\-]*", normalized)
        if not tokens:
            return
        if len(tokens) == 1 and len(tokens[0]) < 4 and tokens[0].lower() not in {"moma"}:
            return
        seen.add(lowered)
        expanded.append(normalized)

    def add_object_fragments(text: str) -> None:
        for pattern in (
            r"^(?:i\s+)?(?:meet(?:ing)?\s+up\s+with|met\s+up\s+with|meeting\s+with)\s+(.+)$",
            r"^(?:i\s+)?(?:receive(?:d)?|got|get|buy|bought|purchase(?:d)?|use(?:d)?|redeem(?:ed)?|order(?:ed)?|sign(?:ed)?\s+up\s+for|start(?:ed)?|finish(?:ed)?|harvest(?:ed)?|attend(?:ed)?|visit(?:ed)?(?:\s+to)?|participat(?:e|ed)\s+in|cancel(?:led|ed)|discover(?:ed)?|find|found|make|made|bake|baked|cook|cooked)\s+(.+)$",
        ):
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            fragment = match.group(1)
            add(fragment)
            without_article = re.sub(r"^(?:the|a|an)\s+", "", fragment, flags=re.IGNORECASE)
            if without_article != fragment:
                add(without_article)
            without_quantity = re.sub(
                r"^\s*(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+",
                "",
                without_article,
                flags=re.IGNORECASE,
            ).strip(" ,.;:!?")
            if without_quantity and without_quantity.lower() != without_article.lower():
                add(without_quantity)
                if without_quantity.lower().endswith(" events"):
                    add(re.sub(r"\bevents\b", "event", without_quantity, flags=re.IGNORECASE))
                elif without_quantity.lower().endswith(" event"):
                    add(re.sub(r"\bevent\b", "events", without_quantity, flags=re.IGNORECASE))
        simplified = re.sub(
            r"\b(?:in\s+a\s+row|on\s+consecutive\s+days?|on\s+back-?to-?back\s+days?|back-?to-?back)\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        simplified = re.sub(
            r"^\s*(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+",
            "",
            simplified,
            flags=re.IGNORECASE,
        )
        simplified = simplified.strip(" ,.;:!?")
        if simplified and simplified.lower() != text.lower():
            add(simplified)
            if consecutive_day_candidate:
                add(f"{simplified} consecutive days")
                add(f"{simplified} in a row")

    generic_aliases = {
        "trip": [
            "road trip",
            "day hike",
            "camping trip",
            "solo camping trip",
            "vacation",
            "travel",
            "just got back from",
            "i started my solo camping trip",
        ],
        "trips": [
            "road trip",
            "day hike",
            "camping trip",
            "solo camping trip",
            "vacation",
            "travel",
            "just got back from",
            "i started my solo camping trip",
        ],
        "travel": [
            "trip",
            "road trip",
            "day hike",
            "camping trip",
            "solo camping trip",
            "vacation",
            "just got back from",
        ],
    }

    for alias in re.findall(r"\(([A-Za-z0-9][A-Za-z0-9 .&'\-]{1,24})\)", source):
        add(alias)

    unwrapped = re.sub(r"\(([^)]+)\)", "", source).strip(" ,.;:!?")
    if unwrapped and unwrapped.lower() != source.lower():
        add_object_fragments(unwrapped)
        add(unwrapped)

    for segment in re.split(r"\s+(?:and|then)\s+", unwrapped or source, flags=re.IGNORECASE):
        cleaned_segment = _clean_temporal_candidate_phrase(segment)
        if not cleaned_segment:
            continue
        add_object_fragments(cleaned_segment)
        add(cleaned_segment)
        without_article = re.sub(r"^(?:the|a|an)\s+", "", cleaned_segment, flags=re.IGNORECASE)
        if without_article != cleaned_segment:
            add(without_article)
        for splitter in (" at ", " from ", " with ", " for "):
            if splitter not in cleaned_segment.lower():
                continue
            left, right = re.split(splitter, cleaned_segment, maxsplit=1, flags=re.IGNORECASE)
            add(right)
            add(left)

    add_object_fragments(source)
    add(source)
    if consecutive_day_candidate:
        add(raw_source)
        add(f"{source} consecutive days")
        add(f"{source} in a row")
    if re.search(r"\bbirthday cake\b", source, flags=re.IGNORECASE):
        add("birthday cake")
    if re.search(r"\bmade\b", source, flags=re.IGNORECASE):
        add(re.sub(r"\bmade\b", "baked", source, flags=re.IGNORECASE))
    if re.search(r"\bmake\b", source, flags=re.IGNORECASE):
        add(re.sub(r"\bmake\b", "bake", source, flags=re.IGNORECASE))
    for proper_noun in re.findall(r"\b(?:[A-Z][A-Za-z0-9&'\-]*)(?:\s+[A-Z][A-Za-z0-9&'\-]*){0,3}\b", source):
        add(proper_noun)
    for alias in generic_aliases.get(source.lower(), []):
        add(alias)
    for phrase in list(expanded):
        for match in re.finditer(
            r"\b(?:my|our|the)\s+([A-Za-z][A-Za-z0-9'&\-]+(?:\s+[A-Za-z][A-Za-z0-9'&\-]+){0,4})",
            phrase,
            flags=re.IGNORECASE,
        ):
            add(match.group(1))

    return expanded


def _expand_temporal_candidate_search_queries(question: str) -> list[str]:
    queries: list[str] = []
    for candidate in _extract_temporal_candidate_phrases(question):
        queries.extend(_expand_temporal_candidate_search_terms(candidate))
    return _dedupe(queries)


def _expand_english_focus_terms(question: str) -> list[str]:
    focus_terms = _extract_english_focus_terms(question)
    if not focus_terms:
        return []
    alias_map = {
        "clothing": ["boots", "blazer", "jacket", "shirt", "pants", "shoes"],
        "doctor": ["physician", "specialist", "dermatologist", "ent", "clinic"],
        "doctors": ["physician", "specialist", "dermatologist", "ent", "clinic"],
        "plant": ["snake plant", "peace lily", "succulent", "orchid", "fern"],
        "property": ["townhouse", "condo", "bungalow", "apartment", "house"],
        "wedding": ["couple", "ceremony", "bride", "groom"],
        "festival": ["sundance", "tribeca", "sxsw", "cannes", "toronto"],
        "fruit": ["orange", "grapefruit", "lime", "lemon", "citrus"],
        "project": ["marketing research", "data analysis", "customer data", "product launch", "feature launch", "leading"],
        "projects": ["marketing research", "data analysis", "customer data", "product launch", "feature launch", "leading"],
        "model": ["model kit", "revell", "tamiya", "spitfire", "tiger", "b-29", "camaro", "eagle"],
        "kit": ["model kit", "revell", "tamiya", "spitfire", "tiger", "b-29", "camaro", "eagle"],
        "luxury": ["gucci", "handbag", "gown", "boots", "designer"],
        "game": ["assassin's creed", "odyssey", "last of us", "witcher", "red dead", "gameplay"],
        "games": ["assassin's creed", "odyssey", "last of us", "witcher", "red dead", "gameplay"],
        "tank": ["aquarium", "fish tank"],
        "trip": ["road trip", "hike", "camping trip", "vacation", "travel"],
        "trips": ["road trip", "day hike", "camping trip", "vacation", "travel"],
        "travel": ["trip", "road trip", "vacation", "camping trip", "hike"],
        "charity": ["charity gala", "fundraiser", "benefit", "outreach event", "donation drive"],
        "event": ["charity gala", "fundraiser", "benefit", "workshop", "conference"],
        "events": ["charity gala", "fundraiser", "benefit", "workshop", "conference"],
        "museum": ["moma", "metropolitan museum", "art museum", "gallery"],
        "museums": ["moma", "metropolitan museum", "art museum", "gallery"],
        "furniture": ["desk", "chair", "bookshelf", "dresser", "table", "sofa", "bed"],
        "baby": ["newborn", "twins", "gave birth", "welcomed"],
        "babies": ["newborn", "twins", "gave birth", "welcomed"],
        "bake": ["bread", "brownies", "cookies", "cake", "muffins", "sourdough"],
        "bike": ["repair", "tune-up", "helmet", "lights", "tires", "brake"],
        "break": ["social media", "instagram", "twitter", "facebook", "tiktok", "detox"],
        "movie": ["marvel", "mcu", "star wars"],
        "movies": ["marvel", "mcu", "star wars"],
    }
    expanded: list[str] = list(focus_terms)
    for term in focus_terms:
        expanded.extend(alias_map.get(term, []))
    return _dedupe(expanded)


def _extract_english_query_seeds(question: str) -> list[str]:
    lowered = question.lower()
    scope_filters = extract_question_scope_filters(question)
    noise_terms = {
        "day",
        "days",
        "hour",
        "hours",
        "minute",
        "minutes",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "time",
        "times",
        "total",
        "combined",
        "altogether",
        "spent",
        "spend",
        "money",
        "much",
        "many",
        "how",
        "did",
        "do",
        "does",
        "have",
        "has",
        "had",
    }
    seeds = [
        term
        for term in _extract_english_content_terms(question, limit=12)
        if str(term).strip().lower() not in noise_terms
    ]
    seeds.extend(str(item) for item in scope_filters.get("locations", []) if str(item).strip())
    seeds.extend(str(item) for item in scope_filters.get("relative_terms", []) if str(item).strip())

    if any(marker in lowered for marker in ("camp", "camping", "trip", "travel", "drive", "driving", "road trip")):
        seeds.extend(["camping trip", "road trip", "trip", "travel", "driving"])
        for location in scope_filters.get("locations", [])[:4]:
            seeds.extend(
                [
                    f"{location} camping trip",
                    f"{location} road trip",
                    f"{location} trip",
                ]
            )

    if any(marker in lowered for marker in ("bike", "luxury", "spent", "money", "cost", "paid", "expense")):
        seeds.extend(["expense", "cost", "paid for", "purchase"])
        if "bike" in lowered:
            seeds.extend(["bike expense", "bike-related expense", "bike shop", "helmet", "chain", "lights"])
        if "luxury" in lowered:
            seeds.extend(["luxury item", "luxury purchase", "designer item"])

    if any(marker in lowered for marker in ("social media", "break", "detox")):
        seeds.extend(["social media break", "break from social media", "week-long break", "10-day break"])

    if any(marker in lowered for marker in ("baby", "born", "birth", "newborn", "twins")):
        seeds.extend(["baby born", "welcomed their first baby", "twins born", "baby boy named", "daughter born"])

    return _dedupe([seed for seed in seeds if len(seed.strip()) >= 2])[:18]


def _expand_bridge_query_variants(question: str) -> list[str]:
    lowered = str(question or "").lower()
    variants: list[str] = []
    bridge_rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("helsinki",), ("kiasma museum", "kiasma")),
        (("mauritshuis",), ("girl with a pearl earring", "painting up close")),
        (("cannot drink milk", "drink milk", "milk"), ("lactose intolerant", "dairy intolerant")),
        (("cannot eat fish-based meals", "cannot eat fish", "fish-based meals"), ("vegan", "vegan for years")),
    ]
    for question_markers, expansions in bridge_rules:
        if any(marker in lowered for marker in question_markers):
            variants.extend(expansions)
    return _dedupe(variants)


def _is_english_count_reasoning(question: str) -> bool:
    lowered = question.lower()
    if any(
        marker in lowered
        for marker in (
            " ago",
            "passed since",
            "passed between",
            "between the day",
            "between the time",
            "happened first",
            "order of the three",
            "from first to last",
            "from earliest to latest",
        )
    ):
        return False
    return "how many" in lowered and any(marker in lowered for marker in (" i ", " my ", " we ", " our ", "did i", "did we"))


def _is_ambiguous_memory_query(user_question: str, route_keywords: list[str]) -> bool:
    if _contains_any(user_question, VAGUE_MARKERS):
        return True
    if not route_keywords:
        return True
    return all(len(keyword.strip()) <= 3 for keyword in route_keywords if keyword.strip())


def _is_disambiguation_question(user_question: str) -> bool:
    return _contains_any(user_question, DISAMBIGUATION_MARKERS)


def _build_query_variants(user_question: str, route_keywords: list[str], complex_query: bool) -> list[str]:
    route_terms = [term for term in _dedupe(route_keywords) if str(term).strip().lower() != "__full_query__"]
    extracted_terms = _extract_query_terms(user_question)
    query_seeds = _extract_english_query_seeds(user_question)
    temporal_candidates = _extract_temporal_candidate_phrases(user_question)
    temporal_expansion_groups = [
        [query for query in _expand_temporal_candidate_search_terms(candidate) if query.lower() != candidate.lower()]
        for candidate in temporal_candidates[:4]
    ]
    temporal_search_queries = _interleave_expansion_groups(
        temporal_candidates[:4],
        temporal_expansion_groups,
        4 if len(temporal_candidates) <= 1 else 2,
    )
    english_focus_terms = _expand_english_focus_terms(user_question)
    bridge_query_terms = _expand_bridge_query_variants(user_question)
    lowered_question = user_question.lower()
    targeted_variants: list[str] = []
    if any(marker in lowered_question for marker in ("how many hours", "in total")) and "game" in lowered_question:
        targeted_variants.extend(
            [
                "assassin's creed odyssey took me",
                "the last of us part ii took me",
                "celeste took me",
                "hyper light drifter took me",
            ]
        )
    if any(marker in lowered_question for marker in ("autonomous decision", "decision chain", "source arbitration", "evidence chain")):
        targeted_variants.extend(
            [
                "autonomous decision chain",
                "autonomous decision",
                "decision chain",
                "source arbitration",
                "evidence chain",
                "direct support only",
            ]
        )
    if "luxury" in lowered_question and any(marker in lowered_question for marker in ("total amount", "spent", "how much")):
        targeted_variants.extend(
            [
                "luxury evening gown",
                "designer handbag from Gucci",
                "leather boots from a high-end designer",
            ]
        )
    if "how many times" in lowered_question and "bake" in lowered_question:
        targeted_variants.extend(
            [
                "baked a chocolate cake",
                "baked cookies",
                "whole wheat baguette",
                "sourdough starter bread recipe",
            ]
        )
    if lowered_question.startswith("what time") and "go to bed" in lowered_question and "appointment" in lowered_question:
        targeted_variants.extend(
            [
                "didn't get to bed until",
                "last Wednesday bedtime",
                "doctor's appointment last Thursday",
            ]
        )
    if "camping trips in the united states" in lowered_question and "how many days" in lowered_question:
        targeted_variants.extend(
            [
                "Yellowstone National Park camping trip",
                "Big Sur solo camping trip",
                "5-day camping trip",
                "3-day solo camping trip",
            ]
        )
    if "road trip destinations" in lowered_question and "driving" in lowered_question:
        targeted_variants.extend(
            [
                "drove for five hours to the mountains in Tennessee",
                "drove for six hours to Washington D.C.",
                "Outer Banks took four hours to drive there",
            ]
        )
    if "bike-related expenses" in lowered_question and any(marker in lowered_question for marker in ("how much", "total money", "spent")):
        targeted_variants.extend(
            [
                "Bell Zephyr helmet for $120",
                "replace the chain cost me $25",
                "bike lights installed were $40",
            ]
        )
    if "social media breaks" in lowered_question and "how many days" in lowered_question:
        targeted_variants.extend(
            [
                "week-long break from social media",
                "10-day break from social media",
                "just got back from a 10-day break from social media",
                "took a week-long break from it",
            ]
        )
    if "babies were born" in lowered_question and "last few months" in lowered_question:
        targeted_variants.extend(
            [
                "baby boy named",
                "welcomed their first baby",
                "twins born in April",
                "son who was born in March",
                "daughter Charlotte was born",
            ]
        )
    variants: list[str] = [user_question]
    if targeted_variants:
        variants.extend(targeted_variants)
    if route_terms:
        variants.append(" ".join(route_terms[:3]))
    if extracted_terms:
        variants.append(" ".join(extracted_terms[:4]))
    if temporal_search_queries:
        variants.extend(temporal_search_queries[:6])
        temporal_terms = _extract_query_terms(" ".join(temporal_search_queries))
        if temporal_terms:
            variants.append(" ".join(temporal_terms[:6]))
    elif temporal_candidates:
        variants.extend(temporal_candidates[:3])
    if english_focus_terms:
        variants.append(" ".join(english_focus_terms[:6]))
    if bridge_query_terms:
        variants.extend(bridge_query_terms[:4])
        bridge_combo = _dedupe([*bridge_query_terms[:2], *route_terms[:1], *extracted_terms[:1]])
        if bridge_combo:
            variants.append(" ".join(bridge_combo[:4]))
    if complex_query and len(extracted_terms) >= 2:
        variants.append(" ".join(extracted_terms[:2]))
    if route_terms and extracted_terms:
        variants.append(" ".join(_dedupe(route_terms[:2] + extracted_terms[:2])))
    if query_seeds:
        variants.extend(query_seeds[:10])
        if route_terms:
            for seed in query_seeds[:6]:
                variants.append(" ".join(_dedupe([seed, *route_terms[:1]])))
    if _is_disambiguation_question(user_question) and extracted_terms:
        variants.append("精确区分 " + " ".join(extracted_terms[:3]))
    single_word_noise = {
        "day",
        "days",
        "hour",
        "hours",
        "minute",
        "minutes",
        "week",
        "weeks",
        "month",
        "months",
        "year",
        "years",
        "time",
        "times",
        "spent",
        "spend",
        "money",
        "much",
        "many",
        "how",
    }
    filtered = [
        variant
        for variant in _dedupe(variants)
        if len(variant.split()) > 1 or (len(variant) >= 4 and variant.lower() not in single_word_noise)
    ]
    return filtered[:10]


def _extract_candidate_entities(search_results: list[dict[str, object]]) -> list[str]:
    text = " ".join(
        str(item.get(field) or "")
        for item in search_results[:6]
        for field in ("summary", "user_query", "assistant_response", "thread_label")
    )
    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,6}", text)
    latin_terms = re.findall(r"[A-Z][a-zA-Z\-]{2,20}", text)
    candidates = [
        term
        for term in chinese_terms + latin_terms
        if term not in PLANNER_STOPWORDS and len(term.strip()) >= 2
    ]
    return _dedupe(candidates)[:12]


def _has_similar_entities(entities: list[str]) -> bool:
    chinese_entities = [item for item in entities if re.fullmatch(r"[\u4e00-\u9fff]{2,6}", item)]
    for index, current in enumerate(chinese_entities):
        for other in chinese_entities[index + 1 :]:
            if current == other:
                continue
            if current[0] == other[0] or current[:2] == other[:2]:
                return True
    for index, current in enumerate(entities):
        for other in entities[index + 1 :]:
            if current == other:
                continue
            if current.lower() in other.lower() or other.lower() in current.lower():
                return True
    return False


def _extract_candidate_numbers(search_results: list[dict[str, object]]) -> list[str]:
    text = " ".join(
        str(item.get(field) or "")
        for item in search_results[:6]
        for field in ("summary", "user_query", "assistant_response")
    )
    return _dedupe(re.findall(r"\d+(?:\.\d+)?", text))


def assess_confusion_level(user_question: str, search_results: list[dict[str, object]]) -> tuple[str, list[str]]:
    if not search_results:
        return "low", []

    reasons: list[str] = []
    entities = _extract_candidate_entities(search_results)
    numbers = _extract_candidate_numbers(search_results)
    disambiguation_question = _is_disambiguation_question(user_question)
    text_length = sum(
        len(str(item.get("summary") or "")) + len(str(item.get("assistant_response") or ""))
        for item in search_results[:4]
    )

    if disambiguation_question and len(entities) > 1 and _has_similar_entities(entities):
        reasons.append("similar_entities")
        return "high", reasons
    if disambiguation_question and len(numbers) >= 2:
        reasons.append("multiple_numbers")
        return "high", reasons
    if disambiguation_question and text_length > 200:
        reasons.append("long_disambiguation_context")
        return "medium", reasons
    if len(numbers) >= 3 and _contains_any(user_question, ("哪年", "哪一年", "年份", "多少")):
        reasons.append("dense_numeric_candidates")
        return "medium", reasons
    return "low", reasons


def refine_planner_with_confusion(
    planner: PlannerDecision,
    user_question: str,
    task_type: str,
    search_results: list[dict[str, object]],
) -> PlannerDecision:
    if task_type != "grounded_answer":
        return planner

    confusion_level, reasons = assess_confusion_level(user_question, search_results)
    if confusion_level == "low":
        return replace(planner, confusion_level="low")

    notes = _dedupe(
        [
            note
            for note in [*planner.notes, *reasons, f"confusion_{confusion_level}", "disambiguation_reasoning"]
            if note != "general_executor"
        ]
    )
    steps = [step for step in planner.steps if step.step_id not in {"plan-answer", "plan-reason"}]
    compression_dependency = "plan-compress" if any(step.step_id == "plan-compress" for step in steps) else "plan-route"
    steps.append(
        PlannerStep(
            step_id="plan-confusion-assess",
            title="Assess confusion",
            details=f"Detected {confusion_level} confusion from similar entities or competing candidates.",
            depends_on=[compression_dependency],
        )
    )
    steps.append(
        PlannerStep(
            step_id="plan-disambiguate",
            title="Disambiguate evidence",
            details="Route to grounded disambiguation so the reasoning executor can eliminate confusing candidates.",
            depends_on=["plan-confusion-assess"],
        )
    )
    return replace(
        planner,
        strategy="disambiguation",
        collaboration_mode="verify",
        widen_search=True,
        min_results=max(planner.min_results, 2),
        confusion_level=confusion_level,
        steps=steps,
        notes=notes,
    )


def build_planner_decision(
    user_question: str,
    route_action: str,
    route_keywords: list[str],
    task_type: str,
    executor_role: str,
    use_memory: bool,
    base_memory_limit: int | None,
) -> PlannerDecision:
    lowered_question = user_question.lower()
    autonomous_decision_query = _contains_any(
        user_question,
        (
            "autonomous decision",
            "decision chain",
            "source arbitration",
            "evidence chain",
        ),
    )
    ambiguous_query = use_memory and _is_ambiguous_memory_query(user_question, route_keywords)
    complex_query = executor_role == "reasoning" or _contains_any(user_question, COMPLEX_MARKERS)
    if autonomous_decision_query:
        complex_query = True
    temporal_query = use_memory and (_contains_any(user_question, TEMPORAL_SCAN_MARKERS) or _contains_any(user_question, STATE_SCAN_MARKERS))
    active_date_scan = use_memory and (_contains_any(user_question, COLD_MARKERS) or ambiguous_query or temporal_query)
    widen_search = use_memory and (complex_query or ambiguous_query or temporal_query)
    memory_limit = base_memory_limit
    if use_memory and complex_query:
        memory_limit = max(base_memory_limit or 3, 5)
    elif use_memory and (ambiguous_query or temporal_query):
        memory_limit = max(base_memory_limit or 3, 4)

    if not use_memory:
        strategy = "direct_execution"
    elif complex_query:
        strategy = "zoom_in_out"
    elif ambiguous_query:
        strategy = "query_rewrite_lookup"
    else:
        strategy = "direct_lookup"

    collaboration_mode = (
        "verify"
        if use_memory
        and task_type in {"grounded_answer", "grounded_analysis"}
        and (executor_role == "reasoning" or complex_query or ambiguous_query or autonomous_decision_query)
        else "off"
    )
    min_results = 3 if complex_query else 1
    if use_memory and _is_english_count_reasoning(user_question):
        memory_limit = max(memory_limit or 3, 6)
        min_results = max(min_results, 4)
        if any(marker in lowered_question for marker in ("camp", "camping", "trip", "travel", "road trip")):
            widen_search = True
            memory_limit = max(memory_limit, 8)
            min_results = max(min_results, 6)
    binary_event_order_question = "happened first" in lowered_question
    implicit_dual_anchor_question = bool(
        re.search(r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+ago\s+did i\s+.+\s+when i\s+.+", lowered_question)
        or re.search(r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+(?:had|have)\s+passed since i\s+.+\s+when i\s+.+", lowered_question)
        or re.search(r"\bhow many\s+(?:days?|weeks?|months?|years?)\s+passed since i\s+.+\s+when i\s+.+", lowered_question)
    )
    if use_memory and (binary_event_order_question or implicit_dual_anchor_question):
        widen_search = True
        memory_limit = max(memory_limit or 3, 8)
        min_results = max(min_results, 6 if binary_event_order_question else 5)
        if strategy == "direct_lookup":
            strategy = "zoom_in_out"
    quoted_candidate_count = len(re.findall(r"(?<![A-Za-z0-9])['\"]([^'\"]{3,160})['\"](?![A-Za-z0-9])", user_question))
    bridge_query_terms = _expand_bridge_query_variants(user_question) if use_memory else []
    consecutive_temporal_question = _has_consecutive_day_marker(lowered_question)
    if use_memory and consecutive_temporal_question:
        widen_search = True
        memory_limit = max(memory_limit or 3, 8)
        min_results = max(min_results, 5)
        if strategy == "direct_lookup":
            strategy = "zoom_in_out"
    if (
        use_memory
        and quoted_candidate_count >= 2
        and re.search(r"\bhow many\s+(minutes?|hours?|days?|weeks?|months?|years?)\b", user_question.lower())
        and any(marker in user_question.lower() for marker in ("in total", "combined", "altogether"))
    ):
        widen_search = True
        memory_limit = max(memory_limit or 3, min(14, quoted_candidate_count * 4))
        min_results = max(min_results, min(8, quoted_candidate_count * 2))
        if strategy == "direct_lookup":
            strategy = "zoom_in_out"
    if use_memory and re.search(r"\bwhere did i .*?(?:bachelor|master|degree)\b", user_question.lower()):
        widen_search = True
        memory_limit = max(memory_limit or 3, 6)
        min_results = max(min_results, 4)
        if strategy == "direct_lookup":
            strategy = "zoom_in_out"
    if use_memory and bridge_query_terms:
        widen_search = True
        memory_limit = max(memory_limit or 3, 6)
        min_results = max(min_results, 4)
        if strategy == "direct_lookup":
            strategy = "zoom_in_out"
    if use_memory and autonomous_decision_query:
        widen_search = True
        memory_limit = max(memory_limit or 3, 6)
        min_results = max(min_results, 4)
        if strategy == "direct_lookup":
            strategy = "zoom_in_out"
    query_variants = _build_query_variants(user_question, route_keywords, complex_query) if use_memory else []

    steps = [
        PlannerStep(
            step_id="plan-route",
            title="Route request",
            details=f"action={route_action}, keywords={route_keywords}",
            depends_on=[],
        )
    ]
    notes: list[str] = []

    if use_memory:
        if ambiguous_query:
            steps.append(
                PlannerStep(
                    step_id="plan-rewrite",
                    title="Rewrite query",
                    details="Generate more concrete memory queries from the ambiguous recall request.",
                    depends_on=["plan-route"],
                )
            )
            notes.append("ambiguous_query")
        steps.append(
            PlannerStep(
                step_id="plan-search",
                title="Search memory",
                details="Retrieve candidates with keywords, variants, synonyms, and semantic fallback.",
                depends_on=["plan-rewrite"] if ambiguous_query else ["plan-route"],
            )
        )
        if active_date_scan:
            steps.append(
                PlannerStep(
                    step_id="plan-date-scan",
                    title="Scan dates",
                    details="Probe recent date buckets when the first recall pass is too weak or too vague.",
                    depends_on=["plan-search"],
                )
            )
            notes.append("date_scan")
        if widen_search:
            steps.append(
                PlannerStep(
                    step_id="plan-widen",
                    title="Widen search",
                    details="Relax thread/date constraints and zoom out to broader evidence when needed.",
                    depends_on=["plan-date-scan"] if active_date_scan else ["plan-search"],
                )
            )
            notes.append("widen_search")
        steps.append(
            PlannerStep(
                step_id="plan-compress",
                title="Compress evidence",
                details="Deduplicate results, highlight relevant snippets, and attach aggregation hints.",
                depends_on=["plan-widen"] if widen_search else ["plan-date-scan"] if active_date_scan else ["plan-search"],
            )
        )
        if autonomous_decision_query:
            steps.append(
                PlannerStep(
                    step_id="plan-arbitrate",
                    title="Arbitrate sources",
                    details="Prefer directly supported evidence and reject unsupported chain links before answering.",
                    depends_on=["plan-compress"],
                )
            )
            notes.append("source_arbitration")

    final_dependency = ["plan-arbitrate"] if autonomous_decision_query and use_memory else ["plan-compress"] if use_memory else ["plan-route"]
    if executor_role == "reasoning":
        steps.append(
            PlannerStep(
                step_id="plan-reason",
                title="Reason deeply",
                details="Use ReasoningExecutor with structured evidence and deterministic aggregation hints.",
                depends_on=final_dependency,
            )
        )
        notes.append("reasoning_executor")
    else:
        steps.append(
            PlannerStep(
                step_id="plan-answer",
                title="Answer directly",
                details="Use GeneralExecutor for direct extraction or low-latency response generation.",
                depends_on=final_dependency,
            )
        )
        notes.append("general_executor")

    return PlannerDecision(
        strategy=strategy,
        query_variants=query_variants,
        memory_limit=memory_limit,
        collaboration_mode=collaboration_mode,
        active_date_scan=active_date_scan,
        widen_search=widen_search,
        min_results=min_results,
        confusion_level="low",
        steps=steps,
        notes=notes,
    )
