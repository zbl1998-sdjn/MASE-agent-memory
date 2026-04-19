# Legacy Root-Level Shims

This document inventories the **18 root-level `*.py` files** that exist solely
for backwards compatibility with pre-V2 callers (typically downstream scripts
that did `from router import RouterAgent`, `from executor import ExecutorAgent`,
etc.). They are **not** active source files — every one of them just re-exports
the corresponding `mase.<name>` module via `sys.modules[__name__] = _impl`.

If you are reading the codebase to understand MASE V2, **ignore these files
entirely** and read the canonical implementations under `src/mase/` instead.

## Inventory (18 files)

| Root shim                       | Canonical implementation                       | Why kept                                                     |
| ------------------------------- | ---------------------------------------------- | ------------------------------------------------------------ |
| `executor.py`                   | `mase.executor`                                | Top-of-stack agent — heaviest external import surface.       |
| `router.py`                     | `mase.router`                                  | LLM router used by external orchestration scripts.           |
| `planner_agent.py`              | `mase.planner_agent` (+ legacy_archive merge)  | Restores `InstructionPackage` for legacy tests.              |
| `planner.py`                    | re-exports `legacy_archive.planner` symbols    | Legacy planning helpers consumed by V1 scripts only.         |
| `notetaker.py`                  | `mase.notetaker`                               | Markdown audit log writer.                                   |
| `notetaker_agent.py`            | `mase.notetaker_agent`                         | Background notetaker agent.                                  |
| `model_interface.py`            | `mase.model_interface`                         | LLM provider abstraction.                                    |
| `protocol.py`                   | `mase.protocol`                                | Inter-agent message types.                                   |
| `topic_threads.py`              | `mase.topic_threads`                           | Memory thread bucketing.                                     |
| `reasoning_engine.py`           | `mase.reasoning_engine`                        | LV-Eval / NoLiMa reasoning loop.                             |
| `langgraph_orchestrator.py`     | `mase.langgraph_orchestrator`                  | Modern orchestration entry point.                            |
| `event_versioning.py`           | `mase.event_versioning`                        | Event-stream schema versioning.                              |
| `event_bus.py`                  | re-exports `legacy_archive.event_bus`          | Pre-V2 event-bus snapshot consumer.                          |
| `memory_heat.py`                | re-exports `legacy_archive.memory_heat`        | Pre-V2 memory hotness scoring.                               |
| `memory_reflection.py`          | re-exports `legacy_archive.memory_reflection`  | Pre-V2 reflection/summarization helpers.                     |
| `orchestrator.py`               | re-exports `legacy_archive.orchestrator`       | Pre-V2 orchestrator (V2 = `langgraph_orchestrator`).         |
| `temporal_parser.py`            | re-exports `legacy_archive.temporal_parser`    | Pre-V2 date parser.                                          |
| `mase_cli.py`                   | `mase.mase_cli`                                | CLI entry point shim.                                        |

## Removal policy

These shims are slated for deletion in a future major version (post-1.0).
Until then they MUST stay because:

1. They are still imported by tests inside `tests/` and by scripts in
   `scripts/` and `benchmarks/` that pre-date the `src/` migration.
2. External users of MASE 0.x packaged the root names into their own code.

When deleting, follow this order: tests → scripts → external docs → shim file.

Auditors: when scanning the repo, the presence of one of these files at the
project root does **not** indicate active V2 logic. The file at
`src/mase/<same_name>.py` is the authoritative one.
