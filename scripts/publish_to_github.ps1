# MASE 2.0 — One-shot GitHub publish script (PRIVATE by default)
# Pre-requisites:
#   1. GitHub CLI installed: https://cli.github.com/
#   2. Logged in: `gh auth login`
#   3. You're at E:\MASE-demo
#
# What this does (in order):
#   1. git init + first commit
#   2. Create the GitHub repo (PRIVATE — flip to --public when ready)
#   3. Push code
#   4. Add topic tags
#   5. Set repo description + homepage

$ErrorActionPreference = "Stop"
Set-Location E:\MASE-demo

# ---- CONFIGURE THESE ----
$REPO_NAME = "MASE-demo"
$REPO_DESC = "Memory-Augmented Smart Entity 2.0 — Schema-less SQLite memory + chunked recall. Lifts 7B local models from 1.79% to 60.71% on NoLiMa-32k. 84.8% LongMemEval, ~0% hallucination."
$REPO_HOMEPAGE = ""  # optional, leave empty
# Topics: GitHub allows up to 20, each ≤35 chars, lowercase, hyphenated
$TOPICS = @(
    "llm",
    "agent",
    "memory",
    "long-context",
    "rag",
    "sqlite",
    "ollama",
    "qwen",
    "local-llm",
    "memory-management",
    "hallucination",
    "longmemeval",
    "nolima",
    "lv-eval",
    "context-window",
    "ai-agent",
    "vector-database-alternative",
    "mcp",
    "obsidian",
    "langchain"
)
# -------------------------

Write-Host "=== Step 1/5: git init ==="
if (-not (Test-Path .git)) {
    git init -b main
    git add .
    git -c user.email="zbl1998-sdjn@users.noreply.github.com" `
        -c user.name="zbl1998-sdjn" `
        commit -m "feat: initial public release — MASE 2.0

- Schema-less SQLite + Markdown dual-whitebox memory
- Chunked recall: 7B model lifts 1.79% -> 60.71% on NoLiMa-32k
- LV-Eval EN 256k 88.71%, LongMemEval-S 84.8% (LLM-judge)
- Tri-vault (context/sessions/state) + memory diff CLI
- Hybrid recall (BM25 + dense + temporal) opt-in
- Adaptive verification depth (skip/single/dual) opt-in
- 17/17 new tests passing

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
} else {
    Write-Host "  .git already exists, skipping init"
}

Write-Host ""
Write-Host "=== Step 2/5: Create GitHub repo (PRIVATE) ==="
$existing = gh repo view "$REPO_NAME" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Repo already exists — skipping create"
} else {
    gh repo create "$REPO_NAME" --private --description "$REPO_DESC" --source . --remote origin
}

Write-Host ""
Write-Host "=== Step 3/5: Push to origin ==="
git branch -M main
git push -u origin main

Write-Host ""
Write-Host "=== Step 4/5: Add topic tags ==="
$topicArgs = @()
foreach ($t in $TOPICS) { $topicArgs += "--add-topic"; $topicArgs += $t }
gh repo edit @topicArgs

Write-Host ""
Write-Host "=== Step 5/5: Set description + homepage ==="
if ($REPO_HOMEPAGE -ne "") {
    gh repo edit --description "$REPO_DESC" --homepage "$REPO_HOMEPAGE"
} else {
    gh repo edit --description "$REPO_DESC"
}

Write-Host ""
Write-Host "✅ DONE. Open the repo:"
gh repo view --web
