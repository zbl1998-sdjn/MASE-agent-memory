"""Generate NoLiMa chunked-vs-baseline chart for README.

Numbers from results/external/phase_a_summary.jsonl:
  baseline (full haystack into prompt as fact_sheet):
    4k=100.00 / 8k=51.79 / 16k=48.21 / 32k=1.79
  chunked (true MASE chunk+retrieve+executor):
    4k=100.00 / 8k=100.00 / 16k=75.00 / 32k=60.71
"""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

CTX = ["4k", "8k", "16k", "32k"]
BASELINE = [100.00, 51.79, 48.21, 1.79]
CHUNKED  = [100.00, 100.00, 75.00, 60.71]

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "nolima_chunked_vs_baseline.png"
OUT.parent.mkdir(parents=True, exist_ok=True)

x = np.arange(len(CTX))
w = 0.36

fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=140)
b1 = ax.bar(x - w/2, BASELINE, w,
            label="Baseline (dump full haystack as fact_sheet)",
            color="#bcbcbc", edgecolor="#7a7a7a")
b2 = ax.bar(x + w/2, CHUNKED, w,
            label="MASE chunked (chunk -> retrieve -> executor)",
            color="#2a7ae2", edgecolor="#1a4f9b")

for rect, val in list(zip(b1, BASELINE)) + list(zip(b2, CHUNKED)):
    ax.text(rect.get_x() + rect.get_width() / 2, val + 1.2,
            f"{val:.1f}", ha="center", va="bottom", fontsize=9)

for i, (b, c) in enumerate(zip(BASELINE, CHUNKED)):
    d = c - b
    if d > 0.5:
        ax.annotate(f"+{d:.1f}pp",
                    xy=(i + w/2, c),
                    xytext=(i + w/2 + 0.02, c + 6),
                    fontsize=9, color="#1a7f2f", fontweight="bold")

ax.set_ylim(0, 115)
ax.set_xticks(x)
ax.set_xticklabels(CTX)
ax.set_xlabel("Haystack length (NoLiMa needle_set_ONLYDirect, depth=50%, qwen2.5:7b)")
ax.set_ylabel("Accuracy (%)")
ax.set_title("MASE chunked retrieval breaks the 7B base-model context cliff\n"
             "(56 needles per length, single-pass executor, no fine-tuning)")
ax.legend(loc="lower left", framealpha=0.95, fontsize=9)
ax.grid(axis="y", alpha=0.25, linestyle="--")
ax.set_axisbelow(True)

fig.tight_layout()
fig.savefig(OUT, bbox_inches="tight")
print(f"wrote {OUT}")
