import type { JsonValue, Scope } from "./types";

export const SCOPE_STORAGE_KEY = "mase.scope";
const SCOPE_KEYS = ["tenant_id", "workspace_id", "visibility"] as const;
type ScopeKey = (typeof SCOPE_KEYS)[number];
type ScopeCandidate = Partial<Record<ScopeKey, unknown>>;

export type ScopeGuardStatus = {
  level: "strict" | "partial" | "global";
  missingKeys: ScopeKey[];
  label: string;
  message: string;
};

export function compactScope(scope: ScopeCandidate): Scope {
  return SCOPE_KEYS.reduce<Scope>((result, key) => {
    const value = scope[key];
    if (typeof value === "string" && value !== "") {
      result[key] = value;
    }
    return result;
  }, {});
}

export function getScopeGuardStatus(scope: Scope): ScopeGuardStatus {
  const compact = compactScope(scope);
  const missingKeys = SCOPE_KEYS.filter((key) => !compact[key]);
  if (missingKeys.length === 0) {
    return {
      level: "strict",
      missingKeys,
      label: "Strict scope",
      message: "tenant / workspace / visibility are all explicit."
    };
  }
  if (missingKeys.length === SCOPE_KEYS.length) {
    return {
      level: "global",
      missingKeys,
      label: "Global scope",
      message: "No scope filters are active; results may include every local memory row."
    };
  }
  return {
    level: "partial",
    missingKeys,
    label: "Partial scope",
    message: `Missing ${missingKeys.join(", ")}; inspect results for cross-scope leakage.`
  };
}

function parseScope(value: unknown): Scope {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }

  const record = value as Record<string, unknown>;
  return compactScope({
    tenant_id: record.tenant_id,
    workspace_id: record.workspace_id,
    visibility: record.visibility
  });
}

export function readStoredScope(storage: Pick<Storage, "getItem"> = localStorage): Scope {
  const stored = storage.getItem(SCOPE_STORAGE_KEY);
  if (!stored) {
    return {};
  }

  try {
    return parseScope(JSON.parse(stored));
  } catch {
    return {};
  }
}

export function saveStoredScope(scope: Scope, storage: Pick<Storage, "setItem"> = localStorage): void {
  storage.setItem(SCOPE_STORAGE_KEY, JSON.stringify(compactScope(scope)));
}

const SENSITIVE_DETAIL_KEYS = new Set([
  "api_key",
  "apikey",
  "authorization",
  "cookie",
  "id_token",
  "password",
  "raw_provider_request",
  "raw_provider_response",
  "raw_request",
  "raw_response",
  "refresh_token",
  "secret",
  "set_cookie",
  "access_token"
]);

export function isSensitiveKey(key: string): boolean {
  const normalized = key.toLowerCase().replaceAll("-", "_");
  return (
    SENSITIVE_DETAIL_KEYS.has(normalized) ||
    normalized.includes("headers") ||
    normalized.endsWith("_api_key") ||
    normalized.endsWith("_secret") ||
    normalized.endsWith("_password")
  );
}

export function sanitizeForDisplay(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sanitizeForDisplay);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([key]) => !isSensitiveKey(key))
        .map(([key, child]) => [key, sanitizeForDisplay(child)])
    );
  }
  return value;
}

export function formatValue(value: JsonValue | undefined): string {
  if (value === undefined || value === null) {
    return "";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

export function downloadJson(filename: string, value: unknown): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
