import { afterEach, describe, expect, it, vi } from "vitest";
import { api, saveInternalApiKey } from "./api";

describe("api.runTrace", () => {
  afterEach(() => {
    saveInternalApiKey("");
    vi.restoreAllMocks();
  });

  it("defaults trace runs to dry-run mode", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.trace", data: {} })
    } as Response);

    await api.runTrace("What changed?");

    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      query: "What changed?",
      log: false
    });
  });

  it("enables trace logging only when explicitly requested", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.trace", data: {} })
    } as Response);

    await api.runTrace("Remember this trace", true);

    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      query: "Remember this trace",
      log: true
    });
  });

  it("attaches the configured internal API key to requests", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.trace", data: {} })
    } as Response);

    saveInternalApiKey("phase-1-key");
    await api.runTrace("Authorized trace");

    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer phase-1-key");
  });

  it("requests the observability payload with a bounded recent-call limit", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.observability", data: {} })
    } as Response);

    await api.observability(50);

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/observability?recent_limit=50");
  });

  it("requests cost center pricing and summary payloads", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.cost", data: {} })
    } as Response);

    await api.costPricing();
    await api.costSummary(100);
    await api.costRouting();

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/cost/pricing");
    expect(String(fetchSpy.mock.calls[1]?.[0])).toContain("/v1/ui/cost/summary?recent_limit=100");
    expect(String(fetchSpy.mock.calls[2]?.[0])).toContain("/v1/ui/cost/routing");
  });

  it("requests audit events with filters", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.audit.events", data: { events: [] } })
    } as Response);

    await api.auditEvents({
      actor_id: "ops-user",
      action: "memory.event.create",
      resource_type: "memory_event",
      limit: 25
    });

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("/v1/ui/audit/events?");
    expect(url).toContain("actor_id=ops-user");
    expect(url).toContain("action=memory.event.create");
    expect(url).toContain("resource_type=memory_event");
    expect(url).toContain("limit=25");
  });

  it("requests privacy scan and preview payloads", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.privacy", data: {} })
    } as Response);

    await api.privacyScan({ tenant_id: "tenant-a", workspace_id: "ws-a" }, 50);
    await api.privacyPreview({ note: "alice@example.com" });

    const scanUrl = String(fetchSpy.mock.calls[0]?.[0]);
    expect(scanUrl).toContain("/v1/ui/privacy/scan?");
    expect(scanUrl).toContain("tenant_id=tenant-a");
    expect(scanUrl).toContain("workspace_id=ws-a");
    expect(scanUrl).toContain("limit=50");
    expect(String(fetchSpy.mock.calls[1]?.[0])).toContain("/v1/ui/privacy/preview");
    expect(JSON.parse(String((fetchSpy.mock.calls[1]?.[1] as RequestInit).body))).toEqual({
      note: "alice@example.com"
    });
  });

  it("requests lifecycle report with scope and category", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.lifecycle", data: {} })
    } as Response);

    await api.lifecycle({ tenant_id: "tenant-a" }, "general_facts", 25);

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("/v1/ui/lifecycle?");
    expect(url).toContain("tenant_id=tenant-a");
    expect(url).toContain("category=general_facts");
    expect(url).toContain("limit=25");
  });

  it("requests quality score report with optional query", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.quality", data: {} })
    } as Response);

    await api.quality({ tenant_id: "tenant-a" }, "owner", 30);

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("/v1/ui/quality?");
    expect(url).toContain("tenant_id=tenant-a");
    expect(url).toContain("query=owner");
    expect(url).toContain("limit=30");
  });

  it("requests answer support with scoped body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.answer_support", data: {} })
    } as Response);

    await api.answerSupport({ answer: "Alice owns it.", query: "owner" }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/answer-support");
    expect(JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      answer: "Alice owns it.",
      query: "owner",
      tenant_id: "tenant-a"
    });
  });

  it("requests refusal quality with scoped body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.refusal_quality", data: {} })
    } as Response);

    await api.refusalQuality({ query: "owner", answer: "I do not know." }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/refusal-quality");
    expect(JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      query: "owner",
      answer: "I do not know.",
      tenant_id: "tenant-a"
    });
  });

  it("requests why-not-remembered diagnostics with scoped body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.why_not_remembered", data: {} })
    } as Response);

    await api.whyNotRemembered({ query: "owner", thread_id: "thread-a" }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/why-not-remembered");
    expect(JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      query: "owner",
      thread_id: "thread-a",
      tenant_id: "tenant-a"
    });
  });

  it("requests synthetic replay with scoped cases", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.synthetic_replay", data: {} })
    } as Response);

    await api.syntheticReplay({ cases: [{ query: "owner", expected_terms: ["Alice"] }] }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/synthetic-replay");
    expect(JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      cases: [{ query: "owner", expected_terms: ["Alice"] }],
      tenant_id: "tenant-a"
    });
  });

  it("requests golden tests with scoped cases", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.golden_tests", data: {} })
    } as Response);

    await api.goldenTests({ cases: [{ query: "owner", severity: "critical" }] }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/golden-tests");
    expect(JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      cases: [{ query: "owner", severity: "critical" }],
      tenant_id: "tenant-a"
    });
  });

  it("requests SLO dashboard with scoped golden cases", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.slo_dashboard", data: {} })
    } as Response);

    await api.sloDashboard({ cases: [{ query: "owner" }] }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/slo-dashboard");
    expect(JSON.parse(String((fetchSpy.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      cases: [{ query: "owner" }],
      tenant_id: "tenant-a"
    });
  });

  it("requests drift report with scope and category", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.drift", data: {} })
    } as Response);

    await api.drift({ tenant_id: "tenant-a" }, "project");

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/drift");
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("tenant_id=tenant-a");
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("category=project");
  });

  it("requests inspectors and scoped incidents", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.incidents", data: {} })
    } as Response);

    await api.inspectors();
    await api.incidents({ cases: [{ query: "owner" }] }, { tenant_id: "tenant-a" });

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/inspectors");
    expect(String(fetchSpy.mock.calls[1]?.[0])).toContain("/v1/ui/incidents");
    expect(JSON.parse(String((fetchSpy.mock.calls[1]?.[1] as RequestInit).body))).toEqual({
      cases: [{ query: "owner" }],
      tenant_id: "tenant-a"
    });
  });

  it("requests trace history with supported filters", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.traces", data: { summaries: [] } })
    } as Response);

    await api.traces({
      route_action: "search_memory",
      component: "retrieval",
      has_cloud_call: true,
      has_risk: false,
      limit: 20
    });

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("/v1/ui/traces?");
    expect(url).toContain("route_action=search_memory");
    expect(url).toContain("component=retrieval");
    expect(url).toContain("has_cloud_call=true");
    expect(url).toContain("has_risk=false");
    expect(url).toContain("limit=20");
  });

  it("requests encoded trace detail by id", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.trace", data: { trace: {} } })
    } as Response);

    await api.traceDetail("trace/a b");

    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/traces/trace%2Fa%20b");
  });

  it("requests the write inspector with scope and thread filters", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.write_inspector", data: { write_paths: [], summary: {} } })
    } as Response);

    await api.writeInspector({ tenant_id: "t1", workspace_id: "w1", visibility: "shared" }, "thread-1", 25);

    const url = String(fetchSpy.mock.calls[0]?.[0]);
    expect(url).toContain("/v1/ui/write-inspector?");
    expect(url).toContain("tenant_id=t1");
    expect(url).toContain("workspace_id=w1");
    expect(url).toContain("visibility=shared");
    expect(url).toContain("thread_id=thread-1");
    expect(url).toContain("limit=25");
  });

  it("builds a repair plan with scoped evidence", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.repair_plan", data: {} })
    } as Response);

    await api.repairPlan(
      { issue_type: "recall_failure", symptom: "old fact", evidence: { trace_id: "t1" } },
      { tenant_id: "tenant-a" }
    );

    const init = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/repair-plan");
    expect(JSON.parse(String(init.body))).toEqual({
      issue_type: "recall_failure",
      symptom: "old fact",
      evidence: { trace_id: "t1" },
      tenant_id: "tenant-a"
    });
  });

  it("manages repair cases through scoped lifecycle APIs", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ object: "mase.ui.repair_case", data: { case: { case_id: "repair-1" } } })
    } as Response);

    await api.repairCases({ status: "open", limit: 25 });
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/ui/repair-cases?status=open&limit=25");

    await api.createRepairCase(
      { issue_type: "incorrect_memory", symptom: "wrong owner", evidence: { trace_id: "t1" } },
      { tenant_id: "tenant-a" }
    );
    expect(String(fetchSpy.mock.calls[1]?.[0])).toContain("/v1/ui/repair-cases");
    expect(JSON.parse(String((fetchSpy.mock.calls[1]?.[1] as RequestInit).body))).toEqual({
      issue_type: "incorrect_memory",
      symptom: "wrong owner",
      evidence: { trace_id: "t1" },
      tenant_id: "tenant-a"
    });

    await api.transitionRepairCase("repair/a b", { status: "diagnosed" });
    expect(String(fetchSpy.mock.calls[2]?.[0])).toContain("/v1/ui/repair-cases/repair%2Fa%20b/transition");
    expect(JSON.parse(String((fetchSpy.mock.calls[2]?.[1] as RequestInit).body))).toEqual({ status: "diagnosed" });

    await api.proposeRepairDiff("repair/a b");
    expect(String(fetchSpy.mock.calls[3]?.[0])).toContain("/v1/ui/repair-cases/repair%2Fa%20b/diff");
    expect((fetchSpy.mock.calls[3]?.[1] as RequestInit).method).toBe("POST");

    await api.runRepairSandbox("repair/a b");
    expect(String(fetchSpy.mock.calls[4]?.[0])).toContain("/v1/ui/repair-cases/repair%2Fa%20b/sandbox");
    expect((fetchSpy.mock.calls[4]?.[1] as RequestInit).method).toBe("POST");

    await api.executeRepairCase("repair/a b", { confirm: true, operations: [{ operation: "upsert_fact" }] });
    expect(String(fetchSpy.mock.calls[5]?.[0])).toContain("/v1/ui/repair-cases/repair%2Fa%20b/execute");
    expect(JSON.parse(String((fetchSpy.mock.calls[5]?.[1] as RequestInit).body))).toEqual({
      confirm: true,
      operations: [{ operation: "upsert_fact" }]
    });
  });
});
