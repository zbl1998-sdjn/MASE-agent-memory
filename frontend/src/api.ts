import type {
  AuditEventsData,
  AuditFilters,
  AnswerSupportData,
  BootstrapData,
  ChatMessage,
  CostPricingData,
  CostRoutingData,
  CostSummaryData,
  DashboardData,
  DriftData,
  GoldenTestsData,
  IncidentsData,
  InspectorsData,
  JsonRecord,
  LifecycleData,
  MaseResponse,
  MediaUploadData,
  ObservabilityData,
  PrivacyPreviewData,
  PrivacyScanData,
  QualityData,
  RefusalQualityData,
  RepairCase,
  RepairCaseDiffData,
  RepairCaseExecutionData,
  RepairCaseSandboxData,
  RepairCasesData,
  RepairPlanData,
  Scope,
  SloDashboardData,
  SyntheticReplayData,
  TraceDetailData,
  TraceFilters,
  TraceListData,
  WhyNotRememberedData,
  WriteInspectorData
} from "./types";
import { compactScope } from "./utils";

// 前端唯一 HTTP 边界。页面组件只调用这里暴露的 api 方法，不直接拼 fetch，
// 这样鉴权、scope 注入、错误格式和 query 参数规则可以集中维护。
const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const API_KEY_STORAGE_KEY = "mase.internalApiKey";
let runtimeInternalApiKey = "";

function readLocalApiKey(): string {
  // runtimeInternalApiKey 支持本次会话立即生效；localStorage 用于刷新后恢复。
  if (runtimeInternalApiKey) {
    return runtimeInternalApiKey;
  }
  const fallback = import.meta.env.VITE_MASE_INTERNAL_API_KEY ?? "";
  if (typeof localStorage === "undefined") {
    return fallback;
  }
  return localStorage.getItem(API_KEY_STORAGE_KEY) ?? fallback;
}

export function getInternalApiKey(): string {
  return readLocalApiKey();
}

export function saveInternalApiKey(value: string): void {
  // 空值表示清除密钥，不把空 Authorization header 带到后端。
  runtimeInternalApiKey = value.trim();
  if (typeof localStorage === "undefined") {
    return;
  }
  if (runtimeInternalApiKey) {
    localStorage.setItem(API_KEY_STORAGE_KEY, runtimeInternalApiKey);
  } else {
    localStorage.removeItem(API_KEY_STORAGE_KEY);
  }
}

function authHeaders(): Record<string, string> {
  // 后端内部 API 使用 Bearer；无 key 时保持匿名请求，便于只读/本地模式。
  const key = readLocalApiKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

function withQuery(path: string, params: Record<string, string | number | boolean | undefined>): string {
  // 只序列化有意义的值，避免空字符串覆盖后端默认过滤条件。
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  }
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function scopedBody<T extends JsonRecord>(body: T, scope: Scope): T & Scope {
  // scope 是多租户/工作区隔离边界，所有写入和分析类 POST 都在这里统一注入。
  return { ...body, ...compactScope(scope) };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 统一错误抛出格式，页面层只需要展示 Error.message。
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return response.json() as Promise<T>;
}

export async function uploadMedia(file: File, mode?: string): Promise<MediaUploadData> {
  // multipart 边界由浏览器自动生成;绝不能手动设 Content-Type,
  // 因此不走 request<T>(它强制 JSON 头),只复用鉴权头。
  const form = new FormData();
  form.append("file", file);
  if (mode) {
    form.append("mode", mode);
  }
  const response = await fetch(`${API_BASE}/v1/mase/media/upload`, {
    method: "POST",
    headers: { ...authHeaders() },
    body: form
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return response.json() as Promise<MediaUploadData>;
}

export const api = {
  // 产品壳与总览页面。
  health: () => request<MaseResponse<JsonRecord>>("/health"),
  bootstrap: () => request<MaseResponse<BootstrapData>>("/v1/ui/bootstrap"),
  dashboard: (scope: Scope) =>
    request<MaseResponse<DashboardData>>(withQuery("/v1/ui/dashboard", compactScope(scope))),
  observability: (recentLimit = 25) =>
    request<MaseResponse<ObservabilityData>>(withQuery("/v1/ui/observability", { recent_limit: recentLimit })),
  // 成本中心只读取模型调用账本，保持只读。
  costPricing: () => request<MaseResponse<CostPricingData>>("/v1/ui/cost/pricing"),
  costSummary: (recentLimit = 50) =>
    request<MaseResponse<CostSummaryData>>(withQuery("/v1/ui/cost/summary", { recent_limit: recentLimit })),
  costRouting: () => request<MaseResponse<CostRoutingData>>("/v1/ui/cost/routing"),
  // 可靠性与治理工作台接口。
  auditEvents: (filters: AuditFilters = {}) =>
    request<MaseResponse<AuditEventsData>>(withQuery("/v1/ui/audit/events", filters)),
  privacyScan: (scope: Scope, limit = 100) =>
    request<MaseResponse<PrivacyScanData>>(withQuery("/v1/ui/privacy/scan", { ...compactScope(scope), limit })),
  privacyPreview: (payload: JsonRecord) =>
    request<MaseResponse<PrivacyPreviewData>>("/v1/ui/privacy/preview", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  lifecycle: (scope: Scope, category?: string, limit = 200) =>
    request<MaseResponse<LifecycleData>>(withQuery("/v1/ui/lifecycle", { ...compactScope(scope), category, limit })),
  quality: (scope: Scope, query?: string, limit = 100) =>
    request<MaseResponse<QualityData>>(withQuery("/v1/ui/quality", { ...compactScope(scope), query, limit })),
  answerSupport: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<AnswerSupportData>>("/v1/ui/answer-support", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  refusalQuality: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<RefusalQualityData>>("/v1/ui/refusal-quality", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  whyNotRemembered: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<WhyNotRememberedData>>("/v1/ui/why-not-remembered", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  syntheticReplay: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<SyntheticReplayData>>("/v1/ui/synthetic-replay", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  goldenTests: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<GoldenTestsData>>("/v1/ui/golden-tests", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  sloDashboard: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<SloDashboardData>>("/v1/ui/slo-dashboard", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  drift: (scope: Scope, category?: string) =>
    request<MaseResponse<DriftData>>(withQuery("/v1/ui/drift", { ...compactScope(scope), category })),
  inspectors: () => request<MaseResponse<InspectorsData>>("/v1/ui/inspectors"),
  incidents: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<IncidentsData>>("/v1/ui/incidents", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  // Chat 与 trace 分离：chat 走 OpenAI-compatible 补全形状，runTrace 暴露完整
  // MASE 编排证据。
  validate: (scope: Scope) =>
    request<MaseResponse<JsonRecord>>(withQuery("/v1/memory/validate", compactScope(scope))),
  chat: (messages: ChatMessage[]) =>
    request<{ choices: Array<{ message: ChatMessage }> }>("/v1/chat/completions", {
      method: "POST",
      body: JSON.stringify({ model: "mase", messages })
    }),
  runTrace: (query: string, log = false) =>
    request<MaseResponse<JsonRecord>>("/v1/mase/run", {
      method: "POST",
      body: JSON.stringify({ query, log })
    }),
  traces: (filters: TraceFilters = {}) =>
    request<MaseResponse<TraceListData>>(withQuery("/v1/ui/traces", filters)),
  traceDetail: (traceId: string) =>
    request<MaseResponse<TraceDetailData>>(`/v1/ui/traces/${encodeURIComponent(traceId)}`),
  // 记忆 CRUD / recall 接口。查询串用 compactScope，JSON body 用 scopedBody。
  recall: (query: string, topK: number, includeHistory: boolean, scope: Scope) =>
    request<MaseResponse<JsonRecord[]>>("/v1/memory/recall", {
      method: "POST",
      body: JSON.stringify(scopedBody({ query, top_k: topK, include_history: includeHistory }, scope))
    }),
  currentState: (query: string, topK: number, scope: Scope) =>
    request<MaseResponse<JsonRecord[]>>("/v1/memory/current-state", {
      method: "POST",
      body: JSON.stringify(scopedBody({ query, top_k: topK }, scope))
    }),
  explain: (query: string, topK: number, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/explain", {
      method: "POST",
      body: JSON.stringify(scopedBody({ query, top_k: topK }, scope))
    }),
  timeline: (scope: Scope, threadId?: string, limit = 50) =>
    request<MaseResponse<JsonRecord[]>>(
      withQuery("/v1/memory/timeline", { ...compactScope(scope), thread_id: threadId, limit })
    ),
  writeInspector: (scope: Scope, threadId?: string, limit = 50) =>
    request<MaseResponse<WriteInspectorData>>(
      withQuery("/v1/ui/write-inspector", { ...compactScope(scope), thread_id: threadId, limit })
    ),
  repairPlan: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<RepairPlanData>>("/v1/ui/repair-plan", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  repairCases: (filters: { status?: string; issue_type?: string; limit?: number } = {}) =>
    request<MaseResponse<RepairCasesData>>(withQuery("/v1/ui/repair-cases", filters)),
  createRepairCase: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<{ case: RepairCase }>>("/v1/ui/repair-cases", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  transitionRepairCase: (caseId: string, body: JsonRecord) =>
    request<MaseResponse<{ case: RepairCase }>>(`/v1/ui/repair-cases/${encodeURIComponent(caseId)}/transition`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  proposeRepairDiff: (caseId: string) =>
    request<MaseResponse<RepairCaseDiffData>>(`/v1/ui/repair-cases/${encodeURIComponent(caseId)}/diff`, {
      method: "POST"
    }),
  runRepairSandbox: (caseId: string) =>
    request<MaseResponse<RepairCaseSandboxData>>(`/v1/ui/repair-cases/${encodeURIComponent(caseId)}/sandbox`, {
      method: "POST"
    }),
  executeRepairCase: (caseId: string, body: JsonRecord) =>
    request<MaseResponse<RepairCaseExecutionData>>(`/v1/ui/repair-cases/${encodeURIComponent(caseId)}/execute`, {
      method: "POST",
      body: JSON.stringify(body)
    }),
  writeEvent: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/events", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  correctMemory: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/corrections", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  facts: (scope: Scope, category?: string) =>
    request<MaseResponse<JsonRecord[]>>(withQuery("/v1/memory/facts", { ...compactScope(scope), category })),
  upsertFact: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/facts", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  factHistory: (scope: Scope, category?: string, entityKey?: string) =>
    request<MaseResponse<JsonRecord[]>>(
      withQuery("/v1/memory/facts/history", {
        ...compactScope(scope),
        category,
        entity_key: entityKey,
        limit: 100
      })
    ),
  forgetFact: (category: string, entityKey: string, scope: Scope) =>
    request<MaseResponse<JsonRecord>>(
      withQuery(`/v1/memory/facts/${encodeURIComponent(category)}/${encodeURIComponent(entityKey)}`, compactScope(scope)),
      { method: "DELETE" }
    ),
  getSessionState: (sessionId: string, scope: Scope, includeExpired: boolean) =>
    request<MaseResponse<JsonRecord[]>>(
      withQuery(`/v1/memory/session-state/${encodeURIComponent(sessionId)}`, {
        ...compactScope(scope),
        include_expired: includeExpired
      })
    ),
  upsertSessionState: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/session-state", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  forgetSessionState: (sessionId: string, contextKey: string | undefined, scope: Scope) =>
    request<MaseResponse<JsonRecord>>(
      withQuery(`/v1/memory/session-state/${encodeURIComponent(sessionId)}`, {
        ...compactScope(scope),
        context_key: contextKey
      }),
      { method: "DELETE" }
    ),
  procedures: (scope: Scope, procedureType?: string) =>
    request<MaseResponse<JsonRecord[]>>(
      withQuery("/v1/memory/procedures", { ...compactScope(scope), procedure_type: procedureType })
    ),
  registerProcedure: (body: JsonRecord, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/procedures", {
      method: "POST",
      body: JSON.stringify(scopedBody(body, scope))
    }),
  snapshots: (scope: Scope, threadId?: string) =>
    request<MaseResponse<JsonRecord[]>>(
      withQuery("/v1/memory/snapshots", { ...compactScope(scope), thread_id: threadId })
    ),
  consolidate: (threadId: string, maxItems: number, scope: Scope) =>
    request<MaseResponse<JsonRecord>>("/v1/memory/snapshots/consolidate", {
      method: "POST",
      body: JSON.stringify(scopedBody({ thread_id: threadId, max_items: maxItems }, scope))
    })
};
