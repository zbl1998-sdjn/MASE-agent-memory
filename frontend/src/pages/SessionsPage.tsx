import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { StatusLine } from "../components/StatusLine";
import type { JsonRecord, Scope } from "../types";

type SessionsPageProps = {
  scope: Scope;
  readOnly: boolean;
};

export function SessionsPage({ scope, readOnly }: SessionsPageProps) {
  const [sessionId, setSessionId] = useState("default");
  const [includeExpired, setIncludeExpired] = useState(false);
  const [rows, setRows] = useState<JsonRecord[]>([]);
  const [selectedRow, setSelectedRow] = useState<JsonRecord>();
  const [form, setForm] = useState({ context_key: "", context_value: "", ttl_days: "" });
  const [metadata, setMetadata] = useState("{}");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await api.getSessionState(sessionId, scope, includeExpired);
      setRows(response.data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly) {
      setMessage("只读模式：Session State 写入已禁用");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      await api.upsertSessionState(
        {
          session_id: sessionId,
          context_key: form.context_key,
          context_value: form.context_value,
          ttl_days: form.ttl_days ? Number(form.ttl_days) : undefined,
          metadata: metadata.trim() ? JSON.parse(metadata) : {}
        },
        scope
      );
      setMessage("Session state 已保存");
      setForm({ context_key: "", context_value: "", ttl_days: "" });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function forget(row: JsonRecord) {
    if (readOnly) {
      setMessage("只读模式：Session State 删除已禁用");
      return;
    }
    const key = String(row.context_key ?? "");
    setLoading(true);
    try {
      await api.forgetSessionState(sessionId, key || undefined, scope);
      setMessage(key ? `已删除 ${key}` : "已删除整个 session");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid two">
      <Card title="Session State 查询" subtitle="短期上下文、TTL 和元数据">
        <div className="toolbar">
          <label>
            Session ID
            <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={includeExpired}
              onChange={(event) => setIncludeExpired(event.target.checked)}
            />
            包含过期
          </label>
          <button type="button" onClick={load}>
            查询
          </button>
        </div>
        <StatusLine loading={loading} error={error} message={message} />
        <DataTable
          rows={rows}
          preferredColumns={["session_id", "context_key", "context_value", "expires_at", "updated_at"]}
          onSelect={setSelectedRow}
        />
        {selectedRow && (
          <button type="button" className="danger" disabled={readOnly} onClick={() => forget(selectedRow)}>
            删除选中上下文
          </button>
        )}
      </Card>
      <Card title="写入 Session State">
        <form className="stack-form" onSubmit={save}>
          <label>
            Context Key
            <input
              value={form.context_key}
              onChange={(event) => setForm({ ...form, context_key: event.target.value })}
              required
            />
          </label>
          <label>
            Context Value
            <textarea
              value={form.context_value}
              onChange={(event) => setForm({ ...form, context_value: event.target.value })}
              required
            />
          </label>
          <label>
            TTL Days
            <input value={form.ttl_days} onChange={(event) => setForm({ ...form, ttl_days: event.target.value })} />
          </label>
          <label>
            Metadata JSON
            <textarea value={metadata} onChange={(event) => setMetadata(event.target.value)} />
          </label>
          <button type="submit" disabled={readOnly}>保存上下文</button>
        </form>
      </Card>
    </div>
  );
}
