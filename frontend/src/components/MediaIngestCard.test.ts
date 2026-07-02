import { describe, expect, it } from "vitest";
import type { MediaUploadData } from "../types";
import { summarizeMediaUpload } from "./MediaIngestCard";

const data: MediaUploadData = {
  media_id: 7,
  sha256: "abcdef0123456789".repeat(4),
  media_type: "image/png",
  deduplicated: false,
  extraction: {
    extractor: "vision",
    model: "qwen2.5vl:7b",
    version: "1",
    full_text_excerpt: "INVOICE ACME-INV-2026-001",
    facts: [
      {
        category: "finance_budget",
        key: "invoice_total",
        value: "4200 EUR",
        confidence: 0.9,
        evidence: "total 4200 EUR"
      }
    ],
    warnings: ["page 1: low confidence"]
  }
};

describe("summarizeMediaUpload", () => {
  it("produces sha prefix, fact lines and warnings", () => {
    const summary = summarizeMediaUpload(data);
    expect(summary.shaPrefix).toBe("abcdef012345");
    expect(summary.factLines).toEqual(["finance_budget.invoice_total = 4200 EUR"]);
    expect(summary.warnings).toEqual(["page 1: low confidence"]);
    expect(summary.dedupLabel).toBe("");
    expect(summary.model).toBe("qwen2.5vl:7b");
  });

  it("marks deduplicated uploads", () => {
    const summary = summarizeMediaUpload({ ...data, deduplicated: true });
    expect(summary.dedupLabel).toContain("已入库");
  });
});
