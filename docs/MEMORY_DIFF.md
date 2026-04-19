# `mase memory diff` — inspect tri-vault changes

The tri-vault is a three-bucket directory tree (`context/`, `sessions/`,
`state/`) that mirrors MASE's SQLite memory writes onto disk so you can
`git diff` how memory evolves over time. The `mase memory diff` subcommand is
the high-level UX for that.

## Enable tri-vault

It's opt-in. Set two env vars before running MASE:

```bash
export MASE_MEMORY_LAYOUT=tri
export MASE_MEMORY_VAULT=/absolute/path/to/your/memory   # optional, defaults to <project>/memory
```

When `MASE_MEMORY_LAYOUT` is unset (the default), MASE behaves exactly as
before — no JSON files are written, and `mase memory diff` has nothing to show.

After the first notetaker write you should see, for example:

```
memory/
├── README.md
├── context/
│   └── user_preferences__language.json
├── sessions/
│   └── t-1__1714000000000__user.json
└── state/
```

## Run a diff

```bash
python -m mase_tools.cli memory diff [--from REF] [--to REF] [--vault PATH]
```

Flags:

| flag      | default                                                     | meaning |
| --------- | ----------------------------------------------------------- | ------- |
| `--from`  | previous git commit touching the vault dir (git mode), or the second-newest snapshot (snapshot mode) | source ref |
| `--to`    | working tree (git mode), or the live vault (snapshot mode)  | target ref |
| `--vault` | `$MASE_MEMORY_VAULT` or `<project-root>/memory`             | vault root |

Two backends, auto-detected:

- **git mode** — when the vault is inside a git working tree, the command
  shells out to `git diff <from> <to> -- <vault>`.
- **snapshot mode** — when it isn't, it compares two `snapshots/<name>/`
  directories under the vault (or the live tree, via `--to WORKING`).

## Sample output

```
$ python -m mase_tools.cli memory diff
# tri-vault diff (git): a1b2c3d -> WORKING
# vault: /repo/memory
  context: +3 -1
  sessions: +12 -0
  state: +0 -0

diff --git a/memory/context/user_preferences__language.json b/memory/context/user_preferences__language.json
index 1234567..89abcde 100644
--- a/memory/context/user_preferences__language.json
+++ b/memory/context/user_preferences__language.json
@@ -1,5 +1,5 @@
 {
   "key": "user_preferences__language",
-  "payload": { "tool": "mase2_upsert_fact", "arguments": { "value": "en" } },
+  "payload": { "tool": "mase2_upsert_fact", "arguments": { "value": "zh" } },
   "updated_at": "2026-04-15T12:00:00Z"
 }
```

The first block is the bucket roll-up (handy for at-a-glance "did anything
durable change?" checks); the per-file diffs follow.

## How writes get mirrored

`NotetakerAgent.execute_tool_call(...)` calls `tri_vault.mirror_write(bucket,
key, payload)` after each successful SQLite-backed tool invocation. Mapping:

| notetaker tool             | bucket     |
| -------------------------- | ---------- |
| `mase2_write_interaction`  | `sessions` |
| `mase2_upsert_fact`        | `context`  |
| `mase2_correct_and_log`    | `state`    |
| `mase2_supersede_facts`    | `state`    |
| read-only tools (`get_*`, `search_*`) | *(not mirrored)* |

Mirror writes are atomic (`*.tmp` then `os.replace`) and best-effort: a vault
write failure never breaks the primary SQLite memory path.
