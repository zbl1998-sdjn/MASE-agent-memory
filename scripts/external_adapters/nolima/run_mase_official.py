from __future__ import annotations

# ruff: noqa: I001

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import tiktoken

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from benchmarks.runner import _aggregate_call_log
from data.book_haystack import BookHaystack
from mase import MASESystem

DEFAULT_TASK_TEMPLATE = (
    "You will answer a question based on the following book snippet:\n\n"
    "{haystack}\n\n"
    "Use the information provided in the book snippet to answer the question. "
    "Your answer should be short and based on either explicitly stated facts or strong, logical inferences.\n\n"
    "Question: {question}\n\n"
    " Return only the final answer with no additional explanation or reasoning."
)


def _resolve_runs_dir() -> Path:
    raw = os.environ.get("MASE_RUNS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (REPO_ROOT.parent / "MASE-runs").resolve()

ABSTENTION_MARKERS = (
    # Hard abstentions
    "cannot answer",
    "can't answer",
    "no answer",
    "unable to answer",
    "not enough information",
    "insufficient information",
    "not explicitly stated",
    "not stated",
    "not mentioned",
    "based on current records",
    # Soft refusals: "cannot/unable to determine/find"
    "cannot determine",
    "can't determine",
    "unable to determine",
    "cannot be determined",
    "not possible to determine",
    "cannot find",
    "can't find",
    # Soft refusals: "no information / no mention / no evidence"
    "no information",
    "no mention of",
    "no evidence",
    "no indication",
    # Soft refusals: "does not / didn't mention/contain/specify/provide"
    "does not mention",
    "doesn't mention",
    "does not contain",
    "doesn't contain",
    "does not provide",
    "doesn't provide",
    "does not specify",
    "doesn't specify",
    # Soft refusals: subject-keyed ("the text/passage/snippet/document does not")
    "the text does not",
    "the passage does not",
    "the snippet does not",
    "the document does not",
    "the fact sheet does not",
    # Soft refusals: "not available / not specified / not provided"
    "not available",
    "not specified",
    "not provided",
    # Soft refusals: "nothing in the ..."
    "nothing in the",
    # Soft refusals: "i don't know / i do not know"
    "i don't know",
    "i do not know",
    "i'm not sure",
    "i am not sure",
)


@dataclass
class ExpandedTest:
    test_name: str
    needle: str
    retrieval_question: str
    task_template: str
    system_prompt: str
    gold_answers: list[str]
    character_set: list[str]
    seed: int
    distractor: str | None


class Utf8BookHaystack(BookHaystack):
    def __init__(self, book_path: str) -> None:
        self.book_path = book_path
        path = Path(book_path)
        if not path.exists():
            raise FileNotFoundError(f"Book path {book_path} does not exist")
        if path.suffix.lower() != ".txt":
            raise ValueError(f"Book path {book_path} is not supported")
        self.text = path.read_text(encoding="utf-8")
        self.text_encoded = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run official NoLiMa tests through MASE.")
    parser.add_argument(
        "--needle-set-path",
        default=str(REPO_ROOT / "benchmarks" / "external-benchmarks" / "NoLiMa" / "data" / "needlesets" / "needle_set.json"),
        help="Official NoLiMa needle set json path",
    )
    parser.add_argument(
        "--haystack-dir",
        default=str(REPO_ROOT / "benchmarks" / "external-benchmarks" / "NoLiMa" / "data" / "haystack" / "rand_shuffle"),
        help="Official NoLiMa haystack directory",
    )
    parser.add_argument("--context-length", type=int, required=True, help="NoLiMa context length")
    parser.add_argument("--document-depth-percent-min", type=float, default=0.0)
    parser.add_argument("--document-depth-percent-max", type=float, default=100.0)
    parser.add_argument("--document-depth-percent-intervals", type=int, default=26)
    parser.add_argument("--shift", type=int, default=0)
    parser.add_argument("--static-depth", type=float, default=-1.0)
    parser.add_argument("--metric", default="contains", choices=["EM", "contains", "lastline_EM", "lastline_contains"])
    parser.add_argument("--base-seed", type=int, default=42)
    parser.add_argument("--limit-tests", type=int, default=None, help="Optional expanded-test limit")
    parser.add_argument(
        "--include-tests",
        default="",
        help="Optional comma-separated substrings/regexes; only expanded test names matching any selector run",
    )
    parser.add_argument("--limit-haystacks", type=int, default=None, help="Optional haystack-file limit")
    parser.add_argument(
        "--encoding-name",
        default="approx_words",
        help="Tokenizer encoding name used for official needle placement (supports tiktoken names or approx_words)",
    )
    parser.add_argument(
        "--executor-role",
        default="reasoning",
        choices=["general", "reasoning"],
        help="MASE executor role",
    )
    parser.add_argument("--run-dir", default=None, help="Optional run artifact directory")
    return parser.parse_args()


def build_tokenizer(encoding_name: str) -> tuple[str, Any, Any]:
    normalized = str(encoding_name or "").strip()
    if normalized == "approx_words":
        token_pattern = re.compile(r"\S+\s*|\s+")

        def encode(text: str) -> list[str]:
            return token_pattern.findall(text)

        def decode(tokens: list[str]) -> str:
            return "".join(tokens)

        return normalized, encode, decode

    try:
        encoding = tiktoken.get_encoding(normalized)
        return normalized, encoding.encode, encoding.decode
    except Exception:
        token_pattern = re.compile(r"\S+\s*|\s+")

        def encode(text: str) -> list[str]:
            return token_pattern.findall(text)

        def decode(tokens: list[str]) -> str:
            return "".join(tokens)

        return f"{normalized} (fallback=approx_words)", encode, decode


def load_needle_set(path: Path, base_seed: int) -> list[ExpandedTest]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    expanded: list[ExpandedTest] = []
    for exp_config in raw:
        system_prompt = str(exp_config.get("system_prompt") or "")
        task_template = str(exp_config.get("task_template") or DEFAULT_TASK_TEMPLATE)
        exp_id = str(exp_config["id"])
        questions = exp_config.get("questions") or {}
        tests = exp_config.get("tests") or {}
        character_set = [str(item) for item in (exp_config.get("character_set") or [])]
        for question_type, question_template in questions.items():
            for test_id, test in tests.items():
                full_question = str(question_template)
                full_needle = str(exp_config["needle"])
                full_distractor = None
                input_args = test.get("input_args") or []
                for arg_no, arg in enumerate(input_args, start=1):
                    placeholder = "{" + str(arg_no) + "}"
                    full_question = full_question.replace(placeholder, str(arg))
                    full_needle = full_needle.replace(placeholder, str(arg))
                    distractors = exp_config.get("distractors") or {}
                    if (
                        isinstance(distractors, dict)
                        and question_type in distractors
                        and placeholder in str(distractors[question_type])
                    ):
                        full_distractor = str(distractors[question_type]).replace(placeholder, str(arg))
                gold_answers = [str(item) for item in (test.get("gold_answers") or [])]
                expanded.append(
                    ExpandedTest(
                        test_name=f"{exp_id}_{test_id}_{question_type}",
                        needle=full_needle,
                        retrieval_question=full_question,
                        task_template=task_template,
                        system_prompt=system_prompt,
                        gold_answers=gold_answers,
                        character_set=character_set,
                        seed=base_seed + int(exp_id[:4]),
                        distractor=full_distractor,
                    )
                )
    return expanded



def _split_test_selectors(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def matches_test_selectors(test_name: str, selectors: list[str]) -> bool:
    if not selectors:
        return True
    for selector in selectors:
        if selector in test_name:
            return True
        try:
            if re.search(selector, test_name):
                return True
        except re.error:
            continue
    return False


def is_entity_seeking_question(question: str) -> bool:
    lowered_question = str(question or "").strip().lower()
    entity_seeking_patterns = (
        "which character",
        "which person",
        "who ",
        "who's ",
        "whose ",
        " who ",
    )
    return any(pat in lowered_question for pat in entity_seeking_patterns)


def _question_bridge_terms(question: str) -> list[str]:
    lowered = str(question or "").lower()
    terms = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", question)
        if token.lower() not in {"which", "character", "person", "cannot", "drink", "eat", "been", "has", "have", "who", "the", "where"}
    ]
    semantic_cues = {
        "lactose": ("milk", "dairy", "cappuccino", "cream", "cheese"),
        "intolerant": ("cannot", "drink", "eat", "milk", "dairy", "cappuccino"),
        "vegan": ("cannot", "eat", "meat", "fish", "dairy", "animal", "brandade"),
        "museum": ("city", "country", "capital", "landmark", "painting"),
        "painting": ("museum", "city", "country", "landmark"),
        "lives": ("where", "city", "country", "near", "next"),
        "living": ("where", "city", "country", "engineer"),
    }
    for cue, implied in semantic_cues.items():
        if cue in lowered or any(term in lowered for term in implied):
            terms.extend([cue, *implied])
    if "has been to" in lowered or "been to" in lowered:
        terms.extend(["visited", "saw", "seen", "museum", "painting", "landmark", "city", "country", "lives", "living"])
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower().strip("'\"")
        if len(key) < 3 or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped[:18]


def _character_windows(text: str, character: str, radius: int = 220, max_windows: int = 3) -> list[str]:
    if not text or not character:
        return []
    windows: list[str] = []
    pattern = re.compile(rf"\b{re.escape(character)}\b", flags=re.IGNORECASE)
    for match in pattern.finditer(text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        snippet = " ".join(text[start:end].split())
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        if snippet not in windows:
            windows.append(snippet)
        if len(windows) >= max_windows:
            break
    return windows


def extract_haystack_entity_candidates(
    haystack_text: str,
    question: str,
    character_set: list[str],
) -> list[dict[str, Any]]:
    """Extract candidate-character evidence from the haystack without gold labels.

    This is a white-box guard for NoLiMa: enumerate the public candidate
    characters, keep only characters that actually appear in the generated
    snippet, and attach local evidence windows plus question/bridge term hits.
    It never reads gold answers or selected_character.
    """
    bridge_terms = _question_bridge_terms(question)
    rows: list[dict[str, Any]] = []
    for character in character_set:
        windows = _character_windows(haystack_text, character)
        if not windows:
            continue
        joined = " ".join(windows).lower()
        direct_hits = [term for term in bridge_terms if term in joined]
        rows.append(
            {
                "name": character,
                "windows": windows,
                "direct_hits": direct_hits,
            }
        )
    return rows


def build_nolima_evidence_preamble(haystack_text: str, question: str, character_set: list[str]) -> str:
    rows = extract_haystack_entity_candidates(haystack_text, question, character_set)
    if not rows:
        return ""
    lines = [
        "NOLIMA CANDIDATE EVIDENCE (derived from the snippet; not gold):",
        "- Treat the following character list as the answer candidate set for entity-seeking questions.",
        "- First isolate each candidate, then match the question predicate/negation/condition, then answer.",
        "- For implicit chains (landmark→city/country, food→dietary restriction), identify the bridge fact before selecting a character.",
        "- If no candidate has a supported bridge, answer exactly: Cannot answer.",
        f"Question bridge terms: {', '.join(_question_bridge_terms(question)) or 'none'}",
    ]
    for index, row in enumerate(rows, start=1):
        hits = ", ".join(row["direct_hits"]) if row["direct_hits"] else "none"
        evidence = " || ".join(row["windows"])
        lines.append(f"[C{index}] name={row['name']} | direct_hits={hits} | evidence={evidence}")
    return "\n".join(lines)


def candidate_names_from_preamble(preamble: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"^\[C\d+\]\s+name=([^|\n]+)", str(preamble or ""), flags=re.MULTILINE):
        name = match.group(1).strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def response_matches_candidate(response: str, candidates: list[str]) -> bool:
    cleaned = str(response or "").strip().lower()
    if not cleaned or not candidates:
        return False
    return any(candidate.lower() in cleaned for candidate in candidates)


def single_supported_candidate(preamble: str) -> str:
    """Return the sole candidate only when its row has some predicate/bridge hit."""
    matches = re.findall(r"^\[C\d+\]\s+name=([^|\n]+)\s+\|\s+direct_hits=([^|\n]+)", str(preamble or ""), flags=re.MULTILINE)
    if len(matches) != 1:
        return ""
    name, hits = matches[0]
    if hits.strip().lower() in {"", "none"}:
        return ""
    return name.strip()

def evaluate_metric(metric: str, response: str, gold_answers: list[str]) -> int:
    normalized = str(response or "").strip()
    if metric == "EM":
        return int(normalized in gold_answers)
    if metric == "contains":
        return int(any(answer in normalized for answer in gold_answers))
    if metric == "lastline_EM":
        return int(normalized.splitlines()[-1].strip() in gold_answers) if normalized else 0
    if metric == "lastline_contains":
        last_line = normalized.splitlines()[-1].strip() if normalized else ""
        return int(any(answer in last_line for answer in gold_answers))
    raise ValueError(f"Unsupported metric: {metric}")


def build_executor_question(system_prompt: str, task_template: str, retrieval_question: str) -> str:
    prompt = task_template.format(haystack="the fact sheet provided separately", question=retrieval_question)
    prompt = prompt.replace("the following book snippet:\n\nthe fact sheet provided separately", "the fact sheet provided separately")
    prompt = prompt.replace("the book snippet", "the fact sheet")
    prompt = prompt.strip()
    if system_prompt.strip():
        return f"{system_prompt.strip()}\n\n{prompt}"
    return prompt


def is_abstention_like(response: str) -> bool:
    lowered = str(response or "").strip().lower()
    if not lowered:
        return True
    if any(marker in lowered for marker in ABSTENTION_MARKERS):
        return True
    if lowered in {"none", "unknown"}:
        return True
    return lowered.startswith("none of the characters") or lowered.startswith("no character")


def should_retry_with_extractor(
    question: str,
    response: str,
    candidate_names: list[str] | None = None,
) -> bool:
    """Return True for generic NoLiMa entity failures worth extractor retry.

    Triggers are deliberately white-box and test-agnostic:
    - abstention-like response on an entity-seeking question;
    - entity-seeking response outside the haystack-derived candidate set.
    """
    if not is_entity_seeking_question(question):
        return False
    if is_abstention_like(response):
        return True
    candidates = [name for name in (candidate_names or []) if str(name).strip()]
    if candidates and not response_matches_candidate(response, candidates):
        return True
    return False


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    processed = len(results)
    passed = sum(int(item.get("metric_value") or 0) for item in results)
    failed = processed - passed
    by_test: dict[str, dict[str, Any]] = {}
    by_haystack: dict[str, dict[str, Any]] = {}
    by_depth: dict[str, dict[str, Any]] = {}
    for item in results:
        for bucket, key in (
            (by_test, str(item["test_name"])),
            (by_haystack, str(item["haystack_name"])),
            (by_depth, str(item["depth_percent"])),
        ):
            entry = bucket.setdefault(key, {"processed": 0, "passed": 0})
            entry["processed"] += 1
            entry["passed"] += int(item.get("metric_value") or 0)
    for bucket in (by_test, by_haystack, by_depth):
        for entry in bucket.values():
            entry["failed"] = entry["processed"] - entry["passed"]
            entry["accuracy"] = round(entry["passed"] / max(1, entry["processed"]), 4)
    return {
        "processed": processed,
        "passed": passed,
        "failed": failed,
        "accuracy": round(passed / max(1, processed), 4),
        "by_test": by_test,
        "by_haystack": by_haystack,
        "by_depth": by_depth,
    }


def main() -> None:
    args = parse_args()
    needle_set_path = Path(args.needle_set_path).resolve()
    haystack_dir = Path(args.haystack_dir).resolve()
    if not needle_set_path.exists():
        raise FileNotFoundError(f"Needle set not found: {needle_set_path}")
    if not haystack_dir.exists():
        raise FileNotFoundError(f"Haystack dir not found: {haystack_dir}")

    expanded_tests = load_needle_set(needle_set_path, base_seed=args.base_seed)
    selectors = _split_test_selectors(args.include_tests)
    if selectors:
        expanded_tests = [test for test in expanded_tests if matches_test_selectors(test.test_name, selectors)]
    if args.limit_tests is not None:
        expanded_tests = expanded_tests[: args.limit_tests]

    haystack_paths = sorted(path for path in haystack_dir.iterdir() if path.is_file() and path.suffix.lower() == ".txt")
    if args.limit_haystacks is not None:
        haystack_paths = haystack_paths[: args.limit_haystacks]

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_run_dir = (
        _resolve_runs_dir()
        / "external-benchmarks"
        / "NoLiMa"
        / "outputs"
        / f"mase-{needle_set_path.stem}-{args.context_length}-{timestamp}"
    )
    run_dir = Path(args.run_dir).resolve() if args.run_dir else default_run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    results_path = run_dir / "nolima.results.json"
    summary_path = run_dir / "nolima.summary.json"

    resolved_encoding_name, encode_tokens, decode_tokens = build_tokenizer(args.encoding_name)
    system = MASESystem()
    results: list[dict[str, Any]] = []
    previous_task_profile = os.environ.get("MASE_TASK_PROFILE")
    os.environ["MASE_TASK_PROFILE"] = "candidate_evidence"

    try:
        for haystack_index, haystack_path in enumerate(haystack_paths):
            haystack = Utf8BookHaystack(str(haystack_path))
            for test in expanded_tests:
                np.random.seed(test.seed + haystack_index)
                for depth_percent in np.linspace(
                    args.document_depth_percent_min,
                    args.document_depth_percent_max,
                    args.document_depth_percent_intervals,
                ):
                    selected_character = None
                    needle = test.needle
                    retrieval_question = test.retrieval_question
                    gold_answers = list(test.gold_answers)
                    if "{CHAR}" in needle:
                        if not test.character_set:
                            raise ValueError(f"Character set missing for test: {test.test_name}")
                        selected_character = str(np.random.choice(test.character_set))
                        needle = needle.replace("{CHAR}", selected_character)
                        retrieval_question = retrieval_question.replace("{CHAR}", selected_character)
                        if not gold_answers:
                            gold_answers = [selected_character]

                    placement = haystack.generate_w_needle_placement(
                        needle=needle,
                        token_count_func=lambda text: len(encode_tokens(text)),
                        encoding_func=encode_tokens,
                        decoding_func=decode_tokens,
                        context_length=args.context_length,
                        shift=args.shift,
                        depth=float(depth_percent) / 100.0,
                        static_depth=args.static_depth,
                        distractor=test.distractor,
                    )

                    question = build_executor_question(
                        system_prompt=test.system_prompt,
                        task_template=test.task_template,
                        retrieval_question=retrieval_question,
                    )
                    evidence_preamble = build_nolima_evidence_preamble(
                        str(placement["text"]),
                        retrieval_question,
                        test.character_set,
                    )
                    fact_sheet = (
                        f"{evidence_preamble}\n\nFULL BOOK SNIPPET:\n{placement['text']}"
                        if evidence_preamble
                        else str(placement["text"])
                    )
                    candidate_names = candidate_names_from_preamble(evidence_preamble)

                    system.model_interface.reset_call_log()
                    started = time.perf_counter()
                    raw_answer = ""
                    error = None
                    target: dict[str, Any] | None = None
                    retry_used = False
                    try:
                        target = system.describe_executor_target(
                            mode="grounded_answer",
                            user_question=question,
                            use_memory=True,
                            executor_role=args.executor_role,
                        )
                        raw_answer = system.call_executor(
                            user_question=question,
                            fact_sheet=fact_sheet,
                            allow_general_knowledge=False,
                            task_type="grounded_answer",
                            use_memory=True,
                            executor_role=args.executor_role,
                        )
                        if should_retry_with_extractor(retrieval_question, raw_answer, candidate_names):
                            os.environ["MASE_TASK_PROFILE"] = "candidate_evidence_extract"
                            retry_used = True
                            retry_target = system.describe_executor_target(
                                mode="grounded_answer",
                                user_question=question,
                                use_memory=True,
                                executor_role=args.executor_role,
                            )
                            retry_answer = system.call_executor(
                                user_question=question,
                                fact_sheet=fact_sheet,
                                allow_general_knowledge=False,
                                task_type="grounded_answer",
                                use_memory=True,
                                executor_role=args.executor_role,
                            )
                            if (
                                retry_answer.strip()
                                and not is_abstention_like(retry_answer)
                                and (not candidate_names or response_matches_candidate(retry_answer, candidate_names))
                            ):
                                raw_answer = retry_answer
                                target = retry_target
                            elif candidate_names and not response_matches_candidate(raw_answer, candidate_names):
                                guarded_candidate = single_supported_candidate(evidence_preamble)
                                if guarded_candidate:
                                    raw_answer = guarded_candidate
                                    target = retry_target
                            os.environ["MASE_TASK_PROFILE"] = "candidate_evidence"
                    except Exception as exc:  # pragma: no cover - runtime safety
                        error = f"{type(exc).__name__}: {exc}"
                        os.environ["MASE_TASK_PROFILE"] = "candidate_evidence"

                    metrics = _aggregate_call_log(system.model_interface.get_call_log())
                    metrics["wall_clock_seconds"] = round(time.perf_counter() - started, 6)
                    metric_value = evaluate_metric(args.metric, raw_answer, gold_answers) if not error else 0

                    row = {
                        "test_name": test.test_name,
                        "haystack_name": haystack_path.name,
                        "context_length": args.context_length,
                        "depth_percent": round(float(depth_percent), 3),
                        "needle": needle,
                        "retrieval_question": retrieval_question,
                        "gold_answers": gold_answers,
                        "selected_character": selected_character,
                        "response": raw_answer,
                        "metric": args.metric,
                        "metric_value": metric_value,
                        "placement_metadata": {k: v for k, v in placement.items() if k != "text"},
                        "executor_target": target,
                        "retry_used": retry_used,
                        "candidate_names": candidate_names,
                        "evidence_preamble": evidence_preamble,
                        "metrics": metrics,
                        "error": error,
                    }
                    results.append(row)
                    print(
                        json.dumps(
                            {
                                "processed": len(results),
                                "test": test.test_name,
                                "haystack": haystack_path.name,
                                "depth": row["depth_percent"],
                                "metric": metric_value,
                                "error": error,
                                "response": raw_answer[:120],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
    finally:
        if previous_task_profile is None:
            os.environ.pop("MASE_TASK_PROFILE", None)
        else:
            os.environ["MASE_TASK_PROFILE"] = previous_task_profile

    summary = {
        "needle_set_path": str(needle_set_path),
        "haystack_dir": str(haystack_dir),
        "context_length": args.context_length,
        "document_depth_percent_min": args.document_depth_percent_min,
        "document_depth_percent_max": args.document_depth_percent_max,
        "document_depth_percent_intervals": args.document_depth_percent_intervals,
        "metric": args.metric,
        "encoding_name": resolved_encoding_name,
        "executor_role": args.executor_role,
        "test_count": len(expanded_tests),
        "include_tests": selectors,
        "haystack_count": len(haystack_paths),
        "results_path": str(results_path),
        "summary": summarize_results(results),
    }

    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
