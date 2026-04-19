"""``mase memory diff`` — show what changed in the tri-vault between two refs.

Two backends:

1. **git mode** — when the vault directory lives inside a git working tree,
   shell out to ``git diff <from> <to> -- <vault>``. ``--from`` defaults to the
   most recent commit that touched the vault dir; ``--to`` defaults to ``HEAD``
   (or the working tree if ``HEAD`` is the from-ref).

2. **snapshot mode** — when the vault is *not* under git control, compare two
   timestamped snapshot directories inside the vault (``snapshots/<ts>/``).
   ``--from`` / ``--to`` then accept a snapshot name or the literal ``WORKING``
   to mean the live tri-vault tree.

Output is bucket-rolled-up first ("context: +3 -1"), then full per-file diffs.
"""
from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path

from mase_tools.memory import tri_vault

BUCKETS = tri_vault.BUCKETS


# ---------------------------------------------------------------------------
# argparse glue
# ---------------------------------------------------------------------------

def add_memory_diff_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--from",
        dest="from_ref",
        default=None,
        help="Source ref. In git mode: a commit-ish (default: previous commit "
        "touching the vault). In snapshot mode: a snapshot dir name.",
    )
    parser.add_argument(
        "--to",
        dest="to_ref",
        default=None,
        help="Target ref. In git mode: a commit-ish (default: HEAD or working "
        "tree). In snapshot mode: a snapshot dir name or 'WORKING'.",
    )
    parser.add_argument(
        "--vault",
        dest="vault",
        default=None,
        help="Path to the memory vault. Defaults to $MASE_MEMORY_VAULT or "
        "<project-root>/memory.",
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _resolve_vault(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    env = os.environ.get(tri_vault.VAULT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    # Same default as tri_vault._vault_root().
    return (Path(__file__).resolve().parents[2] / "memory").resolve()


def _is_git_dir(path: Path) -> tuple[bool, Path | None]:
    """Return (is_in_git, repo_top) for ``path``."""
    if not path.exists():
        return False, None
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, None
    if out.returncode != 0:
        return False, None
    return True, Path(out.stdout.strip())


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_git_refs(repo: Path, vault: Path, from_ref: str | None, to_ref: str | None) -> tuple[str, str | None]:
    rel = vault.relative_to(repo).as_posix() or "."
    if from_ref is None:
        log = _git(repo, "log", "-n", "2", "--format=%H", "--", rel)
        commits = [c for c in log.stdout.split() if c]
        if len(commits) >= 2:
            from_ref = commits[1]
        elif commits:
            from_ref = commits[0] + "^"
        else:
            from_ref = "HEAD"
    # to_ref=None means working tree (git diff with single ref).
    return from_ref, to_ref


# ---------------------------------------------------------------------------
# git-mode diff
# ---------------------------------------------------------------------------

def _diff_git(repo: Path, vault: Path, from_ref: str, to_ref: str | None) -> int:
    rel = vault.relative_to(repo).as_posix() or "."
    refs = [from_ref] + ([to_ref] if to_ref else [])

    # Per-bucket counts via --numstat.
    numstat_args = ["diff", "--numstat", *refs, "--"]
    numstat_args += [f"{rel}/{b}" for b in BUCKETS]
    ns = _git(repo, *numstat_args)
    counts = {b: [0, 0] for b in BUCKETS}
    for line in ns.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds, dels, fname = parts[0], parts[1], parts[2]
        for b in BUCKETS:
            if fname.startswith(f"{rel}/{b}/") or fname.startswith(f"{b}/"):
                if adds.isdigit():
                    counts[b][0] += int(adds)
                if dels.isdigit():
                    counts[b][1] += int(dels)
                break

    print(f"# tri-vault diff (git): {from_ref} -> {to_ref or 'WORKING'}")
    print(f"# vault: {vault}")
    _print_bucket_summary(counts)
    print()

    # Full diff per bucket.
    full = _git(
        repo,
        "diff",
        *refs,
        "--",
        *[f"{rel}/{b}" for b in BUCKETS],
    )
    sys.stdout.write(full.stdout)
    if full.returncode not in (0, 1):
        sys.stderr.write(full.stderr)
        return full.returncode
    return 0


# ---------------------------------------------------------------------------
# snapshot-mode diff
# ---------------------------------------------------------------------------

def _list_snapshots(vault: Path) -> list[Path]:
    snap_root = vault / "snapshots"
    if not snap_root.is_dir():
        return []
    return sorted(p for p in snap_root.iterdir() if p.is_dir())


def _resolve_snapshot(vault: Path, ref: str | None, *, default_to_working: bool) -> Path:
    if ref is None:
        if default_to_working:
            return vault
        snaps = _list_snapshots(vault)
        if len(snaps) >= 2:
            return snaps[-2]
        if snaps:
            return snaps[-1]
        return vault
    if ref == "WORKING":
        return vault
    candidate = vault / "snapshots" / ref
    if candidate.is_dir():
        return candidate
    direct = Path(ref)
    if direct.is_dir():
        return direct
    raise SystemExit(f"snapshot ref not found: {ref}")


def _bucket_files(root: Path, bucket: str) -> dict[str, Path]:
    bucket_dir = root / bucket
    if not bucket_dir.is_dir():
        return {}
    out: dict[str, Path] = {}
    for p in sorted(bucket_dir.rglob("*.json")):
        out[p.relative_to(bucket_dir).as_posix()] = p
    return out


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return []


def _diff_snapshot(vault: Path, from_ref: str | None, to_ref: str | None) -> int:
    src = _resolve_snapshot(vault, from_ref, default_to_working=False)
    dst = _resolve_snapshot(vault, to_ref, default_to_working=True)

    counts = {b: [0, 0] for b in BUCKETS}
    diffs: list[str] = []
    for bucket in BUCKETS:
        src_files = _bucket_files(src, bucket)
        dst_files = _bucket_files(dst, bucket)
        keys = sorted(set(src_files) | set(dst_files))
        for key in keys:
            sl = _read_lines(src_files[key]) if key in src_files else []
            dl = _read_lines(dst_files[key]) if key in dst_files else []
            if sl == dl:
                continue
            adds = sum(1 for l in dl if l not in sl)
            dels = sum(1 for l in sl if l not in dl)
            counts[bucket][0] += adds
            counts[bucket][1] += dels
            label_src = f"a/{bucket}/{key}" if key in src_files else "/dev/null"
            label_dst = f"b/{bucket}/{key}" if key in dst_files else "/dev/null"
            diff = "".join(
                difflib.unified_diff(sl, dl, fromfile=label_src, tofile=label_dst)
            )
            diffs.append(diff)

    print(f"# tri-vault diff (snapshot): {src} -> {dst}")
    print(f"# vault: {vault}")
    _print_bucket_summary(counts)
    print()
    for d in diffs:
        sys.stdout.write(d)
    return 0


# ---------------------------------------------------------------------------
# pretty-print
# ---------------------------------------------------------------------------

def _print_bucket_summary(counts: dict[str, list[int]]) -> None:
    for bucket in BUCKETS:
        adds, dels = counts.get(bucket, [0, 0])
        print(f"  {bucket}: +{adds} -{dels}")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def run_memory_diff(args: argparse.Namespace) -> int:
    vault = _resolve_vault(getattr(args, "vault", None))
    if not vault.exists():
        print(f"vault directory does not exist: {vault}", file=sys.stderr)
        return 1
    in_git, repo = _is_git_dir(vault)
    if in_git and repo is not None:
        from_ref, to_ref = _resolve_git_refs(repo, vault, args.from_ref, args.to_ref)
        return _diff_git(repo, vault, from_ref, to_ref)
    return _diff_snapshot(vault, args.from_ref, args.to_ref)


__all__ = ["add_memory_diff_args", "run_memory_diff"]
