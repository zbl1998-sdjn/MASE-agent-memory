import { useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { LifecycleData, MaseResponse, Scope } from "../types";

type LifecyclePageProps = {
  scope: Scope;
};

export function LifecyclePage({ scope }: LifecyclePageProps) {
  const [category, setCategory] = useState("");
  const [report, setReport] = useState<MaseResponse<LifecycleData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setReport(await api.lifecycle(scope, category || undefined, 200));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Memory Lifecycle & Contracts" subtitle="只读检查 fact 生命周期、TTL、importance 和 category contract">
        <div className="button-row">
          <input value={category} placeholder="category filter" onChange={(event) => setCategory(event.target.value)} />
          <button type="button" onClick={() => void load()}>
            加载生命周期报告
          </button>
        </div>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="summary-grid">
            <div className="metric-card">
              <span>facts</span>
              <strong>{String(report.data.summary.fact_count ?? 0)}</strong>
            </div>
            <div className="metric-card">
              <span>contract violations</span>
              <strong>{String(report.data.summary.contract_violation_count ?? 0)}</strong>
            </div>
            {Object.entries(report.data.summary.by_state ?? {}).map(([state, count]) => (
              <div className="metric-card" key={state}>
                <span>{state}</span>
                <strong>{String(count)}</strong>
              </div>
            ))}
          </div>
          <Card title="Lifecycle rows">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th>Key</th>
                    <th>State</th>
                    <th>Violations</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.facts.map((item, index) => (
                    <tr key={`${String(item.category)}-${String(item.entity_key)}-${index}`}>
                      <td>{String(item.category ?? "")}</td>
                      <td>{String(item.entity_key ?? "")}</td>
                      <td>{String((item.lifecycle as Record<string, unknown> | undefined)?.state ?? "")}</td>
                      <td>{String((item.contract_violations as unknown[] | undefined)?.length ?? 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Contract payload">
            <JsonBlock value={report} filename="mase-lifecycle-report.json" />
          </Card>
        </>
      )}
    </div>
  );
}
