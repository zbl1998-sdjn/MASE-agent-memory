"""
MASE 2.0 — Example 03: Research Agent (Cross-Document QA)
喂一组文档, 跨文档问答. 打 RAGFlow 痛处: 不需要切片, 不需要向量化, 不需要重排.

工作流:
  1. 把每个 PDF/Markdown/txt 喂给 BenchmarkNotetaker 的 write()
  2. SQLite FTS5 自动建索引 (毫秒级)
  3. 提问时 MASE 走 search_memory 路线召回, 由 executor 综合答复

跑法:
    # 把 PDF/MD/TXT 放到 ./examples/_corpus/ 目录, 然后:
    python examples/03_research_agent.py "What are the key findings about X?"

支持: .txt, .md (PDF 需先 pip install pypdf 并解开下方注释)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import BenchmarkNotetaker, mase_ask  # noqa: E402


def load_corpus(corpus_dir: Path) -> list[tuple[str, str]]:
    docs: list[tuple[str, str]] = []
    for p in sorted(corpus_dir.rglob("*")):
        if p.suffix.lower() in {".txt", ".md"}:
            docs.append((p.name, p.read_text(encoding="utf-8", errors="ignore")))
        # PDF 支持: pip install pypdf, 然后解开下面三行
        # elif p.suffix.lower() == ".pdf":
        #     from pypdf import PdfReader
        #     docs.append((p.name, "\n".join(pg.extract_text() or "" for pg in PdfReader(p).pages)))
    return docs


def ingest(docs: list[tuple[str, str]]) -> None:
    nt = BenchmarkNotetaker()
    for name, text in docs:
        chunk_size = 4000
        for i in range(0, len(text), chunk_size):
            nt.write(
                user_query=f"[corpus:{name}#{i}]",
                assistant_response=text[i:i + chunk_size],
                summary=f"document chunk from {name}",
                key_entities=[name],
                thread_id=f"corpus::{name}",
            )
    print(f"已写入 {len(docs)} 个文档到 SQLite (FTS5 自动建索引).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="总结这批文档的核心观点.")
    ap.add_argument("--corpus", default=str(ROOT / "examples" / "_corpus"))
    ap.add_argument("--no-ingest", action="store_true",
                    help="跳过写入步骤 (假设已经 ingest 过)")
    args = ap.parse_args()

    corpus_dir = Path(args.corpus)
    if not args.no_ingest:
        corpus_dir.mkdir(parents=True, exist_ok=True)
        docs = load_corpus(corpus_dir)
        if not docs:
            print(f"⚠️  {corpus_dir} 为空. 放几个 .txt/.md 进去再跑.")
            return
        ingest(docs)

    print(f"\nQ: {args.question}")
    print(f"A: {mase_ask(args.question)}")


if __name__ == "__main__":
    main()
