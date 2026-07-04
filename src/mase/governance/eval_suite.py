"""Deterministic memory-governance eval suite(P7).

Eval 只使用本地 facts/evidence 审计链:compile Evidence Pack → verify answer →
保存 sample/prompt/code hash。报告明确按 lane 区分 deterministic、anti_poisoning、
stale_conflict 等口径,避免把 diagnostic/best-of 混成发布分数。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .claim_verifier import verify_answer
from .evidence_pack import compile_evidence_pack

DEFAULT_CODE_HASH = hashlib.sha256(b"mase-governance-eval.v1").hexdigest()


@dataclass(frozen=True)
class GovernanceEvalCase:
    """一条治理 eval 样本。"""

    case_id: str
    lane: str
    query: str
    keywords: tuple[str, ...]
    answer: str
    expected_verdict: str
    expected_terms: tuple[str, ...] = ()
    blocked_terms: tuple[str, ...] = ()
    mode: str = "single-run"


@dataclass(frozen=True)
class GovernanceEvalResult:
    """一条 eval 结果;hash 字段用于发布证据回放。"""

    case_id: str
    lane: str
    mode: str
    verdict: str
    expected_verdict: str
    passed: bool
    sample_hash: str
    prompt_hash: str
    code_hash: str
    trace_id: str
    violation_count: int
    failure_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return this eval result in JSON-serializable form."""
        return asdict(self)


def run_governance_eval(
    cases: list[GovernanceEvalCase],
    *,
    db_path: str | Path | None = None,
    code_hash: str = DEFAULT_CODE_HASH,
) -> dict[str, Any]:
    """运行核心治理 eval,返回 summary/results/failure_gallery。"""
    results: list[GovernanceEvalResult] = []
    for case in cases:
        pack = compile_evidence_pack(
            case.query,
            list(case.keywords),
            db_path=db_path,
        )
        audit = verify_answer(case.answer, pack, db_path=db_path)
        reasons = _failure_reasons(case, audit.verdict, case.answer)
        result = GovernanceEvalResult(
            case_id=case.case_id,
            lane=case.lane,
            mode=case.mode,
            verdict=audit.verdict,
            expected_verdict=case.expected_verdict,
            passed=not reasons,
            sample_hash=_hash_case(case),
            prompt_hash=_prompt_hash(case),
            code_hash=code_hash,
            trace_id=audit.trace_id,
            violation_count=len(audit.violations),
            failure_reasons=tuple(reasons),
        )
        results.append(result)
    return {
        "summary": summarize_results(results),
        "results": [result.to_dict() for result in results],
        "failure_gallery": failure_gallery(results),
    }


def summarize_results(results: list[GovernanceEvalResult]) -> dict[str, Any]:
    """Aggregate eval pass/fail counts globally and by lane."""
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    by_lane: dict[str, dict[str, Any]] = {}
    for result in results:
        lane = by_lane.setdefault(
            result.lane,
            {"case_count": 0, "passed_count": 0, "failed_count": 0, "pass_rate": 1.0},
        )
        lane["case_count"] += 1
        lane["passed_count"] += 1 if result.passed else 0
        lane["failed_count"] += 0 if result.passed else 1
        lane["pass_rate"] = lane["passed_count"] / lane["case_count"]
    return {
        "case_count": total,
        "passed_count": passed,
        "failed_count": total - passed,
        "pass_rate": (passed / total) if total else 1.0,
        "by_lane": by_lane,
        "release_gate": "passed" if total == passed else "failed",
    }


def failure_gallery(results: list[GovernanceEvalResult]) -> list[dict[str, Any]]:
    """失败样本画廊:只收失败项,便于报告直接定位。"""
    return [
        {
            "case_id": result.case_id,
            "lane": result.lane,
            "mode": result.mode,
            "verdict": result.verdict,
            "expected_verdict": result.expected_verdict,
            "sample_hash": result.sample_hash,
            "prompt_hash": result.prompt_hash,
            "trace_id": result.trace_id,
            "failure_reasons": list(result.failure_reasons),
        }
        for result in results
        if not result.passed
    ]


def render_eval_report(payload: dict[str, Any]) -> str:
    """Markdown 报告生成器;报告中显式区分 lane/mode/hash。"""
    summary = payload["summary"]
    lines = [
        "# MASE Memory Governance Eval Report",
        "",
        f"- release_gate: {summary['release_gate']}",
        f"- case_count: {summary['case_count']}",
        f"- pass_rate: {summary['pass_rate']:.3f}",
        "",
        "## Lanes",
    ]
    for lane, row in sorted(summary["by_lane"].items()):
        lines.append(
            f"- {lane}: {row['passed_count']}/{row['case_count']} pass, "
            f"failed={row['failed_count']}, pass_rate={row['pass_rate']:.3f}"
        )
    lines += ["", "## Results"]
    for result in payload["results"]:
        lines.append(
            "- "
            f"{result['case_id']} lane={result['lane']} mode={result['mode']} "
            f"passed={result['passed']} verdict={result['verdict']} "
            f"sample_hash={result['sample_hash'][:12]} "
            f"prompt_hash={result['prompt_hash'][:12]} "
            f"code_hash={result['code_hash'][:12]}"
        )
    lines += ["", "## Failure Gallery"]
    if payload["failure_gallery"]:
        for failure in payload["failure_gallery"]:
            lines.append(
                f"- {failure['case_id']}({failure['lane']}): "
                + "; ".join(str(reason) for reason in failure["failure_reasons"])
            )
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def _failure_reasons(case: GovernanceEvalCase, verdict: str, answer: str) -> list[str]:
    reasons: list[str] = []
    if verdict != case.expected_verdict:
        reasons.append(f"verdict {verdict!r} != expected {case.expected_verdict!r}")
    for term in case.expected_terms:
        if term not in answer:
            reasons.append(f"missing expected term {term!r}")
    for term in case.blocked_terms:
        if term in answer:
            reasons.append(f"blocked term present {term!r}")
    return reasons


def _hash_case(case: GovernanceEvalCase) -> str:
    encoded = json.dumps(asdict(case), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prompt_hash(case: GovernanceEvalCase) -> str:
    return hashlib.sha256(f"{case.query}\n{case.answer}".encode()).hexdigest()
