import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { AnswerSupportData, MaseResponse, Scope } from "../types";

type AnswerSupportPageProps = {
  scope: Scope;
};

export function AnswerSupportPage({ scope }: AnswerSupportPageProps) {
  const [answer, setAnswer] = useState("");
  const [query, setQuery] = useState("");
  const [report, setReport] = useState<MaseResponse<AnswerSupportData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function analyze(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      setReport(await api.answerSupport({ answer, query }, scope));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Answer Support View" subtitle="把回答句子映射到记忆证据，标记 supported / weak / unsupported / stale">
        <form className="stack-form" onSubmit={analyze}>
          <label>
            Query
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <label>
            Answer
            <textarea value={answer} onChange={(event) => setAnswer(event.target.value)} required />
          </label>
          <button type="submit">分析支撑证据</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="summary-grid">
            {["supported_count", "weak_count", "unsupported_count", "stale_count"].map((key) => (
              <div className="metric-card" key={key}>
                <span>{key}</span>
                <strong>{String(report.data.summary[key] ?? 0)}</strong>
              </div>
            ))}
          </div>
          <Card title="Answer spans">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Span</th>
                    <th>Status</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.spans.map((span, index) => (
                    <tr key={index}>
                      <td>{String(span.text ?? "")}</td>
                      <td>{String(span.support_status ?? "")}</td>
                      <td>{String(span.support_score ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Support payload">
            <JsonBlock value={report} filename="mase-answer-support.json" />
          </Card>
        </>
      )}
    </div>
  );
}
