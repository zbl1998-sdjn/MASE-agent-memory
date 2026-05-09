import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { ChatMessage, JsonRecord, MaseResponse, TraceDetailData, TraceFilters, TraceListData, TraceSummary } from "../types";
import { sanitizeForDisplay } from "../utils";

type ChatPageProps = {
  readOnly: boolean;
};

type TraceFilterForm = {
  routeAction: string;
  component: string;
  hasCloudCall: "all" | "true" | "false";
  hasRisk: "all" | "true" | "false";
  limit: string;
};

type CompareRow = {
  label: string;
  left: string;
  right: string;
  delta: string;
};

const DEFAULT_TRACE_LIMIT = 25;
function parseBooleanFilter(value: TraceFilterForm["hasCloudCall"]): boolean | undefined {
  if (value === "all") {
    return undefined;
  }
  return value === "true";
}

function parseLimit(value: string): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return DEFAULT_TRACE_LIMIT;
  }
  return Math.min(parsed, 100);
}

function traceId(summary: TraceSummary): string {
  return summary.trace_id ?? "";
}

function formatUsd(value: number | undefined): string {
  return `$${(value ?? 0).toFixed(4)}`;
}

function formatList(value: string[] | undefined): string {
  return value?.length ? value.join(", ") : "—";
}

function formatBool(value: boolean | undefined): string {
  return value ? "yes" : "no";
}

function fileSafeTraceId(id: string): string {
  return id.replace(/[^a-z0-9._-]/gi, "_") || "trace";
}

function numericDelta(left: number | undefined, right: number | undefined, decimals = 0): string {
  const delta = (right ?? 0) - (left ?? 0);
  const prefix = delta > 0 ? "+" : "";
  return `${prefix}${delta.toFixed(decimals)}`;
}

function compareSummaries(left: TraceSummary, right: TraceSummary): CompareRow[] {
  const routeChanged = left.route_action === right.route_action ? "same" : "changed";
  const answerChanged = left.answer_preview === right.answer_preview ? "same" : "changed";
  const componentsChanged = formatList(left.components) === formatList(right.components) ? "same" : "changed";
  const risksChanged = formatList(left.risk_flags) === formatList(right.risk_flags) ? "same" : "changed";
  return [
    { label: "route_action", left: left.route_action ?? "—", right: right.route_action ?? "—", delta: routeChanged },
    { label: "answer_preview", left: left.answer_preview ?? "—", right: right.answer_preview ?? "—", delta: answerChanged },
    {
      label: "step_count",
      left: String(left.step_count ?? 0),
      right: String(right.step_count ?? 0),
      delta: numericDelta(left.step_count, right.step_count)
    },
    { label: "components", left: formatList(left.components), right: formatList(right.components), delta: componentsChanged },
    {
      label: "total_tokens",
      left: String(left.total_tokens ?? 0),
      right: String(right.total_tokens ?? 0),
      delta: numericDelta(left.total_tokens, right.total_tokens)
    },
    {
      label: "estimated_cost_usd",
      left: formatUsd(left.estimated_cost_usd),
      right: formatUsd(right.estimated_cost_usd),
      delta: numericDelta(left.estimated_cost_usd, right.estimated_cost_usd, 4)
    },
    { label: "risk_flags", left: formatList(left.risk_flags), right: formatList(right.risk_flags), delta: risksChanged }
  ];
}

export function ChatPage({ readOnly }: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "你好，我是 MASE 控制台。可以直接提问，或运行带审计链的 Trace。" }
  ]);
  const [input, setInput] = useState("");
  const [trace, setTrace] = useState<JsonRecord>();
  const [writeTraceToMemory, setWriteTraceToMemory] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<TraceFilterForm>({
    routeAction: "",
    component: "",
    hasCloudCall: "all",
    hasRisk: "all",
    limit: String(DEFAULT_TRACE_LIMIT)
  });
  const [history, setHistory] = useState<MaseResponse<TraceListData>>();
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [selectedTraceId, setSelectedTraceId] = useState("");
  const [detail, setDetail] = useState<MaseResponse<TraceDetailData>>();
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [compareIds, setCompareIds] = useState<string[]>([]);

  const summaries = useMemo(() => history?.data.summaries ?? [], [history]);
  const compareSummariesSelected = useMemo(
    () =>
      compareIds
        .map((id) => summaries.find((summary) => traceId(summary) === id))
        .filter((summary): summary is TraceSummary => Boolean(summary)),
    [compareIds, summaries]
  );
  const compareRows = useMemo(() => {
    if (compareSummariesSelected.length !== 2) {
      return [];
    }
    return compareSummaries(compareSummariesSelected[0], compareSummariesSelected[1]);
  }, [compareSummariesSelected]);
  const safeDetail = useMemo(
    () => sanitizeForDisplay(detail?.data.trace ?? { hint: "点击 trace_id 查看历史详情" }),
    [detail]
  );

  useEffect(() => {
    void loadTraceHistory();
  }, []);

  function buildTraceFilters(): TraceFilters {
    return {
      route_action: filters.routeAction.trim(),
      component: filters.component.trim(),
      has_cloud_call: parseBooleanFilter(filters.hasCloudCall),
      has_risk: parseBooleanFilter(filters.hasRisk),
      limit: parseLimit(filters.limit)
    };
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!input.trim()) {
      return;
    }
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: input.trim() }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError("");
    try {
      const response = await api.chat(nextMessages);
      setMessages([...nextMessages, response.choices[0]?.message ?? { role: "assistant", content: "" }]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function runTrace() {
    const latestUser = [...messages].reverse().find((message) => message.role === "user")?.content ?? input;
    if (!latestUser.trim()) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await api.runTrace(latestUser, readOnly ? false : writeTraceToMemory);
      setTrace(response.data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function loadTraceHistory(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const response = await api.traces(buildTraceFilters());
      const ids = new Set(response.data.summaries.map(traceId).filter(Boolean));
      setHistory(response);
      setCompareIds((current) => current.filter((id) => ids.has(id)).slice(0, 2));
    } catch (err) {
      setHistoryError((err as Error).message);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadTraceDetail(id: string) {
    if (!id) {
      return;
    }
    setSelectedTraceId(id);
    setDetailLoading(true);
    setDetailError("");
    try {
      setDetail(await api.traceDetail(id));
    } catch (err) {
      setDetailError((err as Error).message);
    } finally {
      setDetailLoading(false);
    }
  }

  function toggleCompare(id: string) {
    if (!id) {
      return;
    }
    setCompareIds((current) => {
      if (current.includes(id)) {
        return current.filter((item) => item !== id);
      }
      return current.length >= 2 ? [current[1], id] : [...current, id];
    });
  }

  return (
    <div className="stack">
      <div className="grid two">
        <Card title="Chat Completions" subtitle="使用 /v1/chat/completions 调用 MASE">
          <div className="chat-log">
            {messages.map((message, index) => (
              <div className={`bubble ${message.role}`} key={`${message.role}-${index}`}>
                <strong>{message.role}</strong>
                <p>{message.content}</p>
              </div>
            ))}
          </div>
          <form className="row-form" onSubmit={send}>
            <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入问题..." />
            <button type="submit">发送</button>
            <button type="button" className="secondary" onClick={runTrace}>
              运行 Trace
            </button>
            <label className="check">
              <input
                type="checkbox"
                checked={writeTraceToMemory}
                disabled={readOnly}
                onChange={(event) => setWriteTraceToMemory(event.target.checked)}
              />
              写入 Memory（持久记录）
            </label>
            <p className={writeTraceToMemory ? "trace-mode-note warning" : "trace-mode-note"}>
              {readOnly
                ? "只读模式：Trace 固定为 Dry-run，不会写入 Memory。"
                : writeTraceToMemory
                ? "写入开启：会创建持久 Memory 记录，影响后续召回/记忆。"
                : "默认 Dry-run：Trace 不写入 Memory，不创建持久记录。"}
            </p>
          </form>
          <StatusLine loading={loading} error={error} />
        </Card>
        <Card title="Orchestration Trace" subtitle="路由、Planner、Fact Sheet、证据与回答">
          <JsonBlock value={trace ?? { hint: "点击“运行 Trace”后显示完整审计链" }} filename="mase-trace.json" />
        </Card>
      </div>

      <Card title="Trace History" subtitle="只读查询历史 trace，按路由、组件、云调用和风险筛选。">
        <form className="trace-filter-grid" onSubmit={loadTraceHistory}>
          <label>
            route_action
            <input
              value={filters.routeAction}
              placeholder="search_memory"
              onChange={(event) => setFilters((current) => ({ ...current, routeAction: event.target.value }))}
            />
          </label>
          <label>
            component
            <input
              value={filters.component}
              placeholder="retrieval"
              onChange={(event) => setFilters((current) => ({ ...current, component: event.target.value }))}
            />
          </label>
          <label>
            has_cloud_call
            <select
              value={filters.hasCloudCall}
              onChange={(event) =>
                setFilters((current) => ({ ...current, hasCloudCall: event.target.value as TraceFilterForm["hasCloudCall"] }))
              }
            >
              <option value="all">全部</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </label>
          <label>
            has_risk
            <select
              value={filters.hasRisk}
              onChange={(event) =>
                setFilters((current) => ({ ...current, hasRisk: event.target.value as TraceFilterForm["hasRisk"] }))
              }
            >
              <option value="all">全部</option>
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          </label>
          <label>
            limit
            <input
              type="number"
              min="1"
              max="100"
              value={filters.limit}
              onChange={(event) => setFilters((current) => ({ ...current, limit: event.target.value }))}
            />
          </label>
          <button type="submit">刷新历史</button>
        </form>
        <StatusLine loading={historyLoading} error={historyError} />
        <p className="trace-mode-note">
          matched {String(history?.metadata?.matched_count ?? 0)} / returned {String(history?.metadata?.returned_count ?? 0)}
        </p>
        <div className="table-wrap trace-history-table">
          <table>
            <thead>
              <tr>
                <th>trace_id</th>
                <th>route_action</th>
                <th>created_at</th>
                <th>step_count</th>
                <th>total_tokens</th>
                <th>estimated_cost_usd</th>
                <th>has_cloud_call</th>
                <th>risk_flags</th>
                <th>compare</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map((summary, index) => {
                const id = traceId(summary);
                const compareSelected = compareIds.includes(id);
                return (
                  <tr className={selectedTraceId === id ? "selected" : ""} key={`${id}-${index}`}>
                    <td>
                      <button type="button" className="link-button" disabled={!id} onClick={() => loadTraceDetail(id)}>
                        {id || "—"}
                      </button>
                    </td>
                    <td>{summary.route_action ?? "—"}</td>
                    <td>{summary.created_at ?? "—"}</td>
                    <td>{summary.step_count ?? 0}</td>
                    <td>{summary.total_tokens ?? 0}</td>
                    <td>{formatUsd(summary.estimated_cost_usd)}</td>
                    <td>{formatBool(summary.has_cloud_call)}</td>
                    <td>{formatList(summary.risk_flags)}</td>
                    <td>
                      <button
                        type="button"
                        className={compareSelected ? "compare-button active" : "compare-button ghost"}
                        disabled={!id}
                        onClick={() => toggleCompare(id)}
                      >
                        {compareSelected ? "已选" : "选择"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!summaries.length && <div className="empty">暂无历史 trace</div>}
        </div>
      </Card>

      <div className="grid two">
        <Card title="Trace Detail" subtitle={selectedTraceId ? `trace_id: ${selectedTraceId}` : "点击历史列表中的 trace_id"}>
          <StatusLine loading={detailLoading} error={detailError} />
          <JsonBlock value={safeDetail} filename={`mase-trace-${fileSafeTraceId(selectedTraceId)}.json`} />
        </Card>
        <Card title="Lightweight Compare" subtitle="选择两条 trace，对比路由、回答预览、步骤、组件、token、成本和风险。">
          {compareRows.length === 0 ? (
            <div className="empty">请选择两条 trace 进行对比；选择第三条会自动替换最早选择。</div>
          ) : (
            <div className="table-wrap compare-table">
              <table>
                <thead>
                  <tr>
                    <th>field</th>
                    <th>{compareIds[0]}</th>
                    <th>{compareIds[1]}</th>
                    <th>delta</th>
                  </tr>
                </thead>
                <tbody>
                  {compareRows.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td>{row.left}</td>
                      <td>{row.right}</td>
                      <td>
                        <span className={row.delta === "same" ? "diff-badge same" : "diff-badge"}>{row.delta}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
