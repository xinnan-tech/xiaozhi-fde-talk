import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const requestMock = vi.fn().mockResolvedValue("RESULT");

vi.mock("@/utils/http", () => ({
  http: { request: (...args: unknown[]) => requestMock(...args) }
}));

import {
  systemConfigApi,
  systemDiagnosticsApi,
  systemAsrDiagnosticsApi,
  systemLlmDiagnosticsApi,
  systemOcrDiagnosticsApi,
  systemConfigSaveApi
} from "@/api/system";

describe("api/system", () => {
  beforeEach(() => requestMock.mockClear());
  afterEach(() => requestMock.mockReset());

  it("module exports 6 expected functions", () => {
    expect(typeof systemConfigApi).toBe("function");
    expect(typeof systemDiagnosticsApi).toBe("function");
    expect(typeof systemAsrDiagnosticsApi).toBe("function");
    expect(typeof systemLlmDiagnosticsApi).toBe("function");
    expect(typeof systemOcrDiagnosticsApi).toBe("function");
    expect(typeof systemConfigSaveApi).toBe("function");
  });

  it("systemConfigApi → GET /api/v1/admin/config", async () => {
    await systemConfigApi();
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("get");
    expect(url).toBe("/api/v1/admin/config");
    expect(param).toBeUndefined();
  });

  it("systemDiagnosticsApi → POST /api/v1/diagnostics", async () => {
    await systemDiagnosticsApi();
    const [method, url] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/diagnostics");
  });

  it("systemAsrDiagnosticsApi → POST /api/v1/diagnostics/asr", async () => {
    await systemAsrDiagnosticsApi();
    const [method, url] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/diagnostics/asr");
  });

  it("systemLlmDiagnosticsApi → POST /api/v1/diagnostics/llm", async () => {
    await systemLlmDiagnosticsApi();
    const [method, url] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/diagnostics/llm");
  });

  it("systemOcrDiagnosticsApi → POST /api/v1/diagnostics/ocr", async () => {
    await systemOcrDiagnosticsApi();
    const [method, url] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/diagnostics/ocr");
  });

  it("systemConfigSaveApi(name, config) → PUT /api/v1/admin/config/{name}", async () => {
    const cfg = { llm: { model: "gpt" } };
    await systemConfigSaveApi("llm", cfg);
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("put");
    expect(url).toBe("/api/v1/admin/config/llm");
    expect(param).toEqual({ data: cfg });
  });
});