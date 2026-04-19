"""Chaos injector — randomly fail model calls to verify fallback paths.

Usage::

    python scripts/chaos.py --rate 0.5 --questions sample_questions.txt

The script monkey-patches ``ModelInterface._call_anthropic`` and
``_call_openai`` to raise a fake 503 with the configured probability, then
runs the questions through the engine and prints whether each one survived.

It is deliberately a separate top-level script (not a unit test) so it
exercises the real engine pipeline including the health tracker, circuit
breaker, and event bus.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

# Make sure ``src/`` is on the path when run from project root.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import httpx  # noqa: E402

from mase import MASESystem  # noqa: E402
from mase.health_tracker import get_tracker  # noqa: E402
from mase.model_interface import ModelInterface  # noqa: E402

DEFAULT_QUESTIONS = [
    "你叫什么名字？",
    "1 + 1 等于几？",
    "What is the capital of France?",
    "请用一句话介绍你自己。",
]


def _make_fake_503(model: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", f"https://chaos.local/{model}")
    response = httpx.Response(status_code=503, request=request, content=b'{"error": "chaos"}')
    return httpx.HTTPStatusError("chaos: simulated 503", request=request, response=response)


def install_chaos(rate: float) -> None:
    rate = max(0.0, min(1.0, rate))
    original_anthropic = ModelInterface._call_anthropic
    original_openai = ModelInterface._call_openai

    def chaotic_anthropic(self, agent_config, model, messages, temperature, max_tokens, tools=None):
        if random.random() < rate:
            raise _make_fake_503(model)
        return original_anthropic(self, agent_config, model, messages, temperature, max_tokens, tools)

    def chaotic_openai(self, agent_config, model, messages, temperature, max_tokens, tools=None):
        if random.random() < rate:
            raise _make_fake_503(model)
        return original_openai(self, agent_config, model, messages, temperature, max_tokens, tools)

    ModelInterface._call_anthropic = chaotic_anthropic
    ModelInterface._call_openai = chaotic_openai


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject random model-call failures and run sample questions through MASE.")
    parser.add_argument("--rate", type=float, default=0.5, help="Failure injection probability per call (0.0-1.0)")
    parser.add_argument("--questions-file", default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    install_chaos(args.rate)

    if args.questions_file:
        questions = [q for q in open(args.questions_file, encoding="utf-8").read().splitlines() if q.strip()]
    else:
        questions = DEFAULT_QUESTIONS

    system = MASESystem()
    results = []
    start = time.time()
    for q in questions:
        t0 = time.time()
        try:
            ans = system.ask(q, log=False)
            results.append({"question": q, "ok": True, "latency_s": round(time.time() - t0, 2), "answer_chars": len(ans)})
        except Exception as exc:  # noqa: BLE001
            results.append({"question": q, "ok": False, "latency_s": round(time.time() - t0, 2), "error": repr(exc)[:200]})

    summary = {
        "rate": args.rate,
        "n": len(questions),
        "ok": sum(1 for r in results if r["ok"]),
        "elapsed_s": round(time.time() - start, 2),
        "candidate_health": get_tracker().snapshot(),
        "details": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] == summary["n"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
