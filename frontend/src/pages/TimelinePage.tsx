import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { StatusLine } from "../components/StatusLine";
import type { JsonRecord, Scope } from "../types";

type TimelinePageProps = {
  scope: Scope;
  readOnly: boolean;
};

export function TimelinePage({ scope, readOnly }: TimelinePageProps) {
  const [threadId, setThreadId] = useState("default");
  const [rows, setRows] = useState<JsonRecord[]>([]);
  const [snapshots, setSnapshots] = useState<JsonRecord[]>([]);
  const [writePaths, setWritePaths] = useState<JsonRecord[]>([]);
  const [writeSummary, setWriteSummary] = useState<Record<string, number>>({});
  const [eventForm, setEventForm] = useState({ role: "user", content: "" });
  const [correction, setCorrection] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [timeline, snapshotRows, inspector] = await Promise.all([
        api.timeline(scope, threadId || undefined, 100),
        api.snapshots(scope, threadId || undefined),
        api.writeInspector(scope, threadId || undefined, 100)
      ]);
      setRows(timeline.data);
      setSnapshots(snapshotRows.data);
      setWritePaths(inspector.data.write_paths);
      setWriteSummary(inspector.data.summary);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [scope, threadId]);

  async function writeEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly) {
      setMessage("只读模式：流水账写入已禁用");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      await api.writeEvent({ thread_id: threadId, role: eventForm.role, content: eventForm.content }, scope);
      setEventForm({ ...eventForm, content: "" });
      setMessage("流水账已写入");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function correct() {
    if (readOnly) {
      setMessage("只读模式：纠错写入已禁用");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      await api.correctMemory({ thread_id: threadId, utterance: correction }, scope);
      setCorrection("");
      setMessage("纠错已记录并尝试 supersede 旧流水");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function consolidate() {
    if (readOnly) {
      setMessage("只读模式：快照生成已禁用");
      return;
    }
    setLoading(true);
    try {
      await api.consolidate(threadId, 50, scope);
      setMessage("会话快照已生成");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="时间线控制" subtitle="Event Log 写入、纠错和快照生成">
        <div className="toolbar">
          <label>
            Thread
            <input value={threadId} onChange={(event) => setThreadId(event.target.value)} />
          </label>
          <button type="button" className="secondary" onClick={load}>
            刷新
          </button>
          <button type="button" disabled={readOnly} onClick={consolidate}>
            生成快照
          </button>
        </div>
        <StatusLine loading={loading} error={error} message={message} />
      </Card>
      <div className="grid two">
        <Card title="写入流水账">
          <form className="stack-form" onSubmit={writeEvent}>
            <select value={eventForm.role} onChange={(event) => setEventForm({ ...eventForm, role: event.target.value })}>
              <option value="user">user</option>
              <option value="assistant">assistant</option>
              <option value="system">system</option>
            </select>
            <textarea
              value={eventForm.content}
              onChange={(event) => setEventForm({ ...eventForm, content: event.target.value })}
              required
            />
            <button type="submit" disabled={readOnly}>写入 Event</button>
          </form>
        </Card>
        <Card title="纠错 / Supersede">
          <textarea value={correction} onChange={(event) => setCorrection(event.target.value)} placeholder="我之前说错了..." />
          <button type="button" onClick={correct} disabled={readOnly || !correction.trim()}>
            记录纠错
          </button>
        </Card>
      </div>
      <Card title="Event Log">
        <DataTable rows={rows} preferredColumns={["id", "thread_id", "role", "content", "event_timestamp", "superseded_at"]} />
      </Card>
      <Card title="Memory Write Inspector" subtitle="事件写入 → 事实链接 → 纠错/Supersede 风险">
        <div className="metric-grid">
          {Object.entries(writeSummary).map(([key, value]) => (
            <div className="metric" key={key}>
              <span>{key}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <DataTable
          rows={writePaths}
          preferredColumns={[
            "event_id",
            "thread_id",
            "role",
            "status",
            "linked_current_fact_count",
            "linked_history_count",
            "risk_hints",
            "content"
          ]}
        />
      </Card>
      <Card title="Episodic Snapshots">
        <DataTable rows={snapshots} preferredColumns={["id", "thread_id", "summary", "source_count", "updated_at"]} />
      </Card>
    </div>
  );
}
