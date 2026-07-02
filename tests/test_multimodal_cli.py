"""ingest CLI:参数解析、退出码、报告打印。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.ingest import IngestReport


def _fake_report(**overrides):
    base = dict(processed=("a.png",), skipped=(), infra_errors=(), extractions=1, facts_written=2)
    base.update(overrides)
    return IngestReport(**base)


def test_cli_invokes_ingest_and_returns_zero(tmp_path, monkeypatch, capsys):
    from mase.multimodal import cli

    captured = {}

    def fake_ingest(folder, **kwargs):
        captured["folder"] = Path(folder)
        captured.update(kwargs)
        return _fake_report()

    monkeypatch.setattr(cli, "ingest_folder", fake_ingest)
    docs = tmp_path / "docs"
    docs.mkdir()
    code = cli.main([str(docs), "--mode", "minicpm", "--force"])
    assert code == 0
    assert captured["folder"] == docs
    assert captured["mode"] == "minicpm" and captured["force"] is True
    out = capsys.readouterr().out
    assert "processed=1" in out and "facts=2" in out


def test_cli_returns_one_on_infra_errors(tmp_path, monkeypatch):
    from mase.multimodal import cli

    monkeypatch.setattr(
        cli, "ingest_folder",
        lambda folder, **kw: _fake_report(infra_errors=({"file": "x.png", "error": "boom"},)),
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    assert cli.main([str(docs)]) == 1


def test_cli_rejects_missing_folder(tmp_path):
    from mase.multimodal import cli

    assert cli.main([str(tmp_path / "nope")]) == 2


def test_cli_passes_whisper_model(tmp_path, monkeypatch):
    from mase.multimodal import cli

    captured = {}
    monkeypatch.setattr(cli, "ingest_folder", lambda folder, **kw: (captured.update(kw), _fake_report())[1])
    docs = tmp_path / "docs"
    docs.mkdir()
    assert cli.main([str(docs), "--whisper-model", "large-v3-turbo"]) == 0
    assert captured["whisper_model"] == "large-v3-turbo"
