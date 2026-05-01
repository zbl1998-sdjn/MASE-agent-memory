"""Plot NoLiMa 3-way comparison: NoLiMa-paper baselines vs MASE chunked vs MASE single-pass.

Reads MASE numbers from results/external/phase_a_summary.jsonl and overlays publicly
reported NoLiMa needle-set (ONLYDirect / "base score") accuracies from the NoLiMa paper
(Modarressi et al., 2025, arXiv:2502.05167) for context.

Output: docs/assets/nolima_3way_lineplot.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "external" / "phase_a_summary.jsonl"
OUT = ROOT / "docs" / "assets" / "nolima_3way_lineplot.png"

CONTEXTS = [4096, 8192, 16384, 32768]
XLABELS = ["4k", "8k", "16k", "32k"]


def load_mase() -> tuple[list[float], list[float]]:
    """Return (single_pass, chunked) accuracy lists aligned to CONTEXTS, in %."""
    single: dict[int, float] = {}
    chunked: dict[int, float] = {}
    with SUMMARY.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            task = row.get("task")
            ctx = row.get("context_length")
            acc = row.get("accuracy")
            if not isinstance(ctx, int) or not isinstance(acc, int | float):
                continue
            if task == "nolima_ONLYDirect":
                single[ctx] = float(acc) * 100.0
            elif task == "nolima_ONLYDirect_chunked":
                chunked[ctx] = float(acc) * 100.0
    return (
        [single.get(c, float("nan")) for c in CONTEXTS],
        [chunked.get(c, float("nan")) for c in CONTEXTS],
    )


# Public NoLiMa-paper numbers (Modarressi et al., 2025; Table 1, "base score" / needle-set %).
# Frontier proprietary + large open models, included for context only — not apples-to-apples
# with our local 7B run, but they bracket what state-of-the-art looks like on the same task.
PAPER_BASELINES = {
    "GPT-4o (paper)":        {4096: 95.7, 8192: 89.2, 16384: 81.6, 32768: 69.7},
    "Llama 3.3 70B (paper)": {4096: 87.4, 8192: 81.5, 16384: 72.1, 32768: 59.5},
    "Llama 3.1 70B (paper)": {4096: 88.1, 8192: 71.6, 16384: 51.9, 32768: 25.5},
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    single, chunked = load_mase()

    fig, ax = plt.subplots(figsize=(9, 5.5))

    for label, vals in PAPER_BASELINES.items():
        ax.plot(
            XLABELS,
            [vals[c] for c in CONTEXTS],
            marker="o",
            linestyle="--",
            alpha=0.55,
            linewidth=1.6,
            label=label,
        )

    ax.plot(
        XLABELS, single, marker="s", linewidth=2.2, color="#888",
        label="MASE single-pass — qwen2.5:7b (ours)",
    )
    ax.plot(
        XLABELS, chunked, marker="D", linewidth=3.0, color="#d62728",
        label="MASE chunked — qwen2.5:7b (ours)",
    )

    for x, y in zip(XLABELS, chunked):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=9, color="#d62728")
    for x, y in zip(XLABELS, single):
        ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points",
                    xytext=(0, -14), ha="center", fontsize=8, color="#555")

    ax.set_ylim(0, 105)
    ax.set_xlabel("Context length")
    ax.set_ylabel("NoLiMa needle-set accuracy (%)")
    ax.set_title(
        "NoLiMa needle-in-haystack: MASE chunked (7B local) vs paper baselines\n"
        "Same benchmark (ONLYDirect / base score), different model classes — read with care",
        fontsize=11,
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower left", fontsize=9, framealpha=0.95)
    fig.tight_layout()
    fig.savefig(OUT, dpi=140)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
