from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from itertools import count
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.runner import _aggregate_call_log, _ingest_context_into_mase
from mase import MASESystem

_REQUEST_COUNTER = count(1)
_MASE_LOCK: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _MASE_LOCK
    if _MASE_LOCK is None:
        _MASE_LOCK = asyncio.Lock()
    return _MASE_LOCK


def _parse_nolima_prompt(prompt: str) -> dict[str, str]:
    normalized = str(prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    question = normalized.strip()
    haystack = ""
    if "Question:" in normalized:
        prefix, suffix = normalized.rsplit("Question:", 1)
        question = suffix.strip()
        for marker in (
            "\n\n Return only",
            "\n\nReturn only",
            "\n\nAnswer only",
            "\n\nLet's think",
            "\n\nPlease answer",
        ):
            if marker in question:
                question = question.split(marker, 1)[0].strip()
        header_marker = "following book snippet:\n\n"
        if header_marker in prefix:
            haystack = prefix.split(header_marker, 1)[1]
        else:
            haystack = prefix
        for marker in (
            "\n\nUse the information provided",
            "\n\nAnswer the question",
            "\n\nBased on the information",
        ):
            if marker in haystack:
                haystack = haystack.split(marker, 1)[0].strip()
                break
    return {
        "haystack": haystack.strip(),
        "question": question.strip() or normalized.strip(),
    }


class MaseNoLiMaAdapter:
    def __init__(
        self,
        config_path: str | None = None,
        workspace_root: str | None = None,
        mode: str = "memory_ingest",
    ) -> None:
        self.config_path = str(Path(config_path).resolve()) if config_path else None
        default_root = REPO_ROOT / "external-benchmarks" / "NoLiMa" / "outputs" / "mase" / "case_memory"
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else default_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.mode = mode

    def _run_once(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        add_default_system_prompt: bool,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        parsed = _parse_nolima_prompt(user_prompt)
        digest = hashlib.sha1(user_prompt.encode("utf-8")).hexdigest()[:12]
        case_dir = self.workspace_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{next(_REQUEST_COUNTER):04d}-{digest}"
        case_dir.mkdir(parents=True, exist_ok=True)
        request_meta = {
            "mode": self.mode,
            "system_prompt": system_prompt,
            "question": parsed["question"],
            "haystack_char_length": len(parsed["haystack"]),
            "user_prompt_char_length": len(user_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "add_default_system_prompt": add_default_system_prompt,
        }
        (case_dir / "adapter_request.json").write_text(json.dumps(request_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        previous_memory_dir = os.environ.get("MASE_MEMORY_DIR")
        previous_benchmark_profile = os.environ.get("MASE_BENCHMARK_PROFILE")
        os.environ["MASE_MEMORY_DIR"] = str(case_dir)
        os.environ["MASE_BENCHMARK_PROFILE"] = "nolima_memory_ingest"
        try:
            system = MASESystem(self.config_path)
            system.model_interface.reset_call_log()

            answer = ""
            route_action = None
            keywords: list[str] = []
            if self.mode == "memory_ingest" and parsed["haystack"] and parsed["question"]:
                _ingest_context_into_mase(system, parsed["haystack"])
                answer = system.call_executor(
                    user_question=parsed["question"],
                    fact_sheet=parsed["haystack"],
                    allow_general_knowledge=False,
                    task_type="grounded_answer",
                    use_memory=True,
                    executor_role="reasoning",
                )
                route_action = "search_memory"
                keywords = ["__FULL_QUERY__"]
            else:
                trace = system.run_with_trace(user_prompt, log=False)
                answer = trace.answer
                route_action = trace.route.action
                keywords = list(trace.route.keywords)

            metrics = _aggregate_call_log(system.model_interface.get_call_log())
            metrics["wall_clock_seconds"] = round(time.perf_counter() - started, 6)

            result = {
                "response": str(answer or "").strip(),
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "finish_reason": "stop",
                "cached_tokens": None,
                "route_action": route_action,
                "keywords": keywords,
                "case_memory_dir": str(case_dir),
                "metrics": metrics,
            }
            (case_dir / "adapter_response.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        except Exception as error:
            result = {
                "response": "",
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "finish_reason": "error",
                "cached_tokens": None,
                "error": f"{type(error).__name__}: {error}",
                "case_memory_dir": str(case_dir),
            }
            (case_dir / "adapter_response.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        finally:
            if previous_memory_dir is None:
                os.environ.pop("MASE_MEMORY_DIR", None)
            else:
                os.environ["MASE_MEMORY_DIR"] = previous_memory_dir
            if previous_benchmark_profile is None:
                os.environ.pop("MASE_BENCHMARK_PROFILE", None)
            else:
                os.environ["MASE_BENCHMARK_PROFILE"] = previous_benchmark_profile

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.0,
        top_p: float = 1.0,
        add_default_system_prompt: bool = True,
    ) -> dict[str, Any]:
        async with _get_lock():
            return await asyncio.to_thread(
                self._run_once,
                system_prompt,
                user_prompt,
                max_tokens,
                temperature,
                top_p,
                add_default_system_prompt,
            )
