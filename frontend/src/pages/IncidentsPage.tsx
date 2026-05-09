import { useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { IncidentsData, InspectorsData, MaseResponse, Scope } from "../types";

type IncidentsPageProps = {
  scope: Scope;
};

export function IncidentsPage({ scope }: IncidentsPageProps) {
  const [incidents, setIncidents] = useState<MaseResponse<IncidentsData>>();
  const [inspectors, setInspectors] = useState<MaseResponse<InspectorsData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextInspectors, nextIncidents] = await Promise.all([
        api.inspectors(),
        api.incidents({ cases: [{ case_id: "incident-smoke", query: "project owner" }] }, scope)
      ]);
      setInspectors(nextInspectors);
      setIncidents(nextIncidents);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [scope]);

  return (
    <div className="stack">
      <Card title="Memory Incidents & Inspectors" subtitle="把高风险信号提升为 incident，并展示插件化 inspector">
        <button type="button" onClick={() => void load()}>
          刷新事件
        </button>
        <StatusLine loading={loading} error={error} />
      </Card>

      {incidents && (
        <>
          <div className="grid cards-3">
            <Card title="Incident status">{String(incidents.data.summary.status ?? "unknown")}</Card>
            <Card title="Incidents">{incidents.data.summary.incident_count ?? 0}</Card>
            <Card title="Inspectors">{inspectors?.data.summary.enabled_count ?? 0}</Card>
          </div>
          <Card title="Open incidents">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Kind</th>
                    <th>Severity</th>
                    <th>Source</th>
                    <th>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {incidents.data.incidents.map((incident, index) => (
                    <tr key={index}>
                      <td>{String(incident.incident_id ?? "")}</td>
                      <td>{String(incident.kind ?? "")}</td>
                      <td>{String(incident.severity ?? "")}</td>
                      <td>{String(incident.source ?? "")}</td>
                      <td>{String(incident.title ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Inspector registry">
            <JsonBlock value={inspectors} filename="mase-inspectors.json" />
          </Card>
          <Card title="Incident payload">
            <JsonBlock value={incidents} filename="mase-incidents.json" />
          </Card>
        </>
      )}
    </div>
  );
}
