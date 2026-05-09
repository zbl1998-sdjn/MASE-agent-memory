import { describe, expect, it } from "vitest";
import type { Scope } from "./types";
import {
  compactScope,
  getScopeGuardStatus,
  isSensitiveKey,
  readStoredScope,
  sanitizeForDisplay,
  saveStoredScope
} from "./utils";

function readableStorage(value: string | null): Pick<Storage, "getItem"> {
  return {
    getItem: () => value
  };
}

function writableStorage(writes: Array<{ key: string; value: string }>): Pick<Storage, "setItem"> {
  return {
    setItem: (key, value) => writes.push({ key, value })
  };
}

describe("readStoredScope", () => {
  it("reads valid stored scope fields", () => {
    expect(
      readStoredScope(
        readableStorage(
          JSON.stringify({
            tenant_id: "tenant-a",
            workspace_id: "workspace-a",
            visibility: "shared",
            unexpected: "ignored"
          })
        )
      )
    ).toEqual({
      tenant_id: "tenant-a",
      workspace_id: "workspace-a",
      visibility: "shared"
    });
  });

  it("falls back to an empty scope when localStorage contains invalid JSON", () => {
    expect(readStoredScope(readableStorage("{bad json"))).toEqual({});
  });

  it("falls back to an empty scope for malformed top-level JSON shapes", () => {
    for (const stored of ["null", "[]", '[{"tenant_id":"tenant-a"}]', "123", "true", JSON.stringify("tenant-a")]) {
      expect(readStoredScope(readableStorage(stored))).toEqual({});
    }
  });

  it("drops malformed scope fields with wrong types", () => {
    expect(
      readStoredScope(
        readableStorage(
          JSON.stringify({
            tenant_id: null,
            workspace_id: false,
            visibility: { mode: "shared" }
          })
        )
      )
    ).toEqual({});
  });

  it("filters empty strings and keeps whitespace strings as explicit values", () => {
    expect(
      readStoredScope(
        readableStorage(
          JSON.stringify({
            tenant_id: "",
            workspace_id: "   ",
            visibility: "shared"
          })
        )
      )
    ).toEqual({
      workspace_id: "   ",
      visibility: "shared"
    });
  });

  it("keeps partial valid string fields and ignores invalid fields", () => {
    expect(
      readStoredScope(
        readableStorage(
          JSON.stringify({
            tenant_id: "tenant-a",
            workspace_id: 42,
            visibility: "public"
          })
        )
      )
    ).toEqual({
      tenant_id: "tenant-a",
      visibility: "public"
    });
  });
});

describe("compactScope", () => {
  it("drops undefined and empty string values", () => {
    expect(compactScope({ tenant_id: undefined, workspace_id: "", visibility: undefined })).toEqual({});
  });

  it("keeps only known string scope fields", () => {
    const scope = {
      tenant_id: "tenant-a",
      workspace_id: "workspace-a",
      visibility: "shared",
      extra: "ignored",
      malformed: 42
    } as Parameters<typeof compactScope>[0] & Record<string, unknown>;

    expect(compactScope(scope)).toEqual({
      tenant_id: "tenant-a",
      workspace_id: "workspace-a",
      visibility: "shared"
    });
  });
});

describe("getScopeGuardStatus", () => {
  it("marks complete scope as strict", () => {
    expect(
      getScopeGuardStatus({
        tenant_id: "tenant-a",
        workspace_id: "workspace-a",
        visibility: "shared"
      })
    ).toMatchObject({ level: "strict", missingKeys: [] });
  });

  it("marks empty scope as global", () => {
    expect(getScopeGuardStatus({})).toMatchObject({
      level: "global",
      missingKeys: ["tenant_id", "workspace_id", "visibility"]
    });
  });

  it("marks incomplete scope as partial", () => {
    expect(getScopeGuardStatus({ tenant_id: "tenant-a" })).toMatchObject({
      level: "partial",
      missingKeys: ["workspace_id", "visibility"]
    });
  });
});

describe("saveStoredScope", () => {
  it("stores only known non-empty string scope fields", () => {
    const writes: Array<{ key: string; value: string }> = [];
    const scope = {
      tenant_id: "tenant-a",
      workspace_id: "",
      visibility: "shared",
      unexpected: "ignored",
      malformed: 42
    } as Scope & Record<string, unknown>;

    saveStoredScope(scope, writableStorage(writes));

    expect(writes).toEqual([
      {
        key: "mase.scope",
        value: JSON.stringify({ tenant_id: "tenant-a", visibility: "shared" })
      }
    ]);
  });
});

describe("isSensitiveKey", () => {
  it("matches normalized exact sensitive keys", () => {
    for (const key of [
      "Authorization",
      "api-key",
      "apikey",
      "password",
      "secret",
      "access-token",
      "refresh_token",
      "id-token"
    ]) {
      expect(isSensitiveKey(key)).toBe(true);
    }
  });

  it("matches sensitive suffixes and any key containing headers", () => {
    for (const key of ["x-api-key", "client_secret", "db-password", "requestHeaders", "raw-provider-headers"]) {
      expect(isSensitiveKey(key)).toBe(true);
    }
  });

  it("does not match safe trace display fields", () => {
    for (const key of ["route_action", "answer_preview", "total_tokens", "estimated_cost_usd"]) {
      expect(isSensitiveKey(key)).toBe(false);
    }
  });
});

describe("sanitizeForDisplay", () => {
  it("recursively removes sensitive trace detail keys from objects and arrays", () => {
    expect(
      sanitizeForDisplay({
        route_action: "search_memory",
        "x-api-key": "secret-key",
        nested: {
          access_token: "token",
          safe: "kept",
          responseHeaders: { authorization: "Bearer token" }
        },
        calls: [{ db_password: "pw", component: "retrieval" }]
      })
    ).toEqual({
      route_action: "search_memory",
      nested: {
        safe: "kept"
      },
      calls: [{ component: "retrieval" }]
    });
  });
});
