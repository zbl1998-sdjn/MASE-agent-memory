export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonRecord = Record<string, JsonValue | undefined>;

export type Scope = {
  tenant_id?: string;
  workspace_id?: string;
  visibility?: string;
};

export type MaseResponse<T> = {
  object: string;
  data: T;
  metadata?: JsonRecord;
};

export type ChatMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type MemoryFact = JsonRecord & {
  category?: string;
  entity_key?: string;
  entity_value?: string;
  updated_at?: string;
};

export type BootstrapData = {
  profile_templates: string[];
  models: Record<string, JsonRecord>;
  validation: JsonRecord;
  product?: {
    name: string;
    tagline: string;
    features: Array<{ title: string; description: string }>;
    quick_actions: Array<{ label: string; target: string; description: string }>;
    frontend_static_ready: boolean;
    auth_required: boolean;
    read_only: boolean;
  };
};

export type ChartPoint = {
  name?: string;
  date?: string;
  value: number;
};

export type DashboardData = {
  kpis: Record<string, number>;
  validation: JsonRecord;
  charts: {
    facts_by_category: ChartPoint[];
    events_by_role: ChartPoint[];
    events_by_thread: ChartPoint[];
    activity_by_day: ChartPoint[];
    fact_freshness: ChartPoint[];
    source_counts: ChartPoint[];
  };
  recent_activity: JsonRecord[];
  top_facts: JsonRecord[];
  procedures: JsonRecord[];
  snapshots: JsonRecord[];
  quick_actions: Array<{ label: string; target: string; description: string }>;
  system_map: Array<{ name: string; status: string; description: string }>;
};

export type ObservabilityData = {
  mode: JsonRecord & {
    read_only?: boolean;
    auth_required?: boolean;
    frontend_static_ready?: boolean;
  };
  models: Record<string, JsonRecord>;
  memory_validation: JsonRecord;
  metrics: {
    event_counters: Record<string, number>;
    latency_ms_avg: Record<string, number>;
  };
  model_health: JsonRecord[];
  model_ledger: {
    totals: Record<string, number>;
    by_agent: JsonRecord[];
    by_model: JsonRecord[];
    recent_calls: JsonRecord[];
  };
  cost_center?: CostSummaryData;
};

export type CostPricingData = {
  catalog: JsonRecord[];
  budget_rules: JsonRecord[];
  status: JsonRecord & {
    cloud_calls_default_to_zero?: boolean;
    local_providers_free?: boolean;
    policy?: string;
    catalog_item_count?: number;
  };
};

export type CostSummaryData = {
  schema_version?: string;
  generated_at?: string;
  totals: Record<string, number>;
  by_agent: JsonRecord[];
  by_model: JsonRecord[];
  recent_events: JsonRecord[];
  pricing_coverage: JsonRecord & {
    catalog_item_count?: number;
    total_call_count?: number;
    priced_call_count?: number;
    unpriced_call_count?: number;
    local_free_call_count?: number;
    cloud_call_count?: number;
    coverage_ratio?: number;
    unpriced_models?: JsonRecord[];
    policy?: string;
  };
  unpriced_call_count: number;
  warning_count: number;
};

export type CostRoutingData = {
  policy: string;
  cloud_models_allowed: boolean;
  catalog_metadata: JsonRecord;
  summary: JsonRecord & {
    route_count?: number;
    allowed_count?: number;
    blocked_count?: number;
    warning_count?: number;
    unpriced_count?: number;
    local_free_count?: number;
  };
  routes: JsonRecord[];
};

export type AuditFilters = {
  actor_id?: string;
  action?: string;
  resource_type?: string;
  limit?: number;
};

export type AuditEventsData = {
  events: JsonRecord[];
};

export type PrivacyScanData = {
  scope: Scope;
  reports: JsonRecord[];
  summary: JsonRecord & {
    item_count?: number;
    finding_count?: number;
    sources_with_findings?: string[];
  };
};

export type PrivacyPreviewData = {
  finding_count: number;
  findings: JsonRecord[];
  redacted: JsonRecord;
};

export type LifecycleData = {
  scope: Scope;
  category?: string;
  summary: JsonRecord & {
    fact_count?: number;
    by_state?: Record<string, number>;
    contract_violation_count?: number;
  };
  facts: JsonRecord[];
  contract: JsonRecord;
};

export type QualityData = {
  scope: Scope;
  query?: string;
  summary: JsonRecord & {
    item_count?: number;
    average_score?: number;
    grade?: string;
    risk_count?: number;
  };
  items: JsonRecord[];
};

export type AnswerSupportData = {
  answer: string;
  query?: string;
  scope: Scope;
  summary: JsonRecord & {
    span_count?: number;
    supported_count?: number;
    weak_count?: number;
    unsupported_count?: number;
    stale_count?: number;
  };
  spans: JsonRecord[];
};

export type RefusalQualityData = {
  answer: string;
  query?: string;
  scope: Scope;
  is_refusal: boolean;
  classification: string;
  severity: string;
  support: JsonRecord;
  evidence_count: number;
  recommended_actions: string[];
};

export type WhyNotRememberedData = {
  query: string;
  scope: Scope;
  thread_id?: string;
  likely_cause: string;
  stages: JsonRecord[];
  samples: JsonRecord;
  recommended_actions: string[];
};

export type SyntheticReplayData = {
  scope: Scope;
  summary: JsonRecord & {
    case_count?: number;
    passed_count?: number;
    failed_count?: number;
    pass_rate?: number;
  };
  results: JsonRecord[];
};

export type GoldenTestsData = {
  scope: Scope;
  summary: JsonRecord & {
    case_count?: number;
    passed_count?: number;
    failed_count?: number;
    critical_failed_count?: number;
    pass_rate?: number;
    release_gate?: string;
  };
  results: JsonRecord[];
};

export type SloDashboardData = {
  scope: Scope;
  summary: JsonRecord & {
    objective_count?: number;
    met_count?: number;
    warning_count?: number;
    breached_count?: number;
    overall_status?: string;
    release_gate?: string;
  };
  objectives: JsonRecord[];
  source_reports: JsonRecord;
};

export type DriftData = {
  scope: Scope;
  category?: string;
  summary: JsonRecord & {
    fact_count?: number;
    issue_count?: number;
    high_count?: number;
    medium_count?: number;
    status?: string;
  };
  issues: JsonRecord[];
};

export type InspectorsData = {
  summary: JsonRecord & {
    inspector_count?: number;
    enabled_count?: number;
  };
  inspectors: JsonRecord[];
};

export type IncidentsData = {
  scope: Scope;
  summary: JsonRecord & {
    incident_count?: number;
    by_severity?: Record<string, number>;
    status?: string;
  };
  incidents: JsonRecord[];
};

export type WriteInspectorData = {
  thread_id?: string;
  write_paths: JsonRecord[];
  summary: Record<string, number>;
};

export type RepairPlanData = {
  issue_type: string;
  scope: Scope;
  symptom: string;
  evidence: JsonRecord;
  risk_checklist: string[];
  recommended_steps: string[];
  agent_prompt: string;
};

export type RepairCase = JsonRecord & {
  case_id: string;
  status: string;
  issue_type: string;
  symptom: string;
  evidence: JsonRecord;
  scope: Scope;
  created_at: string;
  updated_at: string;
  created_by: string;
  events: JsonRecord[];
};

export type RepairCasesData = {
  cases: RepairCase[];
  summary: JsonRecord & {
    total_count?: number;
    by_status?: Record<string, number>;
  };
  metadata: JsonRecord;
};

export type RepairCaseDiffData = {
  case: RepairCase;
  diff: JsonRecord;
};

export type RepairCaseSandboxData = {
  case: RepairCase;
  sandbox: JsonRecord;
};

export type RepairCaseExecutionData = {
  case: RepairCase;
  execution: JsonRecord;
};

export type TraceFilters = {
  route_action?: string;
  component?: string;
  has_cloud_call?: boolean;
  has_risk?: boolean;
  limit?: number;
};

export type TraceSummary = JsonRecord & {
  trace_id?: string;
  schema_version?: string;
  created_at?: string | null;
  user_question?: string;
  route_action?: string;
  answer_preview?: string;
  step_count?: number;
  components?: string[];
  source_files?: string[];
  has_cloud_call?: boolean;
  estimated_cost_usd?: number;
  total_tokens?: number;
  risk_flags?: string[];
  model_call_summary?: JsonRecord;
};

export type TraceListData = {
  summaries: TraceSummary[];
};

export type TraceDetailData = {
  trace: JsonRecord;
};

export type NavKey =
  | "dashboard"
  | "observability"
  | "cost"
  | "audit"
  | "privacy"
  | "lifecycle"
  | "quality"
  | "answer-support"
  | "refusal-quality"
  | "why-not"
  | "synthetic-replay"
  | "golden-tests"
  | "slo-dashboard"
  | "drift"
  | "incidents"
  | "repair"
  | "chat"
  | "recall"
  | "facts"
  | "timeline"
  | "sessions"
  | "procedures";
