import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatCard } from "../components/StatCard";
import { StatusLine } from "../components/StatusLine";
import type { AuditEventsData, AuditFilters, JsonRecord, MaseResponse } from "../types";

const actionOptions = [
  "",
  "auth.permission_denied",
  "memory.event.create",
  "memory.correction.create",
  "memory.fact.upsert",
  "memory.fact.forget",
  "memory.session_state.upsert",
  "memory.session_state.forget",
  "memory.procedure.register",
  "memory.snapshot.consolidate"
];

function countBy(rows: JsonRecord[], key: string): JsonRecord[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const value = String(row[key] ?? "unknown");
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return [...counts.entries()].map(([name, count]) => ({ name, count }));
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function AuditLogPage() {
  const [payload, setPayload] = useState<MaseResponse<AuditEventsData>>();
  const [filters, setFilters] = useState<AuditFilters>({ limit: 100 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function loadAudit(nextFilters = filters) {
    setLoading(true);
    setError("");
    api.auditEvents(nextFilters)
      .then(setPayload)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadAudit(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const events = payload?.data.events ?? [];
  const deniedCount = events.filter((event) => event.outcome === "denied").length;
  const actionCounts = useMemo(() => countBy(events, "action"), [events]);
  const actorCounts = useMemo(() => countBy(events, "actor_id"), [events]);

  return (
    <div className="stack">
      <section className="hero-panel audit-hero">
        <div>
          <p className="eyebrow">Audit Log</p>
          <h1>谁在什么时候改了什么、被拒绝了什么</h1>
          <p>Append-only 审计视图覆盖 memory mutation 与权限拒绝，Repair 执行前先把追责链打牢。</p>
          <div className="tag-list">
            <span className="tag">append-only JSONL</span>
            <span className="tag">secrets redacted</span>
            <span className="tag">audit permission gated</span>
          </div>
        </div>
        <div className="hero-visual">
          <div className="metric-grid">
            <div className="metric">
              <span>events loaded</span>
              <strong>{events.length}</strong>
            </div>
            <div className="metric">
              <span>denied events</span>
              <strong>{deniedCount}</strong>
            </div>
            <div className="metric">
              <span>audit path</span>
              <strong>{String(payload?.metadata?.path ?? "not loaded")}</strong>
            </div>
          </div>
        </div>
      </section>

      <StatusLine loading={loading} error={error} />

      <div className="toolbar">
        <label>
          Actor
          <input
            value={filters.actor_id ?? ""}
            placeholder="ops-user"
            onChange={(event) => setFilters((current) => ({ ...current, actor_id: event.target.value }))}
          />
        </label>
        <label>
          Action
          <select
            value={filters.action ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, action: event.target.value }))}
          >
            {actionOptions.map((action) => (
              <option key={action || "all"} value={action}>
                {action || "all actions"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Resource type
          <input
            value={filters.resource_type ?? ""}
            placeholder="memory_fact"
            onChange={(event) => setFilters((current) => ({ ...current, resource_type: event.target.value }))}
          />
        </label>
        <label>
          Limit
          <input
            type="number"
            min={1}
            max={500}
            value={filters.limit ?? 100}
            onChange={(event) => setFilters((current) => ({ ...current, limit: Number(event.target.value) }))}
          />
        </label>
        <button onClick={() => loadAudit(filters)}>Apply</button>
      </div>

      <div className="stat-grid">
        <StatCard label="audit events" value={events.length} hint="current filtered window" tone="cyan" />
        <StatCard label="denied" value={deniedCount} hint="permission denials" tone="amber" />
        <StatCard label="bad lines skipped" value={asNumber(payload?.metadata?.skipped_count)} hint="corrupt JSONL rows" tone="violet" />
        <StatCard label="resource types" value={countBy(events, "resource_type").length} hint="distinct audited resources" tone="green" />
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Actions</h2>
            <p>按动作聚合，快速定位写入、删除、权限拒绝是否异常集中。</p>
          </header>
          <DataTable rows={actionCounts} preferredColumns={["name", "count"]} />
        </section>
        <section className="glass-card">
          <header>
            <h2>Actors</h2>
            <p>按 actor 聚合，支撑多用户追责和 Repair 审批链。</p>
          </header>
          <DataTable rows={actorCounts} preferredColumns={["name", "count"]} />
        </section>
      </div>

      <section className="glass-card">
        <header>
          <h2>Audit events</h2>
          <p>最新事件在前；metadata 已在后端脱敏，避免泄露 token、headers、password 等敏感字段。</p>
        </header>
        <DataTable
          rows={events}
          preferredColumns={[
            "created_at",
            "actor_id",
            "role",
            "action",
            "resource_type",
            "resource_id",
            "outcome",
            "scope",
            "metadata"
          ]}
        />
      </section>

      <details className="debug-panel">
        <summary>Raw audit payload</summary>
        <JsonBlock value={payload ?? {}} filename="mase-audit-log.json" />
      </details>
    </div>
  );
}
