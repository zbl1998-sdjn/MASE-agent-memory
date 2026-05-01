# Pre-Publish Checklist

Run through this **once** before going public. Everything is automated by `scripts/publish_to_github.ps1` except the secret scan.

## 🔒 Step 0 — Secret scan (MANUAL, do this first)

> Before publishing, verify all headline benchmark claims are covered by a tracked claim manifest
> in `docs/benchmark_claims/`. Run `pytest tests/test_benchmark_claim_manifest.py -q` to confirm.

```powershell
cd C:\path\to\MASE
# Search for accidentally-committed API keys
Select-String -Path . -Pattern "sk-[A-Za-z0-9]{20,}|ZHIPU_API_KEY\s*=\s*[A-Za-z]|MOONSHOT_API_KEY\s*=\s*[A-Za-z]" -Recurse -Exclude "*.md","*.log","*.json" | Select-Object -First 10
```

If anything pops up that ISN'T `os.environ.get(...)` or doc references, **stop and scrub** before proceeding.

`.env` and `*.key` are in `.gitignore` — verify by running `git status` after `git init`.

## 📜 Step 1 — License

✅ `LICENSE` (Apache-2.0, copyright zbl1998-sdjn 2026)

If you want MIT instead, replace the file before commit. Apache-2.0 is recommended because:
- Includes patent grant (MASE has novel architecture claims)
- Compatible with most enterprise users
- Permissive enough that it won't scare contributors

## 🚀 Step 2 — Run the publish script

```powershell
gh auth login   # one-time
.\scripts\publish_to_github.ps1
```

This single script does:
1. `git init` + first commit
2. `gh repo create --public`
3. `git push -u origin main`
4. Add 20 topic tags (see list below)
5. Set description

## 🏷️ Topic tags (already in the script)

```
llm, agent, memory, long-context, rag, sqlite, ollama, qwen,
local-llm, memory-management, hallucination, longmemeval, nolima,
lv-eval, context-window, ai-agent, vector-database-alternative,
mcp, obsidian, langchain
```

These cover all main discovery paths:
- "long context" / "context window" — for the NoLiMa angle
- "memory" / "memory-management" — for the agent-memory crowd
- "vector-database-alternative" — for people Googling alternatives to Chroma/Pinecone
- "longmemeval" / "nolima" / "lv-eval" — for benchmark searchers
- "ollama" / "qwen" / "local-llm" — for local-LLM hobbyists
- "mcp" — for Claude Desktop / Cursor users
- "langchain" — for ecosystem search

## 🎯 Step 3 — Post-publish polish (5 min)

After `gh repo view --web` opens in your browser:

- [ ] Check the rendered README — confirm `docs/assets/banner.png` and `docs/assets/nolima_3way_lineplot.png` show
- [ ] In the repo's About section (right sidebar), click ⚙ and ensure **"Releases"** + **"Packages"** are unticked, **"Deployments"** unticked. Just keep description + topics.
- [ ] Pin the NoLiMa 3-way image in the README (already there at line ~42)
- [ ] Open the first issue yourself: **"👋 Welcome — start with examples/10_persistent_chat_cli.py"**
  - This signals the project is alive and gives drive-by visitors something to click

## 📣 Step 4 — Launch

Use `docs/LAUNCH_COPY.md`:

- **Tweet first** (your own account, then RT from any project handle)
- **Wait 2-4 hours**, then post HN. Best window: Tuesday/Wednesday 8:30am PT (00:30 Beijing next day)
- **Reddit r/LocalLLaMA** can go up at the same time as HN — different audience

## ⏰ Step 5 — Be present for the first 4 hours after launch

If HN front-pages, you'll get questions. Have these ready:

| Q | Quick answer |
|---|---|
| "Is this a vector DB wrapper?" | No — pure SQLite + FTS5, schema-less. No embeddings stored at rest. |
| "Why not just use mem0/Letta?" | They target chat history, MASE targets raw long-context (NoLiMa). Different battlefields — see docs/NOLIMA_3WAY.md |
| "Does it support Claude/GPT-4?" | Yes — `MASE_CONFIG_PATH=config.lme_glm5.json` swaps the model set. Default is local Ollama. |
| "Will it work on Linux/Mac?" | Yes — `MASE_DB_PATH` env removes the previously-hardcoded Windows path. |
| "What about hallucination?" | iron-rule prompt + grounded verifier; see ablation in docs/ADAPTIVE_VERIFY.md |
| "Why not headline the 84.8% LongMemEval run?" | Because it is a post-hoc combined/retry diagnostic. The publishable lanes are 61.0% official substring and 80.2% LLM-judge; the architectural win is NoLiMa 32k +58.9pp. |

Don't engage trolls. Reply to genuine questions within 30 min. Star count grows during this window or never.

---

## 🚨 If something breaks mid-launch

```powershell
# Make repo private again FAST
gh repo edit --visibility private --accept-visibility-change-consequences
```

Then debug, then re-publish.
