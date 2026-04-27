import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_DB_FILENAME = "benchmark_memory.sqlite3"


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _freshness_bucket(value: Any) -> str:
    ts = _coerce_datetime(value)
    if ts is None:
        return "unknown"
    if ts.tzinfo is None or ts.utcoffset() is None:
        age = datetime.now() - ts
    else:
        age = datetime.now(UTC) - ts.astimezone(UTC)
    if age <= timedelta(days=2):
        return "fresh"
    if age <= timedelta(days=30):
        return "recent"
    if age <= timedelta(days=180):
        return "aging"
    return "stale"


def _normalize_scope_value(value: str | None) -> str:
    return str(value or "")


def _normalize_visibility(value: str | None) -> str:
    text = str(value or "private").strip()
    return text or "private"


def _build_scope_filters(
    *,
    alias: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> tuple[list[str], list[Any]]:
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    if tenant_id is not None:
        clauses.append(f"COALESCE({prefix}tenant_id, '') = ?")
        params.append(_normalize_scope_value(tenant_id))
    if workspace_id is not None:
        clauses.append(f"COALESCE({prefix}workspace_id, '') = ?")
        params.append(_normalize_scope_value(workspace_id))
    if visibility is not None:
        clauses.append(f"COALESCE({prefix}visibility, 'private') = ?")
        params.append(_normalize_visibility(visibility))
    return clauses, params


def _primary_key_columns(cursor: sqlite3.Cursor, table_name: str) -> list[str]:
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    keyed = [row for row in rows if int(row[5] or 0) > 0]
    keyed.sort(key=lambda row: int(row[5] or 0))
    return [str(row[1]) for row in keyed]


def _resolve_memory_dir(config_path: str | Path | None = None) -> Path:
    """Resolve the memory directory without creating it at import time."""
    env_memory_dir = os.environ.get("MASE_MEMORY_DIR")
    if env_memory_dir:
        return Path(env_memory_dir).expanduser().resolve()

    try:
        from src.mase.model_interface import resolve_config_path  # noqa: PLC0415
    except ImportError:
        try:
            from mase.model_interface import resolve_config_path  # noqa: PLC0415
        except ImportError:
            resolve_config_path = None

    if resolve_config_path is not None:
        return resolve_config_path(config_path).parent / "memory"

    project_root = Path(__file__).resolve().parents[2]
    return project_root / "memory"


def resolve_db_path(config_path: str | Path | None = None) -> Path:
    """Resolve the canonical memory DB path.

    Priority:
    1. ``MASE_DB_PATH`` explicit file override
    2. ``MASE_MEMORY_DIR`` + canonical DB filename
    3. config-derived memory dir + canonical DB filename

    Path resolution stays side-effect free; actual DB operations create parent
    directories in ``get_connection()`` / ``init_db()``.
    """
    env_db = os.environ.get("MASE_DB_PATH")
    if env_db:
        return Path(env_db).expanduser().resolve()

    return _resolve_memory_dir(config_path) / DEFAULT_DB_FILENAME


def _active_db_path(
    db_path: str | Path | None = None,
    *,
    config_path: str | Path | None = None,
) -> Path:
    """Resolve the active DB path, evaluating env vars dynamically.

    When any of the three standard env overrides (MASE_DB_PATH, MASE_MEMORY_DIR,
    MASE_CONFIG_PATH) is present — even if set *after* module import — call
    ``resolve_db_path()`` so the full precedence chain is re-evaluated at
    call-time. This aligns ``get_connection()`` and ``BenchmarkNotetaker`` in
    all normal runtime + benchmark flows without requiring an explicit db_path.

    Falls back to the module-level ``DB_PATH`` constant only when no env var
    override is active, preserving backward compatibility with tests that
    monkeypatch ``db_core.DB_PATH`` directly (e.g. the ``fresh_db`` fixture).
    """
    if db_path is not None:
        return Path(db_path).expanduser().resolve()
    if (
        os.environ.get("MASE_DB_PATH")
        or os.environ.get("MASE_MEMORY_DIR")
        or os.environ.get("MASE_CONFIG_PATH")
        or config_path is not None
    ):
        return resolve_db_path(config_path)
    return DB_PATH


DB_PATH = resolve_db_path()

# Track which db files we've already migrated this process so that the
# `get_connection()` hot path doesn't re-run DDL on every call. This is the
# unified entry point that replaces the old module-level `init_db()` side-effect
# (which fired at import time and made every test suite touch real disk).
_SCHEMA_READY: set[str] = set()


def _ensure_schema(db_path: Path) -> None:
    key = str(db_path)
    if key in _SCHEMA_READY:
        return
    # 1) legacy baseline (entity_state, fts triggers, supersede columns, …)
    _create_legacy_schema(db_path)
    # 2) forward migrations on top (schema_version-tracked evolutions)
    try:
        from src.mase.schema_migrations import migrate as _migrate  # noqa: PLC0415
    except ImportError:
        try:
            from mase.schema_migrations import migrate as _migrate  # noqa: PLC0415
        except ImportError:
            _migrate = None
    if _migrate is not None:
        try:
            _migrate(db_path)
        except sqlite3.OperationalError as exc:
            # Real DDL failure: log and re-raise. Silent skip would let the
            # process run on a half-migrated schema and explode later in
            # business code with cryptic SQL errors. Loud failure here is
            # ten times cheaper to debug than ghost SQL errors downstream.
            import logging
            logging.getLogger("mase.memory").error(
                "schema_migration_failed db_path=%s err=%s", db_path, exc,
            )
            raise
        except ImportError:
            # Import-time failure of the migrations module is a packaging bug;
            # tolerate so that bare `import db_core` still works in stripped envs.
            pass
    _SCHEMA_READY.add(key)

# 预定义的 Profile 模板（实体维度约束），防模型乱造属性名
PROFILE_TEMPLATES = [
    "user_preferences",  # 用户喜好、厌恶、习惯
    "people_relations",  # 人物、职业、亲属关系
    "project_status",    # 项目代号、进度、配置
    "finance_budget",    # 预算、花销、金额记录
    "location_events",   # 去过的地方、居住地、活动地点
    "general_facts"      # 兜底事实
]

def get_connection(
    db_path: str | Path | None = None,
    *,
    config_path: str | Path | None = None,
) -> sqlite3.Connection:
    # Honour the module-level DB_PATH (so tests can monkeypatch it), but
    # always re-check the env var first in case it was set after import.
    db_path = _active_db_path(db_path, config_path=config_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema(db_path)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    # Concurrency safety: WAL lets readers run alongside one writer, busy_timeout
    # eliminates the SQLITE_BUSY storm when the async GC agent and the main
    # notetaker race. synchronous=NORMAL is the standard WAL pairing.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.DatabaseError:
        # Some older SQLite builds reject WAL on network filesystems; fall back silently.
        pass
    return conn

def init_db(
    db_path: str | Path | None = None,
    *,
    config_path: str | Path | None = None,
):
    """Backwards-compat entry point. Real work happens in `_create_legacy_schema`,
    invoked lazily by `get_connection` -> `_ensure_schema`. Tests and examples that
    still call `init_db()` directly remain supported."""
    db_path = _active_db_path(db_path, config_path=config_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _create_legacy_schema(db_path)
    _SCHEMA_READY.add(str(db_path))


def _create_legacy_schema(db_path: Path) -> None:
    """Create the MASE 2.0 white-box memory schema on a fresh DB (idempotent)."""
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        cursor = conn.cursor()

        # 1. 创建流水账表 (Append Only)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("PRAGMA table_info(memory_log)")
        log_cols = {row[1] for row in cursor.fetchall()}
        if "timestamp" not in log_cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN timestamp DATETIME")
            if "created_at" in log_cols:
                cursor.execute(
                    """
                    UPDATE memory_log
                    SET timestamp = created_at
                    WHERE timestamp IS NULL AND created_at IS NOT NULL
                    """
                )
            log_cols.add("timestamp")

        # 2. 创建基于 FTS5 的虚拟全文检索表
        # 使用 unicode61 tokenize 分词
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content,
                tokenize='unicode61'
            )
        """)

        # 3. 创建实体状态表 (Upsert)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_state (
                category TEXT,
                entity_key TEXT,
                entity_value TEXT,
                source_log_id INTEGER,
                source_reason TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                importance_score REAL DEFAULT 0.5,
                ttl_days INTEGER,
                will_expire_at DATETIME,
                archived INTEGER DEFAULT 0,
                tenant_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT '',
                visibility TEXT DEFAULT 'private',
                PRIMARY KEY (category, entity_key, tenant_id, workspace_id)
            )
        """)
        cursor.execute("PRAGMA table_info(entity_state)")
        entity_cols = {row[1] for row in cursor.fetchall()}
        if "source_log_id" not in entity_cols:
            cursor.execute("ALTER TABLE entity_state ADD COLUMN source_log_id INTEGER")
        if "source_reason" not in entity_cols:
            cursor.execute("ALTER TABLE entity_state ADD COLUMN source_reason TEXT")
        for _entity_col, _entity_def in [
            ("importance_score", "REAL DEFAULT 0.5"),
            ("ttl_days", "INTEGER"),
            ("will_expire_at", "DATETIME"),
            ("archived", "INTEGER DEFAULT 0"),
            ("tenant_id", "TEXT NOT NULL DEFAULT ''"),
            ("workspace_id", "TEXT NOT NULL DEFAULT ''"),
            ("visibility", "TEXT DEFAULT 'private'"),
        ]:
            if _entity_col not in entity_cols:
                cursor.execute(f"ALTER TABLE entity_state ADD COLUMN {_entity_col} {_entity_def}")
        if _primary_key_columns(cursor, "entity_state") != ["category", "entity_key", "tenant_id", "workspace_id"]:
            cursor.execute("ALTER TABLE entity_state RENAME TO entity_state_legacy")
            cursor.execute("""
                CREATE TABLE entity_state (
                    category TEXT,
                    entity_key TEXT,
                    entity_value TEXT,
                    source_log_id INTEGER,
                    source_reason TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    importance_score REAL DEFAULT 0.5,
                    ttl_days INTEGER,
                    will_expire_at DATETIME,
                    archived INTEGER DEFAULT 0,
                    tenant_id TEXT NOT NULL DEFAULT '',
                    workspace_id TEXT NOT NULL DEFAULT '',
                    visibility TEXT DEFAULT 'private',
                    PRIMARY KEY (category, entity_key, tenant_id, workspace_id)
                )
            """)
            cursor.execute("""
                INSERT INTO entity_state (
                    category,
                    entity_key,
                    entity_value,
                    source_log_id,
                    source_reason,
                    updated_at,
                    importance_score,
                    ttl_days,
                    will_expire_at,
                    archived,
                    tenant_id,
                    workspace_id,
                    visibility
                )
                SELECT
                    category,
                    entity_key,
                    entity_value,
                    source_log_id,
                    source_reason,
                    updated_at,
                    COALESCE(importance_score, 0.5),
                    ttl_days,
                    will_expire_at,
                    COALESCE(archived, 0),
                    COALESCE(tenant_id, ''),
                    COALESCE(workspace_id, ''),
                    COALESCE(visibility, 'private')
                FROM entity_state_legacy
            """)
            cursor.execute("DROP TABLE entity_state_legacy")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_state_source_log ON entity_state(source_log_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entity_state_scope ON entity_state(tenant_id, workspace_id, updated_at DESC)"
        )

        # 3.1 fact-supersede 审计历史表 (Mem0-style: 每次 UPDATE 留底)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_state_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                superseded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                supersede_reason TEXT,
                source_log_id INTEGER,
                tenant_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT '',
                visibility TEXT DEFAULT 'private'
            )
        """)
        cursor.execute("PRAGMA table_info(entity_state_history)")
        history_cols = {row[1] for row in cursor.fetchall()}
        for _history_col, _history_def in [
            ("tenant_id", "TEXT NOT NULL DEFAULT ''"),
            ("workspace_id", "TEXT NOT NULL DEFAULT ''"),
            ("visibility", "TEXT DEFAULT 'private'"),
        ]:
            if _history_col not in history_cols:
                cursor.execute(f"ALTER TABLE entity_state_history ADD COLUMN {_history_col} {_history_def}")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_eshist_key ON entity_state_history(category, entity_key)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_eshist_scope ON entity_state_history(tenant_id, workspace_id, superseded_at DESC)"
        )

        # 3.2 memory_log 增加 supersede 标记列 (老库自动迁移)
        cols = set(log_cols)
        if "superseded_at" not in cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN superseded_at DATETIME")
        if "superseded_by" not in cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN superseded_by INTEGER")
        if "supersede_reason" not in cols:
            cursor.execute("ALTER TABLE memory_log ADD COLUMN supersede_reason TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_log_superseded ON memory_log(superseded_at)"
        )
        # Add BenchmarkNotetaker columns so a shared DB (MASE_DB_PATH) is
        # fully compatible with BN writes. These have safe DEFAULT NULL / DEFAULT
        # CURRENT_TIMESTAMP so existing rows are unaffected.
        for _bn_col, _bn_def in [
            ("thread_label", "TEXT"),
            ("summary", "TEXT"),
            ("topic_tokens", "TEXT"),
            ("metadata", "TEXT"),
            ("created_at", "DATETIME"),
            ("consolidated", "INTEGER DEFAULT 0"),
            ("tenant_id", "TEXT"),
            ("workspace_id", "TEXT"),
            ("visibility", "TEXT DEFAULT 'private'"),
        ]:
            if _bn_col not in cols:
                cursor.execute(f"ALTER TABLE memory_log ADD COLUMN {_bn_col} {_bn_def}")
                if _bn_col == "created_at" and "timestamp" in cols:
                    cursor.execute(
                        """
                        UPDATE memory_log
                        SET created_at = timestamp
                        WHERE created_at IS NULL AND timestamp IS NOT NULL
                        """
                    )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS episodic_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                record_ids TEXT,
                source_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT,
                workspace_id TEXT,
                visibility TEXT DEFAULT 'private'
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_episodic_thread ON episodic_snapshot(thread_id, updated_at DESC)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS procedure_registry (
                procedure_key TEXT NOT NULL,
                procedure_type TEXT DEFAULT 'rule',
                content TEXT NOT NULL,
                metadata TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT '',
                visibility TEXT DEFAULT 'private',
                PRIMARY KEY (procedure_key, tenant_id, workspace_id)
            )
            """
        )
        if _primary_key_columns(cursor, "procedure_registry") != ["procedure_key", "tenant_id", "workspace_id"]:
            cursor.execute("ALTER TABLE procedure_registry RENAME TO procedure_registry_legacy")
            cursor.execute(
                """
                CREATE TABLE procedure_registry (
                    procedure_key TEXT NOT NULL,
                    procedure_type TEXT DEFAULT 'rule',
                    content TEXT NOT NULL,
                    metadata TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    tenant_id TEXT NOT NULL DEFAULT '',
                    workspace_id TEXT NOT NULL DEFAULT '',
                    visibility TEXT DEFAULT 'private',
                    PRIMARY KEY (procedure_key, tenant_id, workspace_id)
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO procedure_registry (
                    procedure_key,
                    procedure_type,
                    content,
                    metadata,
                    updated_at,
                    tenant_id,
                    workspace_id,
                    visibility
                )
                SELECT
                    procedure_key,
                    procedure_type,
                    content,
                    metadata,
                    updated_at,
                    COALESCE(tenant_id, ''),
                    COALESCE(workspace_id, ''),
                    COALESCE(visibility, 'private')
                FROM procedure_registry_legacy
                """
            )
            cursor.execute("DROP TABLE procedure_registry_legacy")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_procedure_type ON procedure_registry(procedure_type, updated_at DESC)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_procedure_scope ON procedure_registry(tenant_id, workspace_id, updated_at DESC)"
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session_context (
                session_id TEXT NOT NULL,
                context_key TEXT NOT NULL,
                context_value TEXT,
                metadata TEXT,
                expires_at DATETIME,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT NOT NULL DEFAULT '',
                workspace_id TEXT NOT NULL DEFAULT '',
                visibility TEXT DEFAULT 'private',
                PRIMARY KEY (session_id, context_key, tenant_id, workspace_id)
            )
            """
        )
        if _primary_key_columns(cursor, "session_context") != ["session_id", "context_key", "tenant_id", "workspace_id"]:
            cursor.execute("ALTER TABLE session_context RENAME TO session_context_legacy")
            cursor.execute(
                """
                CREATE TABLE session_context (
                    session_id TEXT NOT NULL,
                    context_key TEXT NOT NULL,
                    context_value TEXT,
                    metadata TEXT,
                    expires_at DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    tenant_id TEXT NOT NULL DEFAULT '',
                    workspace_id TEXT NOT NULL DEFAULT '',
                    visibility TEXT DEFAULT 'private',
                    PRIMARY KEY (session_id, context_key, tenant_id, workspace_id)
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO session_context (
                    session_id,
                    context_key,
                    context_value,
                    metadata,
                    expires_at,
                    updated_at,
                    tenant_id,
                    workspace_id,
                    visibility
                )
                SELECT
                    session_id,
                    context_key,
                    context_value,
                    metadata,
                    expires_at,
                    updated_at,
                    COALESCE(tenant_id, ''),
                    COALESCE(workspace_id, ''),
                    COALESCE(visibility, 'private')
                FROM session_context_legacy
                """
            )
            cursor.execute("DROP TABLE session_context_legacy")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_context_expiry ON session_context(expires_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_context_scope ON session_context(tenant_id, workspace_id, updated_at DESC)"
        )

        # 4. 建立触发器：当 memory_log 有新记录时，自动同步到 FTS 检索表
        # 注意: fts5 中的 rowid 不能显式指定 content_rowid 的列名去 insert，而是可以直接用 rowid
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_log_ai AFTER INSERT ON memory_log
            BEGIN
                INSERT INTO memory_fts(rowid, content) VALUES (new.id, new.content);
            END;
        """)

        # 建立触发器：删除时同步删除 (可选)
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS memory_log_ad AFTER DELETE ON memory_log
            BEGIN
                DELETE FROM memory_fts WHERE rowid = old.id;
            END;
        """)

        conn.commit()
    finally:
        conn.close()

def add_memory_log(
    thread_id: str,
    role: str,
    content: str,
    *,
    thread_label: str | None = None,
    summary: str | None = None,
    topic_tokens: str | None = None,
    metadata: str | None = None,
    created_at: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Write a memory_log row using the unified backend."""
    normalized_tenant = _normalize_scope_value(tenant_id)
    normalized_workspace = _normalize_scope_value(workspace_id)
    normalized_visibility = _normalize_visibility(visibility)
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO memory_log
                (
                    thread_id,
                    role,
                    content,
                    timestamp,
                    thread_label,
                    summary,
                    topic_tokens,
                    metadata,
                    created_at,
                    tenant_id,
                    workspace_id,
                    visibility
                )
            VALUES (?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?, ?)
            """,
            (
                thread_id,
                role,
                content,
                created_at,
                thread_label,
                summary,
                topic_tokens,
                metadata,
                created_at,
                normalized_tenant,
                normalized_workspace,
                normalized_visibility,
            ),
        )
        return cursor.lastrowid


def add_event_log(
    thread_id: str,
    role: str,
    content: str,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """写入流水账"""
    return add_memory_log(
        thread_id,
        role,
        content,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
        db_path=db_path,
    )


def _compute_expiry(ttl_days: int | None) -> str | None:
    if ttl_days is None:
        return None
    try:
        days = int(ttl_days)
    except (TypeError, ValueError):
        return None
    now = datetime.now(UTC)
    if days <= 0:
        return (now - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    return (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def search_event_log(
    keywords: list[str],
    limit: int = 5,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """使用 BM25 算法在流水账中做全文检索"""
    if not keywords:
        return []

    # 构建 FTS5 查询语句，例如: '预算 OR 追加'
    # 为了防止 SQL 注入或格式错误，过滤掉双引号
    clean_keywords = [k.replace('"', "").replace("'", "") for k in keywords if k.strip()]
    # 对于中文环境，由于 FTS5 的 unicode61 默认按空格或标点分词，
    # 如果不自己实现自定义分词器，一个简单的 workaround 是用通配符或 LIKE 结合
    # 这里我们使用简单的 match，同时如果没匹配到我们用 like 兜底（或者改成分字插入）
    match_query = " OR ".join(f'"{k}"' for k in clean_keywords)

    with closing(get_connection(db_path)) as conn:
        cursor = conn.cursor()
        scope_clauses, scope_params = _build_scope_filters(
            alias="m",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            visibility=visibility,
        )
        try:
            # 尝试全文检索
            cursor.execute('''
                SELECT m.*, COALESCE(m.timestamp, m.created_at) AS event_timestamp, bm25(memory_fts) AS score
                FROM memory_fts f
                JOIN memory_log m ON f.rowid = m.id
                WHERE memory_fts MATCH ? AND m.superseded_at IS NULL
            ''' + (" AND " + " AND ".join(scope_clauses) if scope_clauses else "") + '''
                ORDER BY bm25(memory_fts), m.id DESC
                LIMIT ?
            ''', (match_query, *scope_params, limit))
            results = [dict(row) for row in cursor.fetchall()]

            # 如果 FTS 因为中文分词没搜到，启动白盒机制：Like 兜底查询
            if not results:
                like_conditions = " OR ".join("content LIKE ?" for _ in clean_keywords)
                like_params = tuple(f"%{k}%" for k in clean_keywords)
                cursor.execute(f'''
                    SELECT *, COALESCE(timestamp, created_at) AS event_timestamp, 0 as score
                    FROM memory_log
                    WHERE ({like_conditions}) AND superseded_at IS NULL
                    {(" AND " + " AND ".join(clause.replace("m.", "") for clause in scope_clauses)) if scope_clauses else ""}
                    ORDER BY id DESC
                    LIMIT ?
                ''', like_params + tuple(scope_params) + (limit,))
                results = [dict(row) for row in cursor.fetchall()]

            return results
        except sqlite3.OperationalError as e:
            print(f"FTS Search Error: {e}")
            return []

def upsert_entity_fact(
    category: str,
    key: str,
    value: str,
    *,
    reason: str | None = None,
    source_log_id: int | None = None,
    importance_score: float | None = None,
    ttl_days: int | None = None,
    archived: bool = False,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
):
    """更新或插入实体状态（对抗时间篡改的核心）。

    更新时把旧值写入 ``entity_state_history``，形成审计链 (Mem0-style)。
    """
    if category not in PROFILE_TEMPLATES:
        category = "general_facts"
    normalized_tenant = _normalize_scope_value(tenant_id)
    normalized_workspace = _normalize_scope_value(workspace_id)
    normalized_visibility = _normalize_visibility(visibility)

    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                entity_value,
                source_log_id,
                source_reason,
                importance_score,
                ttl_days,
                archived,
                tenant_id,
                workspace_id,
                visibility
            FROM entity_state
            WHERE category = ? AND entity_key = ? AND tenant_id = ? AND workspace_id = ?
            """,
            (category, key, normalized_tenant, normalized_workspace),
        )
        row = cursor.fetchone()
        old_value = row["entity_value"] if row else None
        old_source_log_id = row["source_log_id"] if row else None
        old_source_reason = row["source_reason"] if row else None
        old_importance = row["importance_score"] if row and "importance_score" in row.keys() else None
        old_ttl_days = row["ttl_days"] if row and "ttl_days" in row.keys() else None
        old_archived = row["archived"] if row and "archived" in row.keys() else 0
        old_tenant_id = row["tenant_id"] if row and "tenant_id" in row.keys() else None
        old_workspace_id = row["workspace_id"] if row and "workspace_id" in row.keys() else None
        old_visibility = row["visibility"] if row and "visibility" in row.keys() else None
        effective_source_log_id = source_log_id if source_log_id is not None else old_source_log_id
        effective_source_reason = reason if reason is not None else old_source_reason
        effective_importance = old_importance if importance_score is None else float(importance_score)
        effective_ttl_days = old_ttl_days if ttl_days is None else int(ttl_days)
        effective_archived = int(old_archived if archived is False and row else archived)
        effective_tenant_id = normalized_tenant if tenant_id is not None or row is None else old_tenant_id
        effective_workspace_id = (
            normalized_workspace if workspace_id is not None or row is None else old_workspace_id
        )
        effective_visibility = (
            normalized_visibility if visibility is not None or row is None else (old_visibility or "private")
        )
        effective_expiry = _compute_expiry(effective_ttl_days)

        # ON CONFLICT(category, entity_key, tenant_id, workspace_id) 依赖于 scoped PK 约束
        cursor.execute('''
            INSERT INTO entity_state (
                category, entity_key, entity_value, source_log_id, source_reason, updated_at,
                importance_score, ttl_days, will_expire_at, archived, tenant_id, workspace_id, visibility
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(category, entity_key, tenant_id, workspace_id)
            DO UPDATE SET
                entity_value=excluded.entity_value,
                source_log_id=excluded.source_log_id,
                source_reason=excluded.source_reason,
                importance_score=excluded.importance_score,
                ttl_days=excluded.ttl_days,
                will_expire_at=excluded.will_expire_at,
                archived=excluded.archived,
                tenant_id=excluded.tenant_id,
                workspace_id=excluded.workspace_id,
                visibility=excluded.visibility,
                updated_at=CURRENT_TIMESTAMP
        ''', (
            category,
            key,
            value,
            effective_source_log_id,
            effective_source_reason,
            effective_importance if effective_importance is not None else 0.5,
            effective_ttl_days,
            effective_expiry,
            effective_archived,
            effective_tenant_id,
            effective_workspace_id,
            effective_visibility,
        ))

        # 仅当值真正变化时记录一条历史
        if old_value is not None and old_value != value:
            cursor.execute(
                """
                INSERT INTO entity_state_history
                    (
                        category,
                        entity_key,
                        old_value,
                        new_value,
                        supersede_reason,
                        source_log_id,
                        tenant_id,
                        workspace_id,
                        visibility
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    category,
                    key,
                    old_value,
                    value,
                    reason or "user_correction",
                    source_log_id,
                    effective_tenant_id,
                    effective_workspace_id,
                    effective_visibility,
                ),
            )


def get_entity_fact_history(
    category: str | None = None,
    entity_key: str | None = None,
    limit: int = 50,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> list[dict[str, Any]]:
    """查询事实审计链。无参 → 全表最新若干条；指定 (category, key) → 该字段全部历史。"""
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        scope_clauses, scope_params = _build_scope_filters(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            visibility=visibility,
        )
        if category and entity_key:
            sql = "SELECT * FROM entity_state_history WHERE category=? AND entity_key=?"
            params: list[Any] = [category, entity_key]
            if scope_clauses:
                sql += " AND " + " AND ".join(scope_clauses)
                params.extend(scope_params)
            sql += " ORDER BY id DESC"
            cursor.execute(
                sql,
                params,
            )
        elif category:
            sql = "SELECT * FROM entity_state_history WHERE category=?"
            params = [category]
            if scope_clauses:
                sql += " AND " + " AND ".join(scope_clauses)
                params.extend(scope_params)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cursor.execute(
                sql,
                params,
            )
        else:
            sql = "SELECT * FROM entity_state_history"
            params = []
            if scope_clauses:
                sql += " WHERE " + " AND ".join(scope_clauses)
                params.extend(scope_params)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            cursor.execute(
                sql,
                params,
            )
        return [dict(row) for row in cursor.fetchall()]


def supersede_log_entries(
    keywords: list[str],
    replacement_log_id: int,
    reason: str = "user_correction",
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> int:
    """把所有 FTS 命中 ``keywords`` 的 *未被覆盖* 流水账标记为 superseded。

    用于"我之前说错了" 类型的更正：旧的不删除（保留审计），但默认搜索/事实表不再返回。
    返回标记的行数。
    """
    if not keywords:
        return 0
    clean = [k.replace('"', "").replace("'", "") for k in keywords if k.strip()]
    if not clean:
        return 0
    match_query = " OR ".join(f'"{k}"' for k in clean)

    with closing(get_connection()) as conn, conn:
        cursor = conn.cursor()
        scope_clauses, scope_params = _build_scope_filters(
            alias="m",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            visibility=visibility,
        )
        try:
            cursor.execute(
                '''
                SELECT m.id FROM memory_fts f
                JOIN memory_log m ON f.rowid = m.id
                WHERE memory_fts MATCH ? AND m.superseded_at IS NULL AND m.id != ?
                '''
                + (" AND " + " AND ".join(scope_clauses) if scope_clauses else ""),
                (match_query, replacement_log_id, *scope_params),
            )
            ids = [row["id"] for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            ids = []

        # FTS miss → LIKE 兜底（中文场景）
        if not ids:
            like_conditions = " OR ".join("content LIKE ?" for _ in clean)
            like_params = tuple(f"%{k}%" for k in clean)
            cursor.execute(
                f'''
                SELECT id FROM memory_log
                WHERE ({like_conditions}) AND superseded_at IS NULL AND id != ?
                {(" AND " + " AND ".join(clause.replace("m.", "") for clause in scope_clauses)) if scope_clauses else ""}
                ''',
                like_params + (replacement_log_id,) + tuple(scope_params),
            )
            ids = [row["id"] for row in cursor.fetchall()]

        if not ids:
            return 0

        placeholders = ",".join("?" * len(ids))
        cursor.execute(
            f"""
            UPDATE memory_log
            SET superseded_at=CURRENT_TIMESTAMP, superseded_by=?, supersede_reason=?
            WHERE id IN ({placeholders})
            """,
            (replacement_log_id, reason, *ids),
        )
        return len(ids)

def get_entity_facts(
    category: str = None,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> list[dict[str, Any]]:
    """获取最新的实体状态档案"""
    with closing(get_connection()) as conn:
        cursor = conn.cursor()
        scope_clauses, scope_params = _build_scope_filters(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            visibility=visibility,
        )
        if category:
            sql = "SELECT * FROM entity_state WHERE category = ? AND COALESCE(archived, 0) = 0"
            params: list[Any] = [category]
            if scope_clauses:
                sql += " AND " + " AND ".join(scope_clauses)
                params.extend(scope_params)
            sql += " ORDER BY updated_at DESC"
            cursor.execute(
                sql,
                params,
            )
        else:
            sql = "SELECT * FROM entity_state WHERE COALESCE(archived, 0) = 0"
            params = []
            if scope_clauses:
                sql += " AND " + " AND ".join(scope_clauses)
                params.extend(scope_params)
            sql += " ORDER BY category, updated_at DESC"
            cursor.execute(
                sql,
                params,
            )
        return [dict(row) for row in cursor.fetchall()]


def upsert_session_context(
    session_id: str,
    context_key: str,
    context_value: str,
    *,
    metadata: dict[str, Any] | None = None,
    ttl_days: int | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str = "private",
    db_path: str | Path | None = None,
) -> None:
    expires_at = _compute_expiry(ttl_days)
    normalized_tenant = _normalize_scope_value(tenant_id)
    normalized_workspace = _normalize_scope_value(workspace_id)
    normalized_visibility = _normalize_visibility(visibility)
    with closing(get_connection(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO session_context
                (session_id, context_key, context_value, metadata, expires_at, updated_at, tenant_id, workspace_id, visibility)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            ON CONFLICT(session_id, context_key, tenant_id, workspace_id)
            DO UPDATE SET
                context_value=excluded.context_value,
                metadata=excluded.metadata,
                expires_at=excluded.expires_at,
                tenant_id=excluded.tenant_id,
                workspace_id=excluded.workspace_id,
                visibility=excluded.visibility,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                session_id,
                context_key,
                context_value,
                json.dumps(metadata or {}, ensure_ascii=False),
                expires_at,
                normalized_tenant,
                normalized_workspace,
                normalized_visibility,
            ),
        )


def get_session_context(
    session_id: str,
    *,
    include_expired: bool = False,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM session_context WHERE session_id = ?"
    params: list[Any] = [session_id]
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    if scope_clauses:
        sql += " AND " + " AND ".join(scope_clauses)
        params.extend(scope_params)
    if not include_expired:
        sql += " AND (expires_at IS NULL OR datetime(expires_at) > datetime('now'))"
    sql += " ORDER BY updated_at DESC"
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def delete_session_context(
    session_id: str,
    *,
    context_key: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    with closing(get_connection(db_path)) as conn, conn:
        sql = "DELETE FROM session_context WHERE session_id = ?"
        params: list[Any] = [session_id]
        if context_key is None:
            pass
        else:
            sql += " AND context_key = ?"
            params.append(context_key)
        if scope_clauses:
            sql += " AND " + " AND ".join(scope_clauses)
            params.extend(scope_params)
        cursor = conn.execute(sql, params)
        return int(cursor.rowcount or 0)


def gc_expired_session_context(*, db_path: str | Path | None = None) -> int:
    with closing(get_connection(db_path)) as conn, conn:
        cursor = conn.execute(
            "DELETE FROM session_context WHERE expires_at IS NOT NULL AND expires_at <= CURRENT_TIMESTAMP"
        )
        return int(cursor.rowcount or 0)


def register_procedure(
    procedure_key: str,
    content: str,
    *,
    procedure_type: str = "rule",
    metadata: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str = "private",
    db_path: str | Path | None = None,
) -> None:
    normalized_tenant = _normalize_scope_value(tenant_id)
    normalized_workspace = _normalize_scope_value(workspace_id)
    normalized_visibility = _normalize_visibility(visibility)
    with closing(get_connection(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO procedure_registry
                (procedure_key, procedure_type, content, metadata, updated_at, tenant_id, workspace_id, visibility)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            ON CONFLICT(procedure_key, tenant_id, workspace_id)
            DO UPDATE SET
                procedure_type=excluded.procedure_type,
                content=excluded.content,
                metadata=excluded.metadata,
                tenant_id=excluded.tenant_id,
                workspace_id=excluded.workspace_id,
                visibility=excluded.visibility,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                procedure_key,
                procedure_type,
                content,
                json.dumps(metadata or {}, ensure_ascii=False),
                normalized_tenant,
                normalized_workspace,
                normalized_visibility,
            ),
        )


def list_procedures(
    *,
    procedure_type: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM procedure_registry"
    params: list[Any] = []
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    where_clauses: list[str] = []
    if procedure_type:
        where_clauses.append("procedure_type = ?")
        params.append(procedure_type)
    if scope_clauses:
        where_clauses.extend(scope_clauses)
        params.extend(scope_params)
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY updated_at DESC"
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def consolidate_thread(
    thread_id: str,
    *,
    max_items: int = 50,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    with closing(get_connection(db_path)) as conn, conn:
        sql = """
            SELECT id, role, content, summary, tenant_id, workspace_id, visibility
            FROM memory_log
            WHERE thread_id = ? AND COALESCE(consolidated, 0) = 0
        """
        params: list[Any] = [thread_id]
        if scope_clauses:
            sql += " AND " + " AND ".join(scope_clauses)
            params.extend(scope_params)
        sql += " ORDER BY id ASC LIMIT ?"
        params.append(max_items)
        rows = conn.execute(sql, params).fetchall()
        materialized = [dict(row) for row in rows]
        if not materialized:
            return {"snapshot_id": None, "summary": "", "source_count": 0}
        snippets: list[str] = []
        for row in materialized:
            summary = str(row.get("summary") or "").strip()
            content = str(row.get("content") or "").strip()
            text = summary or content
            if text:
                snippets.append(text[:120])
        summary_text = " | ".join(snippets[:8])[:800]
        record_ids = [int(row["id"]) for row in materialized if row.get("id") is not None]
        first_row = materialized[0]
        effective_tenant = _normalize_scope_value(first_row.get("tenant_id"))
        effective_workspace = _normalize_scope_value(first_row.get("workspace_id"))
        effective_visibility = _normalize_visibility(first_row.get("visibility"))
        cursor = conn.execute(
            """
            INSERT INTO episodic_snapshot
                (
                    thread_id,
                    summary,
                    record_ids,
                    source_count,
                    updated_at,
                    tenant_id,
                    workspace_id,
                    visibility
                )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            """,
            (
                thread_id,
                summary_text or f"{thread_id} consolidated snapshot",
                json.dumps(record_ids, ensure_ascii=False),
                len(record_ids),
                effective_tenant,
                effective_workspace,
                effective_visibility,
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        placeholders = ",".join("?" * len(record_ids))
        conn.execute(
            f"UPDATE memory_log SET consolidated = 1 WHERE id IN ({placeholders})",
            record_ids,
        )
        return {
            "snapshot_id": snapshot_id,
            "summary": summary_text,
            "source_count": len(record_ids),
            "record_ids": record_ids,
        }


def list_episodic_snapshots(
    *,
    thread_id: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM episodic_snapshot"
    params: list[Any] = []
    where_clauses: list[str] = []
    if thread_id:
        where_clauses.append("thread_id = ?")
        params.append(thread_id)
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    if scope_clauses:
        where_clauses.extend(scope_clauses)
        params.extend(scope_params)
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY updated_at DESC"
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def archive_entity_fact(
    category: str,
    entity_key: str,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    with closing(get_connection(db_path)) as conn, conn:
        sql = """
            UPDATE entity_state
            SET archived = 1, updated_at = CURRENT_TIMESTAMP
            WHERE category = ? AND entity_key = ?
        """
        params: list[Any] = [category, entity_key]
        if scope_clauses:
            sql += " AND " + " AND ".join(scope_clauses)
            params.extend(scope_params)
        cursor = conn.execute(sql, params)
        return int(cursor.rowcount or 0)


# ---------------------------------------------------------------------------
# Lightweight bilingual alias map for infra/config entity key terms.
# Kept minimal and conservative: only add pairs that are unambiguous.
# ---------------------------------------------------------------------------
_BILINGUAL_ALIASES: dict[str, list[str]] = {
    "服务器": ["server"],
    "端口": ["port"],
    "server": ["服务器"],
    "port": ["端口"],
    "密码": ["password", "passwd"],
    "password": ["密码"],
    "passwd": ["密码"],
    "用户名": ["username", "user"],
    "用户": ["user", "username"],
    "username": ["用户名", "用户"],
    "数据库": ["database", "db"],
    "database": ["数据库"],
    "主机": ["host"],
    "host": ["主机"],
    "地址": ["address", "addr"],
    "address": ["地址"],
    "配置": ["config", "configuration"],
    "config": ["配置"],
    "项目": ["project"],
    "project": ["项目"],
    "预算": ["budget"],
    "budget": ["预算"],
    "状态": ["status", "state"],
    "status": ["状态"],
    "版本": ["version"],
    "version": ["版本"],
    "路径": ["path"],
    "接口": ["interface", "api"],
    "api": ["接口"],
}


def _expand_entity_search_terms(keywords: list[str], max_terms: int = 20) -> list[str]:
    """Expand raw keyword list for entity_state LIKE matching.

    Transformations applied (in order, bounded by *max_terms*):
    1. Preserve original term.
    2. Lowercase variant.
    3. Split on underscores/hyphens → individual tokens (server_port → server, port).
    4. CJK bigrams/trigrams from Chinese runs.
    5. Bilingual alias lookup for each token and each CJK n-gram.
    """
    expanded: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        t = term.strip()
        if len(t) < 2:
            return
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        expanded.append(t)

    def _add_aliases(token: str) -> None:
        key = token.lower()
        for alias in _BILINGUAL_ALIASES.get(key, []):
            _add(alias)
        # Also try the original (non-lowered) form for CJK keys
        for alias in _BILINGUAL_ALIASES.get(token, []):
            _add(alias)

    for kw in keywords:
        raw = str(kw or "").strip()
        if not raw:
            continue
        _add(raw)
        _add(raw.lower())
        # Split on underscore / hyphen
        parts = re.split(r"[_\-]", raw)
        if len(parts) > 1:
            for part in parts:
                _add(part)
                _add(part.lower())
                _add_aliases(part)
        _add_aliases(raw)
        # CJK n-grams and alias expansion
        cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", raw)
        for run in cjk_runs:
            _add(run)
            _add_aliases(run)
            for size in (2, 3):
                if len(run) < size:
                    continue
                for i in range(len(run) - size + 1):
                    chunk = run[i : i + size]
                    _add(chunk)
                    _add_aliases(chunk)
        if len(expanded) >= max_terms:
            break

    return expanded[:max_terms]


def _score_entity_match(
    row: dict[str, Any],
    expanded_terms: list[str],
    original_keywords: list[str],
) -> int:
    """Lightweight match-quality score for an entity_state row.

    Higher is better.  Scoring rules (additive):
    - +3 per expanded term that appears in ``entity_key``
    - +2 per expanded term that appears in ``category``
    - +1 per expanded term that appears in ``entity_value``
    - +5 bonus when *all* Latin tokens derived from the original keywords are
      present in ``entity_key`` (multi-term hit, e.g. both "server" and "port"
      match "server_port")
    - +10 bonus for an exact ``entity_key`` == original keyword match

    The score intentionally ignores ``updated_at`` so that a newer but less
    relevant row (e.g. ``server_host`` vs ``server_port`` for query
    "服务器端口") does not displace the more relevant one.
    """
    key = (row.get("entity_key") or "").lower()
    cat = (row.get("category") or "").lower()
    value = str(row.get("entity_value") or "").lower()

    score = 0
    for t in expanded_terms:
        tl = t.lower()
        if tl in key:
            score += 3
        elif tl in cat:
            score += 2
        elif tl in value:
            score += 1

    # Multi-term bonus: all non-trivial Latin tokens from original keywords
    # must each appear in the entity_key.
    latin_tokens: list[str] = []
    for kw in original_keywords:
        for part in re.split(r"[_\-\s]+", kw):
            tok = part.lower()
            if len(tok) >= 3 and tok.isascii():
                latin_tokens.append(tok)
    # Also add any English alias tokens expanded from the original keywords
    for t in expanded_terms:
        tl = t.lower()
        if len(tl) >= 3 and tl.isascii() and tl not in latin_tokens:
            latin_tokens.append(tl)
    if latin_tokens and all(tok in key for tok in latin_tokens):
        score += 5

    # Exact key match
    for kw in original_keywords:
        if kw.lower() == key:
            score += 10

    return score


def search_entity_facts_by_keyword(
    keywords: list[str],
    limit: int = 20,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Keyword search over current facts with current provenance attached.

    Uses :func:`_expand_entity_search_terms` to expand raw keywords before
    building LIKE clauses, so Chinese natural-language queries (e.g. "服务器端口")
    can match machine-key entity facts (e.g. entity_key='server_port').

    Results are ordered by a lightweight match-quality score (exact/multi-term
    hits ranked higher) and then by ``updated_at DESC`` as a tiebreaker.  This
    prevents a newer but less relevant row (e.g. ``server_host``) from
    displacing the intended match (``server_port``) purely because of recency.
    """
    if not keywords:
        return []
    clean = [k.strip() for k in keywords if k.strip()]
    if not clean:
        return []
    expanded = _expand_entity_search_terms(clean)
    if not expanded:
        return []
    like_clauses: list[str] = []
    params: list[Any] = []
    for kw in expanded[:16]:
        like_clauses.append("(e.category LIKE ? OR e.entity_key LIKE ? OR e.entity_value LIKE ?)")
        params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])
    # Fetch a wider candidate set so the Python re-rank can find the best matches
    # even when updated_at would otherwise push them below the SQL LIMIT cut.
    fetch_limit = min(limit * 4, 80)
    scope_clauses, scope_params = _build_scope_filters(
        alias="e",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    sql = (
        """
        SELECT
            e.*,
            m.content AS source_content,
            m.thread_id AS source_thread_id,
            COALESCE(m.timestamp, m.created_at) AS source_timestamp,
            COALESCE(h.history_depth, 0) AS history_depth,
            h.last_superseded_at
        FROM entity_state e
        LEFT JOIN memory_log m ON m.id = e.source_log_id
        LEFT JOIN (
            SELECT
                category,
                entity_key,
                COUNT(*) AS history_depth,
                MAX(superseded_at) AS last_superseded_at
            FROM entity_state_history
            GROUP BY category, entity_key
        ) h ON h.category = e.category AND h.entity_key = e.entity_key
        WHERE (
        """
        + " OR ".join(like_clauses)
        + """
        ) AND COALESCE(e.archived, 0) = 0
          AND (e.will_expire_at IS NULL OR datetime(e.will_expire_at) > datetime('now'))
        """
        + (" AND " + " AND ".join(scope_clauses) if scope_clauses else "")
        + """
        ORDER BY e.updated_at DESC LIMIT ?
        """
    )
    params.extend(scope_params)
    params.append(fetch_limit)
    with closing(get_connection(db_path)) as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d.setdefault("id", None)
        d["_source"] = "entity_state"
        d["content"] = f"[FACT] {d.get('category', '')}.{d.get('entity_key', '')}: {d.get('entity_value', '')}"
        d["history_depth"] = int(d.get("history_depth") or 0)
        d["conflict_status"] = "updated" if d["history_depth"] else "stable"
        d["freshness"] = _freshness_bucket(d.get("updated_at"))
        d["confidence"] = "high"
        d["retrieval_reason"] = (
            "current_state_fact_with_history" if d["history_depth"] else "current_state_fact"
        )
        d["_match_score"] = _score_entity_match(d, expanded, clean)
        if d["_match_score"] <= 0:
            continue
        results.append(d)
    # Primary sort: match quality (desc); tiebreaker: recency (desc).
    results.sort(key=lambda r: (r["_match_score"], r.get("updated_at") or ""), reverse=True)
    for r in results:
        r.pop("_match_score", None)
    return results[:limit]


def search_entity_fact_history_by_keyword(
    keywords: list[str],
    limit: int = 20,
    *,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    if not keywords:
        return []
    clean = [k.strip() for k in keywords if k.strip()]
    if not clean:
        return []
    expanded = _expand_entity_search_terms(clean)
    if not expanded:
        return []
    like_clauses: list[str] = []
    params: list[Any] = []
    for kw in expanded[:16]:
        like_clauses.append(
            "(h.category LIKE ? OR h.entity_key LIKE ? OR h.old_value LIKE ? OR h.new_value LIKE ?)"
        )
        params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%"])
    scope_clauses, scope_params = _build_scope_filters(
        alias="h",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    sql = (
        """
        SELECT
            h.*,
            m.content AS source_content,
            m.thread_id AS source_thread_id,
            COALESCE(m.timestamp, m.created_at) AS source_timestamp
        FROM entity_state_history h
        LEFT JOIN memory_log m ON m.id = h.source_log_id
        WHERE
        """
        + " OR ".join(like_clauses)
        + (" AND " + " AND ".join(scope_clauses) if scope_clauses else "")
        + " ORDER BY h.superseded_at DESC, h.id DESC LIMIT ?"
    )
    params.extend(scope_params)
    params.append(limit)
    with closing(get_connection(db_path)) as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["_source"] = "entity_state_history"
        d["content"] = (
            f"[HIST] {d.get('category', '')}.{d.get('entity_key', '')}: "
            f"{d.get('old_value', '')} -> {d.get('new_value', '')}"
        )
        d["conflict_status"] = "superseded"
        d["freshness"] = _freshness_bucket(d.get("superseded_at"))
        d["confidence"] = "medium"
        d["retrieval_reason"] = "fact_history"
        results.append(d)
    return results


def facts_first_recall(
    keywords: list[str],
    *,
    full_query: str | None = None,
    limit: int = 5,
    include_history: bool = False,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Unified facts-first recall: current entity_state facts first, then event-log results.

    Every item in the returned list carries ``_source`` set to either
    ``'entity_state'`` (current facts) or ``'memory_log'`` (session evidence),
    giving callers full audit/source visibility without a separate call.

    ``full_query`` is accepted for API symmetry with BenchmarkNotetaker.search
    but is not used for entity_state (the LIKE search covers it via keywords).
    """
    del full_query  # reserved for future dense-retrieval integration
    facts = search_entity_facts_by_keyword(
        keywords,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
        db_path=db_path,
    )
    history = (
        search_entity_fact_history_by_keyword(
            keywords,
            limit=limit,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            visibility=visibility,
            db_path=db_path,
        )
        if include_history
        else []
    )
    logs = search_event_log(
        keywords,
        limit=limit,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
        db_path=db_path,
    )
    for log_item in logs:
        log_item.setdefault("_source", "memory_log")
    # Facts first; fill remaining slots with log results.
    remaining = max(0, limit - len(facts))
    if remaining == 0:
        return facts[:limit]
    history_slice = history[:remaining]
    remaining -= len(history_slice)
    return facts + history_slice + logs[:remaining]


def fetch_memory_rows(
    *,
    db_path: str | Path | None = None,
    limit: int | None = None,
    chronological: bool = False,
    include_superseded: bool = True,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    visibility: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT *, COALESCE(timestamp, created_at) AS event_timestamp FROM memory_log"
    params: list[Any] = []
    where_clauses: list[str] = []
    if not include_superseded:
        where_clauses.append("superseded_at IS NULL")
    scope_clauses, scope_params = _build_scope_filters(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        visibility=visibility,
    )
    if scope_clauses:
        where_clauses.extend(scope_clauses)
        params.extend(scope_params)
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id ASC" if chronological else " ORDER BY id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


# NOTE: schema is created lazily on first `get_connection()` (see `_ensure_schema`).
# We deliberately do NOT call init_db() at import time so that `import db_core`
# is side-effect-free — tests/CLIs that need only a constant or helper no longer
# touch the disk.
