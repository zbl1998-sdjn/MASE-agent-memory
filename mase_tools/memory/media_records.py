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
