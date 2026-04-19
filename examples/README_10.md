# Example 10 — Persistent Chat CLI

The 60-line demo that proves MASE's two killer features in one terminal:

1. **Persistent long memory** — every turn is committed to SQLite (`data/mase_memory.db`).
   Kill the process, reboot the machine, run again — your facts are still there.
2. **Non-hallucination iron rule** — if you ask about something MASE never heard,
   it answers `I don't have that in memory.` instead of making things up.

## Run it

```bash
# First run — tell it some facts
python examples/10_persistent_chat_cli.py
> You: My brother is named Alex and he's a chef in Berlin.
> You: My cat is called Grape.
> You: ^C

# Restart — proves persistence
python examples/10_persistent_chat_cli.py
> Welcome back. I remember we were discussing: ...
> You: What did I tell you about my brother?
> MASE: Your brother Alex is a chef in Berlin.
> [memory: 3 facts retrieved | route: search_memory]

# Ask about something you NEVER said — proves grounding
> You: What's my sister's name?
> MASE: I don't have that in memory.
> [memory: 0 facts retrieved | route: search_memory]

# Start fresh
python examples/10_persistent_chat_cli.py --reset
```

## Configuration

Defaults to `qwen2.5:7b` via Ollama (see top-level `config.json`).
To swap models / providers, point `MASE_CONFIG_PATH` at your own config:

```bash
# Windows
set MASE_CONFIG_PATH=D:\my_configs\cloud.json
python examples/10_persistent_chat_cli.py

# Linux / macOS
MASE_CONFIG_PATH=~/my_configs/cloud.json python examples/10_persistent_chat_cli.py
```

## Footer line

After every reply you'll see:

```
[memory: <N> facts retrieved | route: <route_name>]
```

`N` is the number of memory rows the retriever pulled in for this turn;
`<route_name>` is the planner's chosen route (e.g. `search_memory`,
`direct_answer`). Watching these change is how you *see* MASE working.
