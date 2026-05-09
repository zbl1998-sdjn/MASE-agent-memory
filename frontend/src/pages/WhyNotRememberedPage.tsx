import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { MaseResponse, Scope, WhyNotRememberedData } from "../types";

type WhyNotRememberedPageProps = {
  scope: Scope;
};

export function WhyNotRememberedPage({ scope }: WhyNotRememberedPageProps) {
  const [query, setQuery] = useState("");
  const [threadId, setThreadId] = useState("");
  const [report, setReport] = useState<MaseResponse<WhyNotRememberedData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function diagnose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      setReport(await api.whyNotRemembered({ query, thread_id: threadId || undefined }, scope));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Why Not Remembered" subtitle="定位 event log / entity state / scope / recall 哪一步断了">
        <form className="stack-form" onSubmit={diagnose}>
          <label>
            Query
            <input value={query} onChange={(event) => setQuery(event.target.value)} required />
          </label>
          <label>
            Thread ID
            <input value={threadId} onChange={(event) => setThreadId(event.target.value)} />
          </label>
          <button type="submit">诊断未记住原因</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <Card title={`Likely cause: ${report.data.likely_cause}`}>
            <ol className="repair-list">
              {report.data.recommended_actions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </Card>
          <Card title="Pipeline stages">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Status</th>
                    <th>Evidence</th>
                    <th>Hint</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.stages.map((stage, index) => (
                    <tr key={index}>
                      <td>{String(stage.stage ?? "")}</td>
                      <td>{String(stage.status ?? "")}</td>
                      <td>{String(stage.evidence_count ?? 0)}</td>
                      <td>{String(stage.hint ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Diagnostic payload">
            <JsonBlock value={report} filename="mase-why-not-remembered.json" />
          </Card>
        </>
      )}
    </div>
  );
}
