import { useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { MaseResponse, QualityData, Scope } from "../types";

type QualityPageProps = {
  scope: Scope;
};

export function QualityPage({ scope }: QualityPageProps) {
  const [query, setQuery] = useState("");
  const [report, setReport] = useState<MaseResponse<QualityData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setReport(await api.quality(scope, query || undefined, 100));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Memory Quality Score" subtitle="解释性评分：contract / provenance / freshness / privacy / support / cost">
        <div className="button-row">
          <input value={query} placeholder="optional recall query" onChange={(event) => setQuery(event.target.value)} />
          <button type="button" onClick={() => void load()}>
            计算质量分
          </button>
        </div>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="summary-grid">
            <div className="metric-card">
              <span>average</span>
              <strong>{String(report.data.summary.average_score ?? 0)}</strong>
            </div>
            <div className="metric-card">
              <span>grade</span>
              <strong>{String(report.data.summary.grade ?? "unknown")}</strong>
            </div>
            <div className="metric-card">
              <span>risks</span>
              <strong>{String(report.data.summary.risk_count ?? 0)}</strong>
            </div>
          </div>
          <Card title="Lowest scoring items">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Target</th>
                    <th>Score</th>
                    <th>Grade</th>
                    <th>Risks</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.items.slice(0, 25).map((item, index) => (
                    <tr key={`${String(item.target_id)}-${index}`}>
                      <td>{String(item.target_type ?? "")}</td>
                      <td>{String(item.target_id ?? "")}</td>
                      <td>{String(item.score ?? "")}</td>
                      <td>{String(item.grade ?? "")}</td>
                      <td>{Array.isArray(item.risk_flags) ? item.risk_flags.join(", ") : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Quality payload">
            <JsonBlock value={report} filename="mase-quality-report.json" />
          </Card>
        </>
      )}
    </div>
  );
}
