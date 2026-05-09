import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { RepairExecutionPanel } from "../components/RepairExecutionPanel";
import { StatusLine } from "../components/StatusLine";
import type { JsonValue, MaseResponse, RepairCase, RepairCasesData, RepairPlanData, Scope } from "../types";

type RepairPageProps = {
  scope: Scope;
};

const NEXT_STATUS: Record<string, string[]> = {
  open: ["diagnosed", "failed", "closed"],
  diagnosed: ["pending_approval", "failed", "closed"],
  pending_approval: ["approved", "failed", "closed"],
  approved: [],
  executed: ["validated", "failed"],
  failed: ["open", "closed"],
  validated: ["closed"],
  closed: []
};

function parseEvidence(value: string): { [key: string]: JsonValue } {
  const parsed = value.trim() ? (JSON.parse(value) as unknown) : {};
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Evidence JSON must be an object");
  }
  return parsed as { [key: string]: JsonValue };
}

function statusActions(caseItem: RepairCase): string[] {
  return NEXT_STATUS[caseItem.status] ?? [];
}

export function RepairPage({ scope }: RepairPageProps) {
  const [issueType, setIssueType] = useState("incorrect_memory");
  const [symptom, setSymptom] = useState("");
  const [evidence, setEvidence] = useState("{}");
  const [plan, setPlan] = useState<MaseResponse<RepairPlanData>>();
  const [cases, setCases] = useState<MaseResponse<RepairCasesData>>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadCases() {
    try {
      const response = await api.repairCases({ limit: 50 });
      setCases(response);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    void loadCases();
  }, [scope.tenant_id, scope.workspace_id, scope.visibility]);

  async function buildPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const parsedEvidence = parseEvidence(evidence);
      const response = await api.repairPlan({ issue_type: issueType, symptom, evidence: parsedEvidence }, scope);
      setPlan(response);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function createCase() {
    setLoading(true);
    setError("");
    try {
      const parsedEvidence = parseEvidence(evidence);
      await api.createRepairCase({ issue_type: issueType, symptom, evidence: parsedEvidence }, scope);
      await loadCases();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function transitionCase(caseId: string, status: string) {
    setLoading(true);
    setError("");
    try {
      await api.transitionRepairCase(caseId, { status });
      await loadCases();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function proposeDiff(caseId: string) {
    setLoading(true);
    setError("");
    try {
      await api.proposeRepairDiff(caseId);
      await loadCases();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function runSandbox(caseId: string) {
    setLoading(true);
    setError("");
    try {
      await api.runRepairSandbox(caseId);
      await loadCases();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Agent Repair Center" subtitle="生成可审计的记忆修复工单，不在前端直接改库">
        <form className="stack-form" onSubmit={buildPlan}>
          <label>
            Issue type
            <select value={issueType} onChange={(event) => setIssueType(event.target.value)}>
              <option value="incorrect_memory">incorrect_memory</option>
              <option value="recall_failure">recall_failure</option>
              <option value="cost_spike">cost_spike</option>
            </select>
          </label>
          <label>
            Symptom
            <textarea
              value={symptom}
              onChange={(event) => setSymptom(event.target.value)}
              placeholder="例如：回答用了旧预算，Trace 显示召回到了 superseded event。"
              required
            />
          </label>
          <label>
            Evidence JSON
            <textarea value={evidence} onChange={(event) => setEvidence(event.target.value)} />
          </label>
          <button type="submit">生成 Repair Plan</button>
          <button type="button" onClick={createCase} disabled={!symptom.trim()}>
            创建 Repair Case
          </button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      <Card title="Repair Case Lifecycle" subtitle="只记录诊断、审批与审计状态；真正执行会在 Sandbox/Execution 模块中接入">
        <div className="stack">
          <button type="button" onClick={loadCases}>
            刷新工单
          </button>
          <div className="summary-grid">
            {Object.entries(cases?.data.summary.by_status ?? {})
              .filter(([, count]) => Number(count) > 0)
              .map(([status, count]) => (
                <div className="metric-card" key={status}>
                  <span>{status}</span>
                  <strong>{String(count)}</strong>
                </div>
              ))}
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Status</th>
                  <th>Issue</th>
                  <th>Symptom</th>
                  <th>Updated</th>
                  <th>Next</th>
                </tr>
              </thead>
              <tbody>
                {(cases?.data.cases ?? []).map((caseItem) => (
                  <tr key={caseItem.case_id}>
                    <td>{caseItem.case_id}</td>
                    <td>{caseItem.status}</td>
                    <td>{caseItem.issue_type}</td>
                    <td>{caseItem.symptom}</td>
                    <td>{caseItem.updated_at}</td>
                    <td>
                      <div className="button-row">
                        {statusActions(caseItem).map((status) => (
                          <button key={status} type="button" onClick={() => void transitionCase(caseItem.case_id, status)}>
                            {status}
                          </button>
                        ))}
                        {["open", "diagnosed"].includes(caseItem.status) && (
                          <button type="button" onClick={() => void proposeDiff(caseItem.case_id)}>
                            propose diff
                          </button>
                        )}
                        {caseItem.diff_proposal && ["diagnosed", "pending_approval"].includes(caseItem.status) && (
                          <button type="button" onClick={() => void runSandbox(caseItem.case_id)}>
                            sandbox
                          </button>
                        )}
                        {caseItem.status === "approved" && <span className="muted">waiting for execution module</span>}
                      </div>
                      {caseItem.diff_proposal && (
                        <details>
                          <summary>diff proposal</summary>
                          <JsonBlock value={caseItem.diff_proposal} filename={`${caseItem.case_id}-diff.json`} />
                        </details>
                      )}
                      {caseItem.sandbox_report && (
                        <details>
                          <summary>sandbox report</summary>
                          <JsonBlock value={caseItem.sandbox_report} filename={`${caseItem.case_id}-sandbox.json`} />
                        </details>
                      )}
                      <RepairExecutionPanel caseItem={caseItem} onExecuted={loadCases} onError={setError} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      {plan && (
        <div className="grid two">
          <Card title="Risk checklist" subtitle="交给 Agent 前先逐条审查">
            <ol className="repair-list">
              {plan.data.risk_checklist.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </Card>
          <Card title="Recommended steps" subtitle="执行后用 Trace / Recall 复验">
            <ol className="repair-list">
              {plan.data.recommended_steps.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </Card>
          <Card title="Agent prompt" subtitle="复制给记事 Agent，让它提出 diff、风险和验证查询">
            <pre className="prompt-box">{plan.data.agent_prompt}</pre>
          </Card>
          <Card title="Repair payload">
            <JsonBlock value={plan} filename="mase-repair-plan.json" />
          </Card>
        </div>
      )}
    </div>
  );
}
