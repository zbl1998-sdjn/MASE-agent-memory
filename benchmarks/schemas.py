from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BenchmarkTaskType = Literal[
    "long_memory",
    "long_context_qa",
    "multiple_choice",
    "math",
    "code_generation",
    "qa",
]


@dataclass(frozen=True)
class BenchmarkTurn:
    role: Literal["user", "assistant"]
    content: str
    timestamp: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class BenchmarkSample:
    id: str
    benchmark: str
    task_type: BenchmarkTaskType
    question: str
    ground_truth: str
    history: list[BenchmarkTurn] = field(default_factory=list)
    context: str = ""
    options: list[str] = field(default_factory=list)
    answer_keywords: list[str] = field(default_factory=list)
    word_blacklist: list[str] = field(default_factory=list)
    entry_point: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "benchmark": self.benchmark,
            "task_type": self.task_type,
            "question": self.question,
            "ground_truth": self.ground_truth,
            "history": [turn.__dict__ for turn in self.history],
            "context": self.context,
            "options": self.options,
            "answer_keywords": self.answer_keywords,
            "word_blacklist": self.word_blacklist,
            "entry_point": self.entry_point,
            "metadata": self.metadata,
        }
