import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { StatusLine } from "../components/StatusLine";
import type { JsonRecord, Scope } from "../types";

type ProceduresPageProps = {
  scope: Scope;
  readOnly: boolean;
};

export function ProceduresPage({ scope, readOnly }: ProceduresPageProps) {
  const [procedureType, setProcedureType] = useState("");
  const [rows, setRows] = useState<JsonRecord[]>([]);
  const [form, setForm] = useState({
    procedure_key: "",
    procedure_type: "rule",
    content: "",
    metadata: "{}"
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await api.procedures(scope, procedureType || undefined);
      setRows(response.data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [scope, procedureType]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly) {
      setMessage("只读模式：Procedure 注册已禁用");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      await api.registerProcedure(
        {
          procedure_key: form.procedure_key,
          procedure_type: form.procedure_type,
          content: form.content,
          metadata: form.metadata.trim() ? JSON.parse(form.metadata) : {}
        },
        scope
      );
      setMessage("Procedure 已注册");
      setForm({ procedure_key: "", procedure_type: "rule", content: "", metadata: "{}" });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid two">
      <Card title="Procedure 注册" subtitle="规则、工作流、工具说明等可复用程序记忆">
        <form className="stack-form" onSubmit={save}>
          <label>
            Key
            <input
              value={form.procedure_key}
              onChange={(event) => setForm({ ...form, procedure_key: event.target.value })}
              required
            />
          </label>
          <label>
            Type
            <input
              value={form.procedure_type}
              onChange={(event) => setForm({ ...form, procedure_type: event.target.value })}
              required
            />
          </label>
          <label>
            Content
            <textarea value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} required />
          </label>
          <label>
            Metadata JSON
            <textarea value={form.metadata} onChange={(event) => setForm({ ...form, metadata: event.target.value })} />
          </label>
          <button type="submit" disabled={readOnly}>保存 Procedure</button>
        </form>
        <StatusLine loading={loading} error={error} message={message} />
      </Card>
      <Card title="Procedure 列表">
        <div className="toolbar">
          <label>
            Type Filter
            <input value={procedureType} onChange={(event) => setProcedureType(event.target.value)} />
          </label>
          <button type="button" className="secondary" onClick={load}>
            刷新
          </button>
        </div>
        <DataTable rows={rows} preferredColumns={["procedure_key", "procedure_type", "content", "updated_at"]} />
      </Card>
    </div>
  );
}
