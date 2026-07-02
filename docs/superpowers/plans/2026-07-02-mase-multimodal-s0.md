# MASE S0 多模态摄取地基 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把企业文档/图像(png/jpg/webp/gif/PDF)经本地 VLM 确定性抽取为"全文 + 结构化事实",带完整溯源链写入现有白盒记忆管线(SQLite/FTS5 + entity_state),原始字节按内容哈希存入资产库。

**Architecture:** 新子包 `src/mase/multimodal/`(security → loader → extractor 协议 → vision 抽取器 → ingest 编排),存储侧 `mase_tools/media/asset_store.py`(内容寻址 blob)+ `mase_tools/memory/media_records.py`(溯源表 CRUD),`db_core.py` 只加 additive DDL。抽取器引擎无关,S0 仅接 Ollama(message 级 `images:[base64]` 兄弟字段)。

**Tech Stack:** Python 3.10+/sqlite3/httpx/ollama;可选依赖 PyMuPDF(`fitz`)做 PDF 栅格化;pytest;无新增必装依赖。

**Spec:** `docs/superpowers/specs/2026-07-02-mase-multimodal-s0-design.md`(已批准,决策以 spec §2 为准)。

## Global Constraints

- 提交信息 Conventional Commits(`feat:/fix:/test:/docs:/chore:`),门禁强制;**一特性一提交**;禁止 `--no-verify`。
- ⚠️ 本仓库 commit-msg 钩子对多行 `-m` 解析有坑:**多行消息一律写入临时文件用 `git commit -F <file>`**;单行可用 `-m`。提交尾行加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 每个任务:先写失败测试(红)→ 最小实现(绿)→ 提交。测试通过公共接口测行为,不锁私有实现。
- 测试隔离 DB:`monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "t.db"))`(现有套件模式)。
- 单元测试**不碰真模型**;真模型验收只在 Task 10 的 harness(integration/slow,不进默认套件)。
- 新代码进 `src/mase/multimodal/` 与 `mase_tools/media/`,不塞现有大文件;`db_core.py` 只允许加 DDL 与既有写函数的 nullable 参数。
- 运行测试命令统一:`python -m pytest tests/<file>.py -q`;全量:`python -m pytest -q -m "not integration and not slow"`(当前基线 641 passed)。
- Python 3.10 语法(`X | None`、`dataclass`);行宽 120;中文注释风格与仓库一致。
- 版本钉:`pymupdf>=1.24,<2.0`(仅 optional extra + dev)。
- 视觉模型名(验收用,写死为配置默认):`qwen2.5vl:7b`(默认)/`minicpm-v:4.5`(mode=minicpm)。

---

### Task 1: 溯源 schema + media_records CRUD

**Files:**
- Modify: `mase_tools/memory/db_core.py`(`_create_legacy_schema` 内加 DDL;约 line 611 session_context 索引之后、函数末尾 commit 之前)
- Create: `mase_tools/memory/media_records.py`
- Test: `tests/test_media_records.py`

**Interfaces:**
- Consumes: `db_core.get_connection(db_path=None)`、`db_core._normalize_scope_value`
- Produces(后续任务依赖的精确签名):
  - `register_media_asset(sha256: str, *, source_uri: str | None, media_type: str, byte_size: int | None = None, page_count: int | None = None, tenant_id: str | None = None, workspace_id: str | None = None, db_path=None) -> int`(同 sha256+scope 幂等返回已有 id)
  - `get_media_asset(media_id: int | None = None, *, sha256: str | None = None, tenant_id=None, workspace_id=None, db_path=None) -> dict | None`
  - `record_extraction(media_id: int, *, extractor_name: str, model_name: str, extractor_version: str, full_text: str, result_json: str, tenant_id=None, workspace_id=None, db_path=None) -> int`
  - `find_extraction(media_id: int, *, extractor_name: str, extractor_version: str, db_path=None) -> dict | None`
  - `get_media_provenance(media_id: int, *, db_path=None) -> dict`(形如 `{"asset": {...} | None, "extractions": [ {...}, ... ]}`,extractions 按 created_at DESC)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_media_records.py
"""media_asset / media_extraction 溯源表 CRUD 行为测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "media.db"))


def test_register_media_asset_is_idempotent_per_hash(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.media_records import get_media_asset, register_media_asset

    first = register_media_asset("a" * 64, source_uri="docs/inv.png", media_type="image/png", byte_size=123)
    second = register_media_asset("a" * 64, source_uri="docs/other.png", media_type="image/png", byte_size=123)
    assert first == second  # 同哈希同 scope 幂等

    row = get_media_asset(first)
    assert row is not None
    assert row["sha256"] == "a" * 64
    assert row["media_type"] == "image/png"
    assert get_media_asset(sha256="a" * 64)["id"] == first


def test_register_media_asset_scoped_by_tenant(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.media_records import register_media_asset

    base = register_media_asset("b" * 64, source_uri=None, media_type="application/pdf")
    other = register_media_asset("b" * 64, source_uri=None, media_type="application/pdf", tenant_id="acme")
    assert base != other  # 不同租户不共享资产行


def test_record_and_find_extraction_and_provenance(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.media_records import (
        find_extraction,
        get_media_provenance,
        record_extraction,
        register_media_asset,
    )

    media_id = register_media_asset("c" * 64, source_uri="scan.pdf", media_type="application/pdf", page_count=2)
    assert find_extraction(media_id, extractor_name="vision", extractor_version="1") is None

    ext_id = record_extraction(
        media_id,
        extractor_name="vision",
        model_name="qwen2.5vl:7b",
        extractor_version="1",
        full_text="Invoice total 4200",
        result_json=json.dumps({"facts": []}),
    )
    assert isinstance(ext_id, int)

    found = find_extraction(media_id, extractor_name="vision", extractor_version="1")
    assert found is not None and found["id"] == ext_id and found["full_text"] == "Invoice total 4200"

    chain = get_media_provenance(media_id)
    assert chain["asset"]["sha256"] == "c" * 64
    assert [e["id"] for e in chain["extractions"]] == [ext_id]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_media_records.py -q`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'mase_tools.memory.media_records'`

- [ ] **Step 3: 加 DDL 到 `db_core._create_legacy_schema`**

在 session_context 的两个索引(约 line 608-611)之后、函数收尾 commit 之前插入:

```python
        # 9. 多模态溯源:原始媒体资产 + 抽取记录(S0,additive)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_asset (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sha256 TEXT NOT NULL,
                source_uri TEXT,
                media_type TEXT NOT NULL,
                byte_size INTEGER,
                page_count INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT '',
                UNIQUE (sha256, tenant_id, workspace_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS media_extraction (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id INTEGER NOT NULL,
                extractor_name TEXT NOT NULL,
                model_name TEXT NOT NULL,
                extractor_version TEXT NOT NULL,
                full_text TEXT,
                result_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT ''
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_extraction_media ON media_extraction(media_id, created_at DESC)"
        )
```

- [ ] **Step 4: 实现 `mase_tools/memory/media_records.py`**

```python
"""media_asset / media_extraction 溯源表 CRUD。

多模态"看一次·记文字"路径的存储侧:原始媒体按 sha256 内容寻址登记,
每次抽取(抽取器+模型+版本)落一条可审计记录。事实行经
entity_state.source_media_id / memory_log.source_media_id 指回这里。
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from .db_core import _normalize_scope_value, get_connection


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def register_media_asset(
    sha256: str,
    *,
    source_uri: str | None,
    media_type: str,
    byte_size: int | None = None,
    page_count: int | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """登记媒体资产;同 (sha256, scope) 幂等返回已有行 id。"""
    tenant = _normalize_scope_value(tenant_id)
    workspace = _normalize_scope_value(workspace_id)
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM media_asset WHERE sha256 = ? AND tenant_id = ? AND workspace_id = ?",
            (sha256, tenant, workspace),
        )
        row = cursor.fetchone()
        if row is not None:
            return int(row["id"])
        cursor.execute(
            """
            INSERT INTO media_asset (sha256, source_uri, media_type, byte_size, page_count, tenant_id, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sha256, source_uri, media_type, byte_size, page_count, tenant, workspace),
        )
        return int(cursor.lastrowid)


def get_media_asset(
    media_id: int | None = None,
    *,
    sha256: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """按 id 或 (sha256, scope) 取资产行。"""
    if media_id is None and sha256 is None:
        raise ValueError("get_media_asset 需要 media_id 或 sha256 之一")
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        if media_id is not None:
            cursor.execute("SELECT * FROM media_asset WHERE id = ?", (media_id,))
        else:
            cursor.execute(
                "SELECT * FROM media_asset WHERE sha256 = ? AND tenant_id = ? AND workspace_id = ?",
                (sha256, _normalize_scope_value(tenant_id), _normalize_scope_value(workspace_id)),
            )
        row = cursor.fetchone()
        return _row_to_dict(row) if row is not None else None


def record_extraction(
    media_id: int,
    *,
    extractor_name: str,
    model_name: str,
    extractor_version: str,
    full_text: str,
    result_json: str,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """落一条抽取记录(全文 + 序列化结果),返回 extraction id。"""
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO media_extraction
                (media_id, extractor_name, model_name, extractor_version, full_text, result_json,
                 tenant_id, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                extractor_name,
                model_name,
                extractor_version,
                full_text,
                result_json,
                _normalize_scope_value(tenant_id),
                _normalize_scope_value(workspace_id),
            ),
        )
        return int(cursor.lastrowid)


def find_extraction(
    media_id: int,
    *,
    extractor_name: str,
    extractor_version: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """查同 (media, extractor, version) 的最近抽取记录;幂等判重用。"""
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM media_extraction
            WHERE media_id = ? AND extractor_name = ? AND extractor_version = ?
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (media_id, extractor_name, extractor_version),
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row is not None else None


def get_media_provenance(media_id: int, *, db_path: str | Path | None = None) -> dict[str, Any]:
    """溯源链读取:资产行 + 该资产的全部抽取记录(新→旧)。"""
    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media_asset WHERE id = ?", (media_id,))
        asset_row = cursor.fetchone()
        cursor.execute(
            "SELECT * FROM media_extraction WHERE media_id = ? ORDER BY created_at DESC, id DESC",
            (media_id,),
        )
        extraction_rows = cursor.fetchall()
    return {
        "asset": _row_to_dict(asset_row) if asset_row is not None else None,
        "extractions": [_row_to_dict(row) for row in extraction_rows],
    }
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_media_records.py -q`
Expected: 3 passed
Run: `python -m pytest -q -m "not integration and not slow"`
Expected: 644 passed(641 基线 + 3)

- [ ] **Step 6: 提交**

```bash
git add mase_tools/memory/db_core.py mase_tools/memory/media_records.py tests/test_media_records.py
git commit -m "feat(memory): media asset/extraction provenance schema and CRUD"
```

---

### Task 2: 写路径穿 source_media_id + mase2 门面

**Files:**
- Modify: `mase_tools/memory/db_core.py`(`add_memory_log` line 635、`add_event_log` line 693、`upsert_entity_fact` line 789,以及 `_create_legacy_schema` 两处幂等 ALTER)
- Modify: `mase_tools/memory/api.py`(`mase2_write_interaction`、`mase2_upsert_fact` 加可选参数;新增三个门面)
- Test: `tests/test_media_provenance_threading.py`

**Interfaces:**
- Consumes: Task 1 的 `register_media_asset` / `record_extraction` / `get_media_provenance`
- Produces:
  - `add_event_log(..., source_media_id: int | None = None, ...)`、`upsert_entity_fact(..., source_media_id: int | None = None, ...)`(keyword-only,默认 None,纯文本路径零影响)
  - `mase2_write_interaction(thread_id, role, content, *, source_media_id: int | None = None, scope_filters=None) -> str`
  - `mase2_upsert_fact(category, key, value, *, reason=None, source_log_id=None, source_media_id: int | None = None, scope_filters=None) -> str`
  - `mase2_register_media_asset(sha256, *, source_uri, media_type, byte_size=None, page_count=None, scope_filters=None) -> int`
  - `mase2_record_extraction(media_id, *, extractor_name, model_name, extractor_version, full_text, result_json, scope_filters=None) -> int`
  - `mase2_get_media_provenance(media_id) -> dict`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_media_provenance_threading.py
"""事实/流水账写路径携带 source_media_id 的行为测试(白盒溯源链)。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "prov.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    return db


def test_write_interaction_carries_source_media_id(tmp_path, monkeypatch):
    db = _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_register_media_asset, mase2_write_interaction

    media_id = mase2_register_media_asset(
        "d" * 64, source_uri="scan.png", media_type="image/png"
    )
    mase2_write_interaction("ingest::test", "system", "OCR full text here", source_media_id=media_id)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM memory_log WHERE thread_id = 'ingest::test'").fetchone()
    conn.close()
    assert row["source_media_id"] == media_id


def test_upsert_fact_carries_source_media_id(tmp_path, monkeypatch):
    db = _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_register_media_asset, mase2_upsert_fact

    media_id = mase2_register_media_asset("e" * 64, source_uri=None, media_type="application/pdf")
    mase2_upsert_fact(
        "finance_budget", "invoice_total", "4200 EUR",
        reason=f"media_extraction:{'e' * 64}", source_media_id=media_id,
    )

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM entity_state WHERE category='finance_budget' AND entity_key='invoice_total'"
    ).fetchone()
    conn.close()
    assert row["source_media_id"] == media_id
    assert row["source_reason"].startswith("media_extraction:")


def test_plain_text_path_unaffected(tmp_path, monkeypatch):
    """特征钉:不传 source_media_id 时列为 NULL,原有行为不变。"""
    db = _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_upsert_fact, mase2_write_interaction

    mase2_write_interaction("t1", "user", "hello")
    mase2_upsert_fact("user_preferences", "lang", "zh")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    log = conn.execute("SELECT source_media_id FROM memory_log WHERE thread_id='t1'").fetchone()
    fact = conn.execute("SELECT source_media_id FROM entity_state WHERE entity_key='lang'").fetchone()
    conn.close()
    assert log["source_media_id"] is None
    assert fact["source_media_id"] is None


def test_provenance_facade_returns_chain(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import (
        mase2_get_media_provenance,
        mase2_record_extraction,
        mase2_register_media_asset,
    )

    media_id = mase2_register_media_asset("f" * 64, source_uri="a.pdf", media_type="application/pdf")
    mase2_record_extraction(
        media_id, extractor_name="vision", model_name="qwen2.5vl:7b",
        extractor_version="1", full_text="text", result_json="{}",
    )
    chain = mase2_get_media_provenance(media_id)
    assert chain["asset"]["sha256"] == "f" * 64
    assert len(chain["extractions"]) == 1


def test_migration_adds_columns_to_existing_db(tmp_path, monkeypatch):
    """旧库(无新列)打开后自动获得 source_media_id 列,旧行不变。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE memory_log (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, role TEXT, content TEXT)")
    conn.execute("INSERT INTO memory_log (thread_id, role, content) VALUES ('old', 'user', 'legacy row')")
    conn.commit()
    conn.close()

    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    from mase_tools.memory.api import mase2_write_interaction

    mase2_write_interaction("new", "user", "new row")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_log)")}
    old = conn.execute("SELECT content FROM memory_log WHERE thread_id='old'").fetchone()
    conn.close()
    assert "source_media_id" in cols
    assert old["content"] == "legacy row"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_media_provenance_threading.py -q`
Expected: FAIL — `mase2_register_media_asset` 不存在 / `unexpected keyword argument 'source_media_id'`

- [ ] **Step 3: db_core 改动(最小)**

3a. `_create_legacy_schema` 中 entity_state 的幂等 ALTER 列表(约 line 326-334)追加一项:

```python
            ("source_media_id", "INTEGER"),
```

3b. memory_log 的 timestamp 迁移块(约 line 278-290)之后,按同一 PRAGMA 模式补:

```python
        if "source_media_id" not in log_cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN source_media_id INTEGER")
            log_cols.add("source_media_id")
```

⚠️ 注意 `_create_legacy_schema` 里 memory_log 可能还有第二段列迁移逻辑(thread_label/summary 等列在 `add_memory_log` 中使用);把新列加在同一处、复用已有 `log_cols` 集合,不新开 PRAGMA 查询。若实际行号漂移,以"memory_log 列迁移代码块"为锚点。

3c. `add_memory_log`(line 635):签名 `metadata: str | None = None,` 之后加 `source_media_id: int | None = None,`;INSERT 列表加 `source_media_id` 列与占位符,VALUES 元组对应位置加 `source_media_id`。

3d. `add_event_log`(line 693):签名加 `source_media_id: int | None = None,`,转发 `source_media_id=source_media_id`。

3e. `upsert_entity_fact`(line 789):签名 `source_log_id: int | None = None,` 之后加 `source_media_id: int | None = None,`。SELECT 旧行处补读 `source_media_id`(容错:`old_source_media_id = row["source_media_id"] if row and "source_media_id" in row.keys() else None`);`effective_source_media_id = source_media_id if source_media_id is not None else old_source_media_id`;INSERT 列清单、VALUES 元组、`ON CONFLICT ... DO UPDATE SET` 各加 `source_media_id=excluded.source_media_id`。

- [ ] **Step 4: api.py 改动**

4a. 顶部 import 增加:

```python
from .media_records import (
    get_media_provenance,
    record_extraction,
    register_media_asset,
)
```

4b. `mase2_write_interaction` 签名加 `source_media_id: int | None = None,`(keyword-only 区),调用改 `add_event_log(thread_id, role, content, source_media_id=source_media_id, **scope)`。

4c. `mase2_upsert_fact` 签名加 `source_media_id: int | None = None,`,转发给 `upsert_entity_fact(..., source_media_id=source_media_id, ...)`。

4d. 文件尾部追加三个门面:

```python
# ---------- Multimodal provenance (S0) ----------

def mase2_register_media_asset(
    sha256: str,
    *,
    source_uri: str | None,
    media_type: str,
    byte_size: int | None = None,
    page_count: int | None = None,
    scope_filters: dict[str, Any] | None = None,
) -> int:
    """登记媒体资产(内容寻址,幂等),返回 media_id。"""
    return register_media_asset(
        sha256,
        source_uri=source_uri,
        media_type=media_type,
        byte_size=byte_size,
        page_count=page_count,
        **dict(scope_filters or {}),
    )


def mase2_record_extraction(
    media_id: int,
    *,
    extractor_name: str,
    model_name: str,
    extractor_version: str,
    full_text: str,
    result_json: str,
    scope_filters: dict[str, Any] | None = None,
) -> int:
    """落一条可审计抽取记录,返回 extraction_id。"""
    return record_extraction(
        media_id,
        extractor_name=extractor_name,
        model_name=model_name,
        extractor_version=extractor_version,
        full_text=full_text,
        result_json=result_json,
        **dict(scope_filters or {}),
    )


def mase2_get_media_provenance(media_id: int) -> dict[str, Any]:
    """读取媒体溯源链:资产 + 抽取记录列表。"""
    return get_media_provenance(media_id)
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_media_provenance_threading.py tests/test_media_records.py -q`
Expected: 8 passed
Run: `python -m pytest -q -m "not integration and not slow"`
Expected: 649 passed,0 failed(重点看 test_facts_first_recall / test_fact_supersede 等既有写路径特征测试不回归)

- [ ] **Step 6: 提交**

```bash
git add mase_tools/memory/db_core.py mase_tools/memory/api.py tests/test_media_provenance_threading.py
git commit -m "feat(memory): thread source_media_id through write paths and mase2 facades"
```

---

### Task 3: 内容寻址资产库 asset_store

**Files:**
- Create: `mase_tools/media/__init__.py`(空文件,一行 docstring)
- Create: `mase_tools/media/asset_store.py`
- Test: `tests/test_asset_store.py`

**Interfaces:**
- Consumes: `mase_tools.memory.db_core._resolve_memory_dir`(默认根的回退项)
- Produces:
  - `resolve_asset_root() -> Path`(优先级:env `MASE_MEDIA_ASSETS_DIR` → env `MASE_RUNS_DIR`/media_assets → `_resolve_memory_dir()`/media_assets)
  - `store_bytes(data: bytes, *, suffix: str, root: Path | None = None) -> tuple[str, Path]`(返回 `(sha256, stored_path)`;布局 `<root>/<sha256[:2]>/<sha256>.<suffix>`;已存在同哈希文件直接复用不重写)
  - `asset_path(sha256: str, *, root: Path | None = None) -> Path | None`(按哈希找文件,不存在返回 None)
  - `AssetStoreError(Exception)`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_asset_store.py
"""内容寻址媒体资产库:哈希稳定、去重、写路径 jail。"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_store_bytes_is_content_addressed_and_dedups(tmp_path):
    from mase_tools.media.asset_store import asset_path, store_bytes

    data = b"fake png bytes"
    sha, path1 = store_bytes(data, suffix="png", root=tmp_path)
    assert sha == hashlib.sha256(data).hexdigest()
    assert path1 == tmp_path / sha[:2] / f"{sha}.png"
    assert path1.read_bytes() == data

    mtime = path1.stat().st_mtime_ns
    sha2, path2 = store_bytes(data, suffix="png", root=tmp_path)
    assert (sha2, path2) == (sha, path1)
    assert path1.stat().st_mtime_ns == mtime  # 已存在不重写

    assert asset_path(sha, root=tmp_path) == path1
    assert asset_path("0" * 64, root=tmp_path) is None


def test_store_bytes_rejects_pathy_suffix(tmp_path):
    """suffix 只允许短字母数字,防止拼路径逃逸。"""
    from mase_tools.media.asset_store import AssetStoreError, store_bytes

    for bad in ("../evil", "a/b", "png\\..", "x" * 20, ""):
        with pytest.raises(AssetStoreError):
            store_bytes(b"data", suffix=bad, root=tmp_path)


def test_resolve_asset_root_priority(tmp_path, monkeypatch):
    from mase_tools.media.asset_store import resolve_asset_root

    monkeypatch.setenv("MASE_MEDIA_ASSETS_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))
    assert resolve_asset_root() == (tmp_path / "explicit").resolve()

    monkeypatch.delenv("MASE_MEDIA_ASSETS_DIR")
    assert resolve_asset_root() == (tmp_path / "runs" / "media_assets").resolve()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_asset_store.py -q`
Expected: FAIL — `No module named 'mase_tools.media'`

- [ ] **Step 3: 实现**

`mase_tools/media/__init__.py`:

```python
"""媒体资产存储子包(S0 多模态摄取地基)。"""
```

`mase_tools/media/asset_store.py`:

```python
"""内容寻址媒体资产库。

原始媒体字节按 sha256 存放在 ``<root>/<sha[:2]>/<sha>.<suffix>``,是白盒
溯源链的最底层锚点:media_asset.sha256 → 本库文件 → 原始字节。
写路径固定在 resolve_asset_root() 之下(路径 jail),suffix 白名单校验,
同哈希文件已存在时直接复用,不重复写盘。
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from mase_tools.memory.db_core import _resolve_memory_dir

_SUFFIX_RE = re.compile(r"^[a-z0-9]{1,5}$")


class AssetStoreError(Exception):
    """资产库写入被拒(非法 suffix / 越界路径)。"""


def resolve_asset_root() -> Path:
    """资产根目录:显式 env → MASE_RUNS_DIR 下 → 默认 memory 目录下。"""
    explicit = os.environ.get("MASE_MEDIA_ASSETS_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    runs = os.environ.get("MASE_RUNS_DIR")
    if runs:
        return (Path(runs).expanduser() / "media_assets").resolve()
    return (_resolve_memory_dir() / "media_assets").resolve()


def _target_path(sha256: str, suffix: str, root: Path) -> Path:
    if not _SUFFIX_RE.fullmatch(suffix or ""):
        raise AssetStoreError(f"非法资产后缀: {suffix!r}")
    target = (root / sha256[:2] / f"{sha256}.{suffix}").resolve()
    if root.resolve() not in target.parents:
        raise AssetStoreError(f"资产写路径越界: {target}")
    return target


def store_bytes(data: bytes, *, suffix: str, root: Path | None = None) -> tuple[str, Path]:
    """按内容哈希存储字节;返回 (sha256, 存储路径)。同哈希已存在则复用。"""
    base = (root or resolve_asset_root()).resolve()
    sha256 = hashlib.sha256(data).hexdigest()
    target = _target_path(sha256, suffix, base)
    if target.exists():
        return sha256, target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)  # 原子落盘,避免半写文件被当成完整资产
    return sha256, target


def asset_path(sha256: str, *, root: Path | None = None) -> Path | None:
    """按哈希定位资产文件;不存在返回 None。"""
    base = (root or resolve_asset_root()).resolve()
    prefix_dir = base / sha256[:2]
    if not prefix_dir.is_dir():
        return None
    for candidate in prefix_dir.glob(f"{sha256}.*"):
        if candidate.is_file() and not candidate.name.endswith(".tmp"):
            return candidate
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_asset_store.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add mase_tools/media/__init__.py mase_tools/media/asset_store.py tests/test_asset_store.py
git commit -m "feat(media): content-addressed asset store with jailed writes"
```

---

### Task 4: 摄取安全边界 security.py

**Files:**
- Create: `src/mase/multimodal/__init__.py`
- Create: `src/mase/multimodal/security.py`
- Test: `tests/test_multimodal_security.py`

**Interfaces:**
- Consumes: 无(纯标准库)
- Produces:
  - `IngestSecurityError(Exception)`;`JailViolation(IngestSecurityError)`;`UnsupportedMedia(IngestSecurityError)`
  - `ALLOWED_MEDIA_TYPES: dict[str, str]`(`.png/.jpg/.jpeg/.webp/.gif/.pdf` → MIME)
  - `DEFAULT_MAX_BYTES = 50 * 1024 * 1024`
  - `assert_within_jail(path: Path, allowed_root: Path) -> Path`(返回 resolve 后路径;越界抛 JailViolation)
  - `classify_media(path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str`(返回 MIME;非白名单/超限抛 UnsupportedMedia)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multimodal_security.py
"""摄取安全边界:路径 jail + 类型/大小 allowlist。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_jail_allows_inside_and_rejects_escape(tmp_path):
    from mase.multimodal.security import JailViolation, assert_within_jail

    root = tmp_path / "docs"
    root.mkdir()
    inside = root / "a" / "scan.png"
    inside.parent.mkdir()
    inside.write_bytes(b"x")

    assert assert_within_jail(inside, root) == inside.resolve()

    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    with pytest.raises(JailViolation):
        assert_within_jail(outside, root)
    with pytest.raises(JailViolation):
        assert_within_jail(root / ".." / "secret.png", root)


def test_classify_media_allowlist(tmp_path):
    from mase.multimodal.security import UnsupportedMedia, classify_media

    png = tmp_path / "a.PNG"  # 大小写不敏感
    png.write_bytes(b"x" * 10)
    assert classify_media(png) == "image/png"

    pdf = tmp_path / "b.pdf"
    pdf.write_bytes(b"%PDF")
    assert classify_media(pdf) == "application/pdf"

    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(UnsupportedMedia):
        classify_media(exe)


def test_classify_media_rejects_oversize(tmp_path):
    from mase.multimodal.security import UnsupportedMedia, classify_media

    big = tmp_path / "big.png"
    big.write_bytes(b"x" * 1024)
    with pytest.raises(UnsupportedMedia):
        classify_media(big, max_bytes=512)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_multimodal_security.py -q`
Expected: FAIL — `No module named 'mase.multimodal'`

- [ ] **Step 3: 实现**

`src/mase/multimodal/__init__.py`:

```python
"""S0 多模态摄取子包:security → loader → extractor → ingest。

设计基线见 docs/superpowers/specs/2026-07-02-mase-multimodal-s0-design.md。
"""
```

`src/mase/multimodal/security.py`:

```python
"""摄取安全边界:路径 jail + 媒体类型/大小 allowlist。

S0 只读本地文件,不做 URL 抓取(无 SSRF 面);所有文件访问先过
assert_within_jail,再过 classify_media,两道都过才进入抽取管线。
"""
from __future__ import annotations

from pathlib import Path

ALLOWED_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".pdf": "application/pdf",
}

DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 单文件 50MB 上限,批处理防呆


class IngestSecurityError(Exception):
    """摄取安全边界拒绝(基类)。"""


class JailViolation(IngestSecurityError):
    """路径越出 allowed_root(含符号链接/.. 逃逸)。"""


class UnsupportedMedia(IngestSecurityError):
    """媒体类型不在 allowlist 或超出大小上限。"""


def assert_within_jail(path: Path, allowed_root: Path) -> Path:
    """resolve 后断言 path 位于 allowed_root 之内,返回归一化路径。

    resolve() 同时消解符号链接与 ``..``,因此链接指向根外也会被拒。
    """
    resolved = Path(path).resolve()
    root = Path(allowed_root).resolve()
    if resolved != root and root not in resolved.parents:
        raise JailViolation(f"路径越界: {resolved} 不在 {root} 之内")
    return resolved


def classify_media(path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """按扩展名 allowlist 归类媒体类型;非白名单或超限抛 UnsupportedMedia。"""
    suffix = Path(path).suffix.lower()
    media_type = ALLOWED_MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise UnsupportedMedia(f"不支持的媒体类型: {suffix!r} ({path})")
    size = Path(path).stat().st_size
    if size > max_bytes:
        raise UnsupportedMedia(f"文件超过大小上限 {max_bytes}B: {path} ({size}B)")
    return media_type
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_multimodal_security.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/mase/multimodal/__init__.py src/mase/multimodal/security.py tests/test_multimodal_security.py
git commit -m "feat(multimodal): ingest security boundary (path jail + allowlist)"
```

---

### Task 5: 文档加载器(图像直通 + PDF 栅格化)+ 可选依赖

**Files:**
- Create: `src/mase/multimodal/document_loader.py`
- Modify: `pyproject.toml`(optional-dependencies 加 `multimodal`;`dev` 列表加 pymupdf;`all` 列表加 pymupdf)
- Test: `tests/test_document_loader.py`

**Interfaces:**
- Consumes: `security.classify_media` 的 MIME 结果(loader 自身不做安全检查,信任上游已过滤)
- Produces:
  - `@dataclass(frozen=True) PageImage: index: int; image_bytes: bytes; media_type: str`
  - `load_pages(path: Path, media_type: str, *, pdf_dpi: int = 150) -> list[PageImage]`(图像 → 1 页原字节;PDF → 每页 PNG 字节)
  - `MissingDependencyError(Exception)`(缺 PyMuPDF 时的明确安装提示)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_document_loader.py
"""文档加载器:图像直通、PDF 按页栅格化、缺依赖有明确报错。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_image_passthrough_single_page(tmp_path):
    from mase.multimodal.document_loader import load_pages

    img = tmp_path / "shot.jpg"
    img.write_bytes(b"\xff\xd8fakejpeg")
    pages = load_pages(img, "image/jpeg")
    assert len(pages) == 1
    assert pages[0].index == 0
    assert pages[0].image_bytes == b"\xff\xd8fakejpeg"
    assert pages[0].media_type == "image/jpeg"


def test_pdf_rasterizes_each_page(tmp_path):
    fitz = pytest.importorskip("fitz")  # PyMuPDF;dev extra 已含,环境缺失时跳过
    from mase.multimodal.document_loader import load_pages

    doc = fitz.open()
    for text in ("Page one: invoice #001", "Page two: total 4200 EUR"):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    pdf = tmp_path / "two.pdf"
    doc.save(str(pdf))
    doc.close()

    pages = load_pages(pdf, "application/pdf")
    assert [p.index for p in pages] == [0, 1]
    assert all(p.media_type == "image/png" for p in pages)
    assert all(p.image_bytes[:8] == b"\x89PNG\r\n\x1a\n" for p in pages)


def test_missing_pymupdf_gives_actionable_error(tmp_path, monkeypatch):
    import builtins

    from mase.multimodal import document_loader
    from mase.multimodal.document_loader import MissingDependencyError

    real_import = builtins.__import__

    def _no_fitz(name, *args, **kwargs):
        if name == "fitz":
            raise ImportError("No module named 'fitz'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_fitz)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(MissingDependencyError, match=r"mase-memory\[multimodal\]"):
        document_loader.load_pages(pdf, "application/pdf")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_document_loader.py -q`
Expected: FAIL — `No module named 'mase.multimodal.document_loader'`

- [ ] **Step 3: 装依赖 + 改 pyproject**

Run: `python -m pip install "pymupdf>=1.24,<2.0"`

`pyproject.toml` `[project.optional-dependencies]` 增加(`llamaindex` 块后):

```toml
multimodal = [
    "pymupdf>=1.24,<2.0",
]
```

`all` 列表末尾与 `dev` 列表末尾各加一行:

```toml
    "pymupdf>=1.24,<2.0",
```

- [ ] **Step 4: 实现 `document_loader.py`**

```python
"""文档 → 页图序列。

图像文件直通(1 页,保留原字节与 MIME);PDF 经 PyMuPDF 按页栅格化为
PNG 字节。PyMuPDF 是可选依赖:核心安装不带,缺失时给出明确安装指引,
不静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class MissingDependencyError(Exception):
    """可选依赖缺失;消息包含安装指引。"""


@dataclass(frozen=True)
class PageImage:
    """单页图像:index 从 0 起;image_bytes 为该页完整图像字节。"""

    index: int
    image_bytes: bytes
    media_type: str


def load_pages(path: Path, media_type: str, *, pdf_dpi: int = 150) -> list[PageImage]:
    """把一个已过安全检查的文件转成页图列表。

    pdf_dpi 默认 150:文档 OCR 可读性与 VLM token 成本的折中;验收
    harness 会把实际 DPI 记入证据文件。
    """
    if media_type == "application/pdf":
        return _load_pdf_pages(Path(path), dpi=pdf_dpi)
    return [PageImage(index=0, image_bytes=Path(path).read_bytes(), media_type=media_type)]


def _load_pdf_pages(path: Path, *, dpi: int) -> list[PageImage]:
    try:
        import fitz  # PyMuPDF,按需导入:核心路径不背 PDF 依赖
    except ImportError as exc:
        raise MissingDependencyError(
            "解析 PDF 需要 PyMuPDF。请安装: pip install \"mase-memory[multimodal]\" "
            "或 pip install \"pymupdf>=1.24,<2.0\""
        ) from exc

    pages: list[PageImage] = []
    with fitz.open(str(path)) as doc:
        for page_index, page in enumerate(doc):
            pixmap = page.get_pixmap(dpi=dpi)
            pages.append(
                PageImage(index=page_index, image_bytes=pixmap.tobytes("png"), media_type="image/png")
            )
    return pages
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_document_loader.py -q`
Expected: 3 passed(pymupdf 已装,无 skip)

- [ ] **Step 6: 提交**

```bash
git add src/mase/multimodal/document_loader.py pyproject.toml tests/test_document_loader.py
git commit -m "feat(multimodal): document loader with optional PDF rasterization"
```

---

### Task 6: 抽取器契约(dataclasses + Protocol + 注册表)

**Files:**
- Create: `src/mase/multimodal/extractor.py`
- Test: `tests/test_multimodal_extractor_contract.py`

**Interfaces:**
- Consumes: `document_loader.PageImage`
- Produces(全特性可插拔接缝,S1–S3 复用):
  - `@dataclass(frozen=True) MediaAssetInfo: media_id: int; sha256: str; media_type: str; source_uri: str | None; page_count: int`
  - `@dataclass(frozen=True) CandidateFact: category: str; key: str; value: str; confidence: float; evidence: str`(confidence 为尽力值,非标定概率)
  - `@dataclass(frozen=True) ExtractionResult: full_text: str; candidate_facts: tuple[CandidateFact, ...]; extractor_name: str; model_name: str; extractor_version: str; warnings: tuple[str, ...]` + 方法 `to_json() -> str`
  - `class MediaExtractor(Protocol): name: str; version: str; def supports(self, media_type: str) -> bool; def extract(self, asset: MediaAssetInfo, pages: list[PageImage]) -> ExtractionResult`
  - `register_extractor(name: str, factory: Callable[[], MediaExtractor]) -> None`、`get_extractor_factory(name: str) -> Callable[[], MediaExtractor] | None`、`extractor_names() -> list[str]`(线程安全,同名重注册静默替换——与 agent_registry 语义一致)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multimodal_extractor_contract.py
"""MediaExtractor 契约:结果不可变、可序列化,注册表可插拔。"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _sample_result():
    from mase.multimodal.extractor import CandidateFact, ExtractionResult

    return ExtractionResult(
        full_text="Invoice #001 total 4200 EUR",
        candidate_facts=(
            CandidateFact(
                category="finance_budget", key="invoice_001_total", value="4200 EUR",
                confidence=0.9, evidence="total 4200 EUR",
            ),
        ),
        extractor_name="fake",
        model_name="none",
        extractor_version="1",
        warnings=(),
    )


def test_extraction_result_frozen_and_json_roundtrip():
    result = _sample_result()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.full_text = "tampered"  # type: ignore[misc]

    payload = json.loads(result.to_json())
    assert payload["full_text"].startswith("Invoice")
    assert payload["candidate_facts"][0]["category"] == "finance_budget"
    assert payload["extractor_version"] == "1"


def test_registry_register_get_and_replace():
    from mase.multimodal.extractor import extractor_names, get_extractor_factory, register_extractor

    marker_a, marker_b = object(), object()
    register_extractor("t6-demo", lambda: marker_a)
    assert get_extractor_factory("t6-demo")() is marker_a
    register_extractor("t6-demo", lambda: marker_b)  # 同名替换,幂等重导入友好
    assert get_extractor_factory("t6-demo")() is marker_b
    assert "t6-demo" in extractor_names()
    assert get_extractor_factory("no-such") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_multimodal_extractor_contract.py -q`
Expected: FAIL — `No module named 'mase.multimodal.extractor'`

- [ ] **Step 3: 实现 `extractor.py`**

```python
"""MediaExtractor 契约:多模态抽取的可插拔接缝。

每个模态(S0 视觉 / S1 语音 / S3 视频)实现同一协议:输入资产信息 +
页图,输出人和测试可直接检视的 ExtractionResult(全文 + 候选事实 +
抽取器/模型/版本)。注册表语义与 agent_registry 一致:同名重注册静默
替换,便于 dev reload;线程安全。
"""
from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .document_loader import PageImage


@dataclass(frozen=True)
class MediaAssetInfo:
    """抽取器可见的资产元数据(不含原始字节,字节走 pages)。"""

    media_id: int
    sha256: str
    media_type: str
    source_uri: str | None
    page_count: int


@dataclass(frozen=True)
class CandidateFact:
    """单条候选事实;confidence 为尽力值(模型自报/启发式),非标定概率。"""

    category: str
    key: str
    value: str
    confidence: float
    evidence: str


@dataclass(frozen=True)
class ExtractionResult:
    """一次抽取的完整可审计产物。"""

    full_text: str
    candidate_facts: tuple[CandidateFact, ...]
    extractor_name: str
    model_name: str
    extractor_version: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class MediaExtractor(Protocol):
    """模态无关抽取器协议。"""

    name: str
    version: str

    def supports(self, media_type: str) -> bool: ...

    def extract(self, asset: MediaAssetInfo, pages: list[PageImage]) -> ExtractionResult: ...


_LOCK = threading.RLock()
_FACTORIES: dict[str, Callable[[], MediaExtractor]] = {}


def register_extractor(name: str, factory: Callable[[], MediaExtractor]) -> None:
    """注册抽取器工厂;同名替换。"""
    if not name or not isinstance(name, str):
        raise ValueError(f"extractor name must be a non-empty string, got {name!r}")
    with _LOCK:
        _FACTORIES[name] = factory


def get_extractor_factory(name: str) -> Callable[[], MediaExtractor] | None:
    with _LOCK:
        return _FACTORIES.get(name)


def extractor_names() -> list[str]:
    with _LOCK:
        return sorted(_FACTORIES)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_multimodal_extractor_contract.py -q`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/mase/multimodal/extractor.py tests/test_multimodal_extractor_contract.py
git commit -m "feat(multimodal): MediaExtractor contract and registry"
```

---

### Task 7: VLM 视觉抽取器 + vision agent 配置

**Files:**
- Create: `src/mase/multimodal/vision_extractor.py`
- Modify: `config.json`(`models` 块加 `"vision"` agent,置于 `"executor"` 之后)
- Modify: `pyproject.toml`(ruff per-file-ignores 加 vision_extractor/ingest 的 BLE001)
- Test: `tests/test_vision_extractor.py`

**Interfaces:**
- Consumes: `ModelInterface.chat(agent_type="vision", messages=..., mode=..., override_system_prompt=...)`(消息 dict 的 `images` 兄弟字段被 `chat()`/`_call_ollama` 原样透传——`inject_system_prompt` 对非 system 消息做 `dict(message)` 浅拷贝,保留额外键);`extractor` 契约;`document_loader.PageImage`
- Produces:
  - `VISION_EXTRACTOR_VERSION = "1"`
  - `class VisionExtractor: def __init__(self, model_interface=None, *, mode: str | None = None)`;`name = "vision"`;`version = VISION_EXTRACTOR_VERSION`;`supports(media_type)`(image/* 与 application/pdf 为 True);`extract(asset, pages) -> ExtractionResult`
  - 每页一次 `chat()` 调用;页间聚合:full_text 以 `\n\n--- page {n} ---\n\n` 连接,facts 串接
  - JSON 解析失败降级:该页原文进 full_text、无 facts、warnings 加 `"page {n}: non_json_response"`
  - config.json 新增 `models.vision`(默认 qwen2.5vl:7b;`modes.minicpm.model_name = "minicpm-v:4.5"`)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_vision_extractor.py
"""VLM 视觉抽取器:Ollama images 传参形状、JSON 解析、降级、多页聚合。"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.document_loader import PageImage
from mase.multimodal.extractor import MediaAssetInfo


class FakeModelInterface:
    """记录 chat() 入参并按序返回预置响应。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, agent_type, messages, mode=None, tools=None, override_system_prompt=None, prompt_key="system_prompt"):
        self.calls.append({
            "agent_type": agent_type, "messages": messages, "mode": mode,
            "override_system_prompt": override_system_prompt,
        })
        return {"message": {"role": "assistant", "content": self.replies.pop(0)}, "model": "fake-vlm"}


def _asset(pages=1):
    return MediaAssetInfo(media_id=1, sha256="a" * 64, media_type="image/png", source_uri="s.png", page_count=pages)


def test_extract_sends_base64_images_sibling_field_and_parses_json():
    from mase.multimodal.vision_extractor import VisionExtractor

    reply = json.dumps({
        "full_text": "Invoice #001 total 4200 EUR",
        "facts": [{"category": "finance_budget", "key": "invoice_001_total",
                   "value": "4200 EUR", "confidence": 0.9, "evidence": "total 4200 EUR"}],
    })
    fake = FakeModelInterface([reply])
    extractor = VisionExtractor(fake)
    page_bytes = b"\x89PNGfake"
    result = extractor.extract(_asset(), [PageImage(0, page_bytes, "image/png")])

    call = fake.calls[0]
    assert call["agent_type"] == "vision"
    user_msg = call["messages"][0]
    assert user_msg["role"] == "user"
    assert user_msg["images"] == [base64.b64encode(page_bytes).decode("ascii")]  # Ollama 兄弟字段,裸 base64
    assert call["override_system_prompt"]  # 抽取契约提示词与解析器同处一模块

    assert result.full_text == "Invoice #001 total 4200 EUR"
    assert result.candidate_facts[0].key == "invoice_001_total"
    assert result.model_name == "fake-vlm"
    assert result.extractor_name == "vision" and result.extractor_version == "1"
    assert result.warnings == ()


def test_malformed_json_degrades_to_full_text_with_warning():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface(["The image shows an invoice, not JSON at all."])
    result = VisionExtractor(fake).extract(_asset(), [PageImage(0, b"img", "image/png")])
    assert "invoice" in result.full_text
    assert result.candidate_facts == ()
    assert any("non_json_response" in w for w in result.warnings)


def test_multipage_aggregates_text_and_facts_in_order():
    from mase.multimodal.vision_extractor import VisionExtractor

    replies = [
        json.dumps({"full_text": "page one text", "facts": [
            {"category": "general_facts", "key": "k1", "value": "v1", "confidence": 0.5, "evidence": "e1"}]}),
        json.dumps({"full_text": "page two text", "facts": [
            {"category": "general_facts", "key": "k2", "value": "v2", "confidence": 0.5, "evidence": "e2"}]}),
    ]
    fake = FakeModelInterface(replies)
    result = VisionExtractor(fake).extract(
        _asset(pages=2),
        [PageImage(0, b"p1", "image/png"), PageImage(1, b"p2", "image/png")],
    )
    assert len(fake.calls) == 2  # 每页一次调用,7B VLM 单图更可靠
    assert "page one text" in result.full_text and "page two text" in result.full_text
    assert result.full_text.index("page one") < result.full_text.index("page two")
    assert "--- page 2 ---" in result.full_text
    assert [f.key for f in result.candidate_facts] == ["k1", "k2"]


def test_mode_passthrough_for_model_switch():
    from mase.multimodal.vision_extractor import VisionExtractor

    fake = FakeModelInterface([json.dumps({"full_text": "t", "facts": []})])
    VisionExtractor(fake, mode="minicpm").extract(_asset(), [PageImage(0, b"i", "image/png")])
    assert fake.calls[0]["mode"] == "minicpm"


def test_supports_matrix():
    from mase.multimodal.vision_extractor import VisionExtractor

    extractor = VisionExtractor(FakeModelInterface([]))
    assert extractor.supports("image/png") and extractor.supports("application/pdf")
    assert not extractor.supports("audio/wav")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_vision_extractor.py -q`
Expected: FAIL — `No module named 'mase.multimodal.vision_extractor'`

- [ ] **Step 3: 实现 `vision_extractor.py`**

```python
"""本地 VLM 视觉抽取器(S0 参考模态)。

引擎无关约定:抽取器只构造"文本提示 + 页图字节"的抽象请求;当前唯一
序列化目标是 Ollama chat 的 message 级 ``images:[base64]`` 兄弟字段
(官方 docs/api.md,裸 base64 无 data URI 前缀)。S2 在同一接缝扩展
OpenAI image_url / Anthropic image block。

提示词与解析器刻意同居本模块:JSON 输出契约变更时两者一起改。
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

from .document_loader import PageImage
from .extractor import CandidateFact, ExtractionResult, MediaAssetInfo

VISION_EXTRACTOR_VERSION = "1"

# 类别引导对齐 db_core.PROFILE_TEMPLATES;未知类别由 upsert_entity_fact
# 的既有护栏归入 general_facts,这里不重复实现。
VISION_EXTRACTION_SYSTEM = """你是企业文档抽取器。请仔细阅读图片并输出严格的 JSON(不要 markdown 代码围栏),形状:
{"full_text": "<转写图中全部可读文本,保留数字与单位>",
 "facts": [{"category": "<user_preferences|people_relations|project_status|finance_budget|location_events|general_facts 之一>",
            "key": "<snake_case 唯一键>", "value": "<事实当前值>",
            "confidence": <0到1的数字>, "evidence": "<full_text 中支撑该事实的原文片段>"}]}
规则:
- full_text 必须尽量完整转写,这是审计底稿;
- 只提取图中明确出现的事实,不要推测;没有事实就返回空数组;
- evidence 必须是 full_text 的子串级别引用。"""

_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


class VisionExtractor:
    """把页图交给本地 VLM,产出可审计 ExtractionResult。"""

    name = "vision"
    version = VISION_EXTRACTOR_VERSION

    def __init__(self, model_interface: Any = None, *, mode: str | None = None) -> None:
        if model_interface is None:
            from mase.model_interface import ModelInterface

            model_interface = ModelInterface()
        self.model_interface = model_interface
        self.mode = mode

    def supports(self, media_type: str) -> bool:
        return media_type.startswith("image/") or media_type == "application/pdf"

    def extract(self, asset: MediaAssetInfo, pages: list[PageImage]) -> ExtractionResult:
        text_parts: list[str] = []
        facts: list[CandidateFact] = []
        warnings: list[str] = []
        model_name = "unknown"

        for page in pages:
            prompt = (
                f"来源: {asset.source_uri or asset.sha256[:12]}"
                f" 第 {page.index + 1}/{asset.page_count} 页。请按系统提示抽取。"
            )
            message = {
                "role": "user",
                "content": prompt,
                # Ollama chat 多模态约定:base64 图放 message 级 images 兄弟字段
                "images": [base64.b64encode(page.image_bytes).decode("ascii")],
            }
            response = self.model_interface.chat(
                "vision",
                messages=[message],
                mode=self.mode,
                override_system_prompt=VISION_EXTRACTION_SYSTEM,
            )
            model_name = str(response.get("model") or model_name)
            raw = str((response.get("message") or {}).get("content") or "")
            page_text, page_facts, page_warnings = _parse_page_reply(raw, page_number=page.index + 1)
            if page.index > 0:
                text_parts.append(f"--- page {page.index + 1} ---")
            text_parts.append(page_text)
            facts.extend(page_facts)
            warnings.extend(page_warnings)

        return ExtractionResult(
            full_text="\n\n".join(part for part in text_parts if part).strip(),
            candidate_facts=tuple(facts),
            extractor_name=self.name,
            model_name=model_name,
            extractor_version=self.version,
            warnings=tuple(warnings),
        )


def _parse_page_reply(raw: str, *, page_number: int) -> tuple[str, list[CandidateFact], list[str]]:
    """解析单页模型回复;畸形输出降级为"原文即全文",绝不抛穿。"""
    match = _JSON_BLOB_RE.search(raw)
    if match:
        try:
            payload = json.loads(match.group(0))
            full_text = str(payload.get("full_text") or "").strip()
            facts = [
                CandidateFact(
                    category=str(item.get("category") or "general_facts"),
                    key=str(item.get("key") or "").strip(),
                    value=str(item.get("value") or "").strip(),
                    confidence=_coerce_confidence(item.get("confidence")),
                    evidence=str(item.get("evidence") or "").strip(),
                )
                for item in (payload.get("facts") or [])
                if isinstance(item, dict) and str(item.get("key") or "").strip() and str(item.get("value") or "").strip()
            ]
            return full_text or raw.strip(), facts, []
        except Exception:
            pass
    return raw.strip(), [], [f"page {page_number}: non_json_response"]


def _coerce_confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 4: config.json 加 vision agent**

`models` 块内 `"executor": {...}` 之后加(注意 JSON 逗号):

```json
"vision": {
  "provider": "ollama",
  "model_name": "qwen2.5vl:7b",
  "ollama_options": {
    "num_ctx": 8192
  },
  "temperature": 0.0,
  "max_tokens": 2048,
  "modes": {
    "minicpm": {
      "model_name": "minicpm-v:4.5"
    }
  }
}
```

(`ModelsBlock` 是 `extra="allow"`,新增 agent 键不破坏 config 校验;`config_schema.REQUIRED_AGENTS` 不含 vision,保持可选。)

- [ ] **Step 5: pyproject ruff per-file-ignores 加两行**

`[tool.ruff.lint.per-file-ignores]` 内(与 notetaker_agent 同理:LLM 输出解析必须容忍畸形输出):

```toml
"src/mase/multimodal/vision_extractor.py" = ["BLE001"]  # VLM 回复解析降级,不抛穿批处理
"src/mase/multimodal/ingest.py" = ["BLE001"]            # 逐文件隔离:任意异常落 infra_errors
```

- [ ] **Step 6: 跑测试确认通过 + lint**

Run: `python -m pytest tests/test_vision_extractor.py -q`
Expected: 5 passed
Run: `python -m ruff check src/mase/multimodal/ && python - <<'EOF'
import json; json.load(open("config.json", encoding="utf-8")); print("config.json OK")
EOF`
Expected: ruff 无输出;`config.json OK`

- [ ] **Step 7: 提交**

```bash
git add src/mase/multimodal/vision_extractor.py config.json pyproject.toml tests/test_vision_extractor.py
git commit -m "feat(multimodal): local VLM vision extractor with vision agent config"
```

---

### Task 8: 批处理摄取管线 ingest.py

**Files:**
- Create: `src/mase/multimodal/ingest.py`
- Test: `tests/test_multimodal_ingest.py`

**Interfaces:**
- Consumes: Task 3 `store_bytes`;Task 4 `assert_within_jail/classify_media/IngestSecurityError`;Task 5 `load_pages/MissingDependencyError`;Task 6 契约;Task 7 `VisionExtractor`;Task 2 `mase2_register_media_asset/mase2_record_extraction/mase2_write_interaction/mase2_upsert_fact`;Task 1 `find_extraction`;`mase_tools.memory.tri_vault`(is_enabled/mirror_write)
- Produces:
  - `@dataclass(frozen=True) IngestReport: processed: tuple[str, ...]; skipped: tuple[dict, ...]; infra_errors: tuple[dict, ...]; extractions: int; facts_written: int`
  - `ingest_folder(folder: Path, *, allowed_root: Path | None = None, mode: str | None = None, extractor: MediaExtractor | None = None, force: bool = False, asset_root: Path | None = None, max_bytes: int = DEFAULT_MAX_BYTES) -> IngestReport`
  - 行为:非递归+递归?**递归**(`rglob("*")` 只取文件,排序保证确定性);`allowed_root` 默认= folder;`extractor` 默认= `VisionExtractor(mode=mode)`;幂等键 `(sha256, extractor.name, extractor.version)`;full_text 落 `mase2_write_interaction(thread_id=f"ingest::{sha256[:12]}", role="system", ...)`;每条事实 `reason=f"media_extraction:{sha256}"`;tri-vault 镜像 best-effort

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multimodal_ingest.py
"""摄取管线端到端(假抽取器,无真模型):溯源、幂等、隔离、越界拒绝。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.multimodal.extractor import CandidateFact, ExtractionResult


class FakeExtractor:
    """确定性抽取器:全文=文件名标记,一条事实;可指定对某文件抛错。"""

    name = "fake"
    version = "1"

    def __init__(self, *, boom_on: str | None = None):
        self.boom_on = boom_on
        self.extract_count = 0

    def supports(self, media_type: str) -> bool:
        return True

    def extract(self, asset, pages) -> ExtractionResult:
        self.extract_count += 1
        if self.boom_on and self.boom_on in str(asset.source_uri):
            raise RuntimeError("simulated model failure")
        tag = Path(str(asset.source_uri)).stem
        return ExtractionResult(
            full_text=f"fulltext-of-{tag} unique-token-{tag}",
            candidate_facts=(
                CandidateFact("general_facts", f"doc_{tag}", f"value-{tag}", 0.8, f"unique-token-{tag}"),
            ),
            extractor_name=self.name, model_name="fake-model", extractor_version=self.version,
            warnings=(),
        )


def _setup(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    db = tmp_path / "ingest.db"
    monkeypatch.setenv("MASE_DB_PATH", str(db))
    docs = tmp_path / "docs"
    docs.mkdir()
    assets = tmp_path / "assets"
    return db, docs, assets


def test_ingest_writes_facts_with_full_provenance_chain(tmp_path, monkeypatch):
    db, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "invoice.png").write_bytes(b"\x89PNG-invoice-bytes")
    from mase.multimodal.ingest import ingest_folder
    from mase_tools.memory.api import mase2_get_media_provenance, mase2_search_memory

    report = ingest_folder(docs, extractor=FakeExtractor(), asset_root=assets)
    assert report.processed == ("invoice.png",)
    assert report.extractions == 1 and report.facts_written == 1
    assert report.infra_errors == () and report.skipped == ()

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    fact = conn.execute("SELECT * FROM entity_state WHERE entity_key='doc_invoice'").fetchone()
    assert fact["source_media_id"] is not None
    assert fact["source_reason"].startswith("media_extraction:")
    log = conn.execute("SELECT * FROM memory_log WHERE source_media_id = ?", (fact["source_media_id"],)).fetchone()
    assert "unique-token-invoice" in log["content"]
    conn.close()

    chain = mase2_get_media_provenance(fact["source_media_id"])
    assert chain["asset"]["source_uri"].endswith("invoice.png")
    assert chain["extractions"][0]["model_name"] == "fake-model"
    # 资产文件真实落盘
    sha = chain["asset"]["sha256"]
    assert (assets / sha[:2] / f"{sha}.png").read_bytes() == b"\x89PNG-invoice-bytes"
    # 召回链:全文可被现有搜索命中
    hits = mase2_search_memory(["unique-token-invoice"], limit=5)
    assert any("unique-token-invoice" in str(h.get("content", "")) for h in hits)


def test_ingest_is_idempotent_and_force_reextracts(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "a.png").write_bytes(b"same-bytes")
    from mase.multimodal.ingest import ingest_folder

    fake = FakeExtractor()
    ingest_folder(docs, extractor=fake, asset_root=assets)
    report2 = ingest_folder(docs, extractor=fake, asset_root=assets)
    assert fake.extract_count == 1  # 第二遍同 (hash, extractor, version) 跳过
    assert report2.skipped and report2.skipped[0]["reason"] == "already_extracted"

    ingest_folder(docs, extractor=fake, asset_root=assets, force=True)
    assert fake.extract_count == 2


def test_per_file_isolation_on_extractor_failure(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "bad.png").write_bytes(b"bad-bytes")
    (docs / "good.png").write_bytes(b"good-bytes")
    from mase.multimodal.ingest import ingest_folder

    report = ingest_folder(docs, extractor=FakeExtractor(boom_on="bad"), asset_root=assets)
    assert report.processed == ("good.png",)
    assert len(report.infra_errors) == 1
    assert report.infra_errors[0]["file"] == "bad.png"
    assert "simulated model failure" in report.infra_errors[0]["error"]


def test_non_allowlisted_and_escaping_files_are_skipped(tmp_path, monkeypatch):
    _, docs, assets = _setup(tmp_path, monkeypatch)
    (docs / "note.txt").write_text("not media")
    (docs / "ok.png").write_bytes(b"ok")
    from mase.multimodal.ingest import ingest_folder

    report = ingest_folder(docs, extractor=FakeExtractor(), asset_root=assets)
    assert report.processed == ("ok.png",)
    assert any(s["file"] == "note.txt" and s["reason"] == "unsupported_media" for s in report.skipped)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_multimodal_ingest.py -q`
Expected: FAIL — `No module named 'mase.multimodal.ingest'`

- [ ] **Step 3: 实现 `ingest.py`**

```python
"""批处理摄取编排:文件夹 → 逐文件隔离管线 → 带溯源写入白盒记忆。

单文件失败(安全拒绝/损坏/模型故障)只影响该文件:安全与类型问题落
skipped,运行时异常落 infra_errors,批次继续(对齐 benchmarks/runner.py
的 attempt_rows/infra_error 模式)。幂等键 (sha256, extractor, version)。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mase_tools.media.asset_store import store_bytes
from mase_tools.memory import tri_vault
from mase_tools.memory.api import (
    mase2_record_extraction,
    mase2_register_media_asset,
    mase2_upsert_fact,
    mase2_write_interaction,
)
from mase_tools.memory.media_records import find_extraction

from .document_loader import load_pages
from .extractor import MediaAssetInfo, MediaExtractor
from .security import DEFAULT_MAX_BYTES, IngestSecurityError, UnsupportedMedia, assert_within_jail, classify_media

_SUFFIX_BY_MEDIA_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "application/pdf": "pdf",
}


@dataclass(frozen=True)
class IngestReport:
    """一次批处理的可审计汇总。"""

    processed: tuple[str, ...]
    skipped: tuple[dict[str, Any], ...]
    infra_errors: tuple[dict[str, Any], ...]
    extractions: int
    facts_written: int


def ingest_folder(
    folder: Path,
    *,
    allowed_root: Path | None = None,
    mode: str | None = None,
    extractor: MediaExtractor | None = None,
    force: bool = False,
    asset_root: Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> IngestReport:
    """摄取 folder 下全部受支持文件(递归、字典序,保证批次确定性)。"""
    folder = Path(folder).resolve()
    root = Path(allowed_root).resolve() if allowed_root is not None else folder
    if extractor is None:
        from .vision_extractor import VisionExtractor

        extractor = VisionExtractor(mode=mode)

    processed: list[str] = []
    skipped: list[dict[str, Any]] = []
    infra_errors: list[dict[str, Any]] = []
    extractions = 0
    facts_written = 0

    for file_path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel_name = file_path.relative_to(folder).as_posix()
        try:
            checked = assert_within_jail(file_path, root)
            media_type = classify_media(checked, max_bytes=max_bytes)
        except UnsupportedMedia as exc:
            skipped.append({"file": rel_name, "reason": "unsupported_media", "detail": str(exc)})
            continue
        except IngestSecurityError as exc:
            skipped.append({"file": rel_name, "reason": "security_rejected", "detail": str(exc)})
            continue

        try:
            data = checked.read_bytes()
            sha256, _stored = store_bytes(
                data, suffix=_SUFFIX_BY_MEDIA_TYPE[media_type], root=asset_root
            )
            pages = load_pages(checked, media_type)
            media_id = mase2_register_media_asset(
                sha256,
                source_uri=rel_name,
                media_type=media_type,
                byte_size=len(data),
                page_count=len(pages),
            )
            if not force and find_extraction(
                media_id, extractor_name=extractor.name, extractor_version=extractor.version
            ):
                skipped.append({"file": rel_name, "reason": "already_extracted", "sha256": sha256})
                continue

            asset_info = MediaAssetInfo(
                media_id=media_id, sha256=sha256, media_type=media_type,
                source_uri=rel_name, page_count=len(pages),
            )
            result = extractor.extract(asset_info, pages)
            mase2_record_extraction(
                media_id,
                extractor_name=result.extractor_name,
                model_name=result.model_name,
                extractor_version=result.extractor_version,
                full_text=result.full_text,
                result_json=result.to_json(),
            )
            extractions += 1
            mase2_write_interaction(
                f"ingest::{sha256[:12]}", "system", result.full_text, source_media_id=media_id
            )
            for fact in result.candidate_facts:
                mase2_upsert_fact(
                    fact.category, fact.key, fact.value,
                    reason=f"media_extraction:{sha256}", source_media_id=media_id,
                )
                facts_written += 1
                _mirror_fact_write(fact, sha256=sha256, media_id=media_id)
            processed.append(rel_name)
        except Exception as exc:
            infra_errors.append({"file": rel_name, "error": f"{type(exc).__name__}: {exc}"})

    return IngestReport(
        processed=tuple(processed),
        skipped=tuple(skipped),
        infra_errors=tuple(infra_errors),
        extractions=extractions,
        facts_written=facts_written,
    )


def _mirror_fact_write(fact: Any, *, sha256: str, media_id: int) -> None:
    """tri-vault 磁盘镜像(与 notetaker 同模式):best-effort,失败不破坏主链路。"""
    if not tri_vault.is_enabled():
        return
    try:
        tri_vault.mirror_write(
            "context",
            f"{fact.category}__{fact.key}",
            {
                "tool": "multimodal_ingest",
                "arguments": {"category": fact.category, "key": fact.key, "value": fact.value,
                              "source_media_id": media_id, "sha256": sha256},
                "result": f"media_extraction:{sha256}",
                "ts": int(time.time() * 1000),
            },
        )
    except Exception:
        pass
```

⚠️ 校验点:`from mase_tools.memory import tri_vault` 的实际路径——若 tri_vault 位于 `mase_tools/memory/tri_vault.py`(notetaker_agent 用 `from mase_tools.memory import tri_vault`,一致),保持该导入;若 `mirror_write` 签名不同(见 tri_vault.py:101-154),以实际签名为准调整。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_multimodal_ingest.py -q`
Expected: 4 passed
Run: `python -m pytest -q -m "not integration and not slow"`
Expected: 全绿(649 + 本任务 4 + Task3-7 新增 ≈ 666,以实际计)

- [ ] **Step 5: 提交**

```bash
git add src/mase/multimodal/ingest.py tests/test_multimodal_ingest.py
git commit -m "feat(multimodal): batch ingest pipeline with provenance and per-file isolation"
```

---

### Task 9: CLI 入口

**Files:**
- Create: `src/mase/multimodal/cli.py`
- Create: `src/mase/multimodal/__main__.py`
- Modify: `src/mase/mase_cli.py`(仅 `if __name__ == "__main__":` 块前加 argv 分发,交互式菜单不动)
- Test: `tests/test_multimodal_cli.py`

**Interfaces:**
- Consumes: `ingest.ingest_folder`、`ingest.IngestReport`
- Produces:
  - `cli.main(argv: list[str] | None = None) -> int`(参数:`folder` 位置参数;`--mode`;`--force`;`--allowed-root`;`--max-mb`,默认 50)
  - 退出码:0=有产出或空批;1=存在 infra_errors;2=参数/路径错误
  - 入口:`python -m mase.multimodal ingest <folder> [...]` 与 `python mase_cli.py ingest <folder> [...]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multimodal_cli.py
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_multimodal_cli.py -q`
Expected: FAIL — `No module named 'mase.multimodal.cli'`

- [ ] **Step 3: 实现**

`src/mase/multimodal/cli.py`:

```python
"""`mase ingest` 批处理命令行入口。"""
from __future__ import annotations

import argparse
from pathlib import Path

from .ingest import ingest_folder
from .security import DEFAULT_MAX_BYTES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mase ingest",
        description="批量摄取本地文档/图像(png/jpg/webp/gif/pdf)为白盒记忆事实。",
    )
    parser.add_argument("folder", help="待摄取的本地文件夹(默认同时作为路径 jail 根)")
    parser.add_argument("--mode", default=None, help="vision agent 模式,如 minicpm 切换 minicpm-v:4.5")
    parser.add_argument("--force", action="store_true", help="忽略幂等跳过,强制重新抽取")
    parser.add_argument("--allowed-root", default=None, help="路径 jail 根目录(默认= folder)")
    parser.add_argument("--max-mb", type=int, default=DEFAULT_MAX_BYTES // (1024 * 1024), help="单文件大小上限 MB")
    args = parser.parse_args(argv)

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"[error] 目录不存在: {folder}")
        return 2

    report = ingest_folder(
        folder,
        allowed_root=Path(args.allowed_root) if args.allowed_root else None,
        mode=args.mode,
        force=args.force,
        max_bytes=args.max_mb * 1024 * 1024,
    )
    print(
        f"[ingest] processed={len(report.processed)} skipped={len(report.skipped)} "
        f"errors={len(report.infra_errors)} extractions={report.extractions} facts={report.facts_written}"
    )
    for item in report.skipped:
        print(f"  [skip] {item['file']}: {item['reason']}")
    for item in report.infra_errors:
        print(f"  [error] {item['file']}: {item['error']}")
    return 1 if report.infra_errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

`src/mase/multimodal/__main__.py`:

```python
"""`python -m mase.multimodal ingest <folder>` 入口。"""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "ingest":
        argv = argv[1:]
    raise SystemExit(main(argv))
```

`src/mase/mase_cli.py` 的 `if __name__ == "__main__":` 块改为(原 try/except 保留):

```python
if __name__ == "__main__":
    # 非交互子命令分发:`python mase_cli.py ingest <folder>` 走多模态批处理,
    # 其余保持原交互式菜单。
    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        from mase.multimodal.cli import main as _ingest_main

        sys.exit(_ingest_main(sys.argv[2:]))
    try:
        main()
    except KeyboardInterrupt:
        print("\n已安全退出。")
        sys.exit(0)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_multimodal_cli.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add src/mase/multimodal/cli.py src/mase/multimodal/__main__.py src/mase/mase_cli.py tests/test_multimodal_cli.py
git commit -m "feat(multimodal): ingest CLI entry (module and mase_cli dispatch)"
```

---

### Task 10: 验收 harness + 全量质量门

**Files:**
- Create: `scripts/run_s0_acceptance.py`
- Modify: `pyproject.toml`(mypy `files` 列表追加 `"src/mase/multimodal"`——新代码从第一天就进严格类型门)
- Test: 无新增单元测试(harness 本身是 integration 工具);以全量门禁 + 真跑证据收口

**Interfaces:**
- Consumes: `ingest_folder`、`mase2_get_media_provenance`、`mase2_search_memory`、Ollama `/api/tags`
- Produces: `scripts/run_s0_acceptance.py`,行为:
  1. 探测 `http://127.0.0.1:11434/api/tags`;缺 `qwen2.5vl:7b` 或 `minicpm-v:4.5` → 打印 `ollama pull` 指引,exit 2
  2. 用 PyMuPDF 生成确定性样本(1 张发票样式 PNG + 1 个 2 页 PDF,内容含可验证锚词如 `ACME-INV-2026-001`、`4200 EUR`)到 `MASE_RUNS_DIR/s0_acceptance/<ts>/samples/`
  3. 对每个模型 lane(默认 / `--mode minicpm`)各自用独立 `MASE_DB_PATH` 跑 `ingest_folder`
  4. 断言:每 lane `extractions ≥ 2`、`infra_errors == 0`、锚词可经 `mase2_search_memory` 召回、事实溯源链完整(fact→extraction→asset→文件存在)
  5. 证据文件 `evidence.json` + `evidence.md` 写入同目录:模型名、sha256、DPI、每 lane 用时、facts 数、召回命中、溯源链抽样;全过 exit 0,任一断言失败 exit 1
- 运行方式:`python -X utf8 scripts/run_s0_acceptance.py`(需真模型;**不进 pytest 默认套件**)

- [ ] **Step 1: 写 harness(工具脚本,直接实现;验收判据即其内置断言)**

脚本骨架(完整实现按此结构展开;所有断言失败路径必须打印具体差异后 exit 1,禁止吞错):

```python
"""S0 验收 harness:双模型 lane 真跑 + 证据文件。

用法: python -X utf8 scripts/run_s0_acceptance.py [--runs-dir E:/MASE-runs]
前置: ollama 已 pull qwen2.5vl:7b 和 minicpm-v:4.5;缺则 exit 2 并给指引。
产出: <runs>/s0_acceptance/<UTC时间戳>/evidence.{json,md}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx

REQUIRED_MODELS = ("qwen2.5vl:7b", "minicpm-v:4.5")
ANCHORS = ("ACME-INV-2026-001", "4200")
PDF_DPI = 150


def check_models() -> list[str]:
    tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=10).json()
    have = {m["name"] for m in tags.get("models", [])}
    return [m for m in REQUIRED_MODELS if m not in have and f"{m}:latest" not in have]


def make_samples(sample_dir: Path) -> None:
    import fitz

    sample_dir.mkdir(parents=True, exist_ok=True)
    # 单页发票 PNG:文本渲染进图,锚词必须出现在图面上
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "INVOICE ACME-INV-2026-001", fontsize=18)
    page.insert_text((72, 110), "Vendor: ACME GmbH   Total: 4200 EUR", fontsize=14)
    page.get_pixmap(dpi=PDF_DPI).save(str(sample_dir / "invoice.png"))
    doc.close()
    # 2 页 PDF
    doc = fitz.open()
    p1 = doc.new_page(); p1.insert_text((72, 72), "Contract ACME-INV-2026-001 page one", fontsize=14)
    p2 = doc.new_page(); p2.insert_text((72, 72), "Payment terms: 4200 EUR net 30", fontsize=14)
    doc.save(str(sample_dir / "contract.pdf")); doc.close()


def run_lane(lane: str, mode: str | None, samples: Path, out_dir: Path) -> dict:
    os.environ["MASE_DB_PATH"] = str(out_dir / f"lane_{lane}.db")
    os.environ["MASE_MEDIA_ASSETS_DIR"] = str(out_dir / f"assets_{lane}")
    from mase.multimodal.ingest import ingest_folder  # env 设好后再导入使用
    from mase_tools.memory.api import mase2_get_media_provenance, mase2_search_memory

    started = time.perf_counter()
    report = ingest_folder(samples, mode=mode)
    elapsed = time.perf_counter() - started

    failures: list[str] = []
    if report.extractions < 2:
        failures.append(f"extractions={report.extractions} < 2")
    if report.infra_errors:
        failures.append(f"infra_errors={list(report.infra_errors)}")
    recall_hits = {}
    for anchor in ANCHORS:
        hits = mase2_search_memory([anchor], limit=5)
        recall_hits[anchor] = any(anchor in str(h.get("content", "")) for h in hits)
        if not recall_hits[anchor]:
            failures.append(f"anchor {anchor!r} not recalled")
    # 溯源链抽样:随便取一条带 source_media_id 的事实走到底
    # ...(实现:sqlite 查 entity_state 第一行 source_media_id → provenance → 断言 asset 文件存在)
    return {
        "lane": lane, "mode": mode, "elapsed_seconds": round(elapsed, 2),
        "report": {"processed": list(report.processed), "extractions": report.extractions,
                   "facts_written": report.facts_written,
                   "skipped": list(report.skipped), "infra_errors": list(report.infra_errors)},
        "recall_hits": recall_hits, "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", default=os.environ.get("MASE_RUNS_DIR", "../MASE-runs"))
    args = parser.parse_args()

    missing = check_models()
    if missing:
        for m in missing:
            print(f"[missing] ollama pull {m}")
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.runs_dir).resolve() / "s0_acceptance" / stamp
    samples = out_dir / "samples"
    make_samples(samples)

    lanes = [run_lane("qwen25vl", None, samples, out_dir), run_lane("minicpm", "minicpm", samples, out_dir)]
    evidence = {"timestamp_utc": stamp, "pdf_dpi": PDF_DPI, "anchors": list(ANCHORS),
                "models": list(REQUIRED_MODELS), "lanes": lanes,
                "verdict": "PASS" if not any(lane["failures"] for lane in lanes) else "FAIL"}
    (out_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    # evidence.md:人读版摘要(模型/用时/facts数/召回/verdict 表格)
    # ...
    print(f"[evidence] {out_dir / 'evidence.json'}  verdict={evidence['verdict']}")
    for lane in lanes:
        for failure in lane["failures"]:
            print(f"  [FAIL {lane['lane']}] {failure}")
    return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

(标 `# ...` 的两处按注释补全:溯源链抽样 = sqlite 连 lane DB 查 `entity_state WHERE source_media_id IS NOT NULL LIMIT 1` → `mase2_get_media_provenance` → `asset_path(sha256)` 存在断言;evidence.md = 从 evidence dict 渲染 markdown 表。)

- [ ] **Step 2: mypy 纳入新包**

`pyproject.toml` `[tool.mypy]` 的 `files` 列表追加 `"src/mase/multimodal"`。
Run: `python -m mypy`
Expected: `Success: no issues found`(有错就修到绿,不放宽配置)

- [ ] **Step 3: 全量质量门(README 声明集)**

```bash
python -m pytest -q -m "not integration and not slow"
python -m ruff check .
python -m mypy
python -m compileall -q -x "(legacy_archive|run_artifacts|dist|build|\.venv|venv|memory|benchmarks[\\/]external-benchmarks|__pycache__|\.pytest_cache)" .
python scripts/audit_repo_hygiene.py --strict
python scripts/audit_anti_overfit.py --strict
git diff --check
```

Expected: 全绿。(前端三条命令本次无 frontend 改动,跑通即可,失败若与本特性无关则如实上报不掩盖。)

- [ ] **Step 4: 提交**

```bash
git add scripts/run_s0_acceptance.py pyproject.toml
git commit -m "feat(multimodal): S0 acceptance harness with dual-model evidence"
```

- [ ] **Step 5: 真模型验收(标"待验收"→"完成"的唯一途径)**

```bash
ollama pull qwen2.5vl:7b
ollama pull minicpm-v:4.5
python -X utf8 scripts/run_s0_acceptance.py --runs-dir E:/MASE-runs
```

Expected: `verdict=PASS`,evidence 文件落 `E:/MASE-runs/s0_acceptance/<ts>/`。
⚠️ 两个模型共约 11–12GB 下载 + 显存占用,执行前向用户确认时机。**此步未跑或未 PASS 时,S0 只能标"待验收",绝不标完成**(evidence 文件是完成的定义)。

- [ ] **Step 6: 收口(验收 PASS 后)**

CHANGELOG.md 记一条 `## v0.5.0 - S0 multimodal ingestion foundation`(含 evidence 路径),单独提交:

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record S0 multimodal ingestion milestone"
```

打 tag 与否由用户决定(全局纪律:tag 前 CHANGELOG 已记录)。

---

## Self-Review(已执行)

1. **Spec 覆盖**:§4 模块布局 → Task 3-9;§5 schema → Task 1-2;§6 数据流 → Task 8;§7 模型集成/双模型 → Task 7;§8 安全边界 → Task 4(读 jail)+ Task 3(写 jail)+ Task 8(编排处两道检查);§9 错误处理 → Task 8(隔离/幂等)+ Task 5(缺依赖);§10 测试策略 → 各任务 Step 1 + Task 10 验收;§11 依赖/门禁 → Task 5(extra)+ Task 10(全门+证据);§12 非目标未越界。无缺口。
2. **占位符**:Task 10 harness 两处 `# ...` 均带明确补全说明(查询语句/渲染来源),非悬空 TBD;其余任务代码完整。
3. **类型一致性**:`PageImage(index, image_bytes, media_type)`、`ExtractionResult(full_text, candidate_facts, extractor_name, model_name, extractor_version, warnings)`、`IngestReport(processed, skipped, infra_errors, extractions, facts_written)`、`mase2_*` 签名——跨任务引用逐一核对一致;`store_bytes` 返回 `(sha256, Path)` 在 Task 3/8 一致;`find_extraction` 关键字参数在 Task 1/8 一致。
