import { useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { DriftData, MaseResponse, Scope } from "../types";

type DriftPageProps = {
  scope: Scope;
};

export function DriftPage({ scope }: DriftPageProps) {
  const [category, setCategory] = useState("");
  const [report, setReport] = useState<MaseResponse<DriftData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadReport(nextCategory = category) {
    setLoading(true);
    setError("");
    try {
      setReport(await api.drift(scope, nextCategory || undefined));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReport("");
  }, [scope]);

  return (
    <div className="stack">
      <Card title="Memory Drift Detector" subtitle="检测事实冲突、重复值和生命周期压力">
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            void loadReport();
          }}
        >
          <input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Category filter" />
          <button type="submit">刷新漂移报告</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="grid cards-3">
            <Card title="Status">{String(report.data.summary.status ?? "unknown")}</Card>
            <Card title="Issues">{report.data.summary.issue_count ?? 0}</Card>
            <Card title="High">{report.data.summary.high_count ?? 0}</Card>
          </div>
          <Card title="Drift issues">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Severity</th>
                    <th>Facts</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.issues.map((issue, index) => (
                    <tr key={index}>
                      <td>{String(issue.kind ?? "")}</td>
                      <td>{String(issue.severity ?? "")}</td>
                      <td>{String(issue.fact_count ?? 0)}</td>
                      <td>{String(issue.message ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Drift payload">
            <JsonBlock value={report} filename="mase-drift.json" />
          </Card>
        </>
      )}
    </div>
  );
}
