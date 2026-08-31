import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const requestMock = vi.fn().mockResolvedValue("RESULT");

vi.mock("@/utils/http", () => ({
  http: { request: (...args: unknown[]) => requestMock(...args) }
}));

import {
  getStatisticsApi,
  getInterviewsApi,
  getInterviewsTemplatesApi,
  getInterviewTemplateDetailApi,
  extractInterviewFieldsApi,
  ocrInterviewImageApi,
  saveInterviewApi,
  getInterviewDetailApi,
  firstBatchInterviewApi,
  ignoreInterviewItemApi,
  unignoreInterviewItemApi,
  endInterviewApi,
  suspendInterviewApi,
  resumeInterviewApi,
  getInterviewReportApi,
  exportInterviewReportApi,
  deleteInterviewApi
} from "@/api/interview";

beforeEach(() => requestMock.mockClear());
afterEach(() => requestMock.mockReset());

describe("api/interview — list / templates / statistics", () => {
  it("getStatisticsApi → GET /api/v1/interviews/statistics", async () => {
    await getStatisticsApi();
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/interviews/statistics");
  });

  it("getInterviewsApi → GET /api/v1/interviews", async () => {
    await getInterviewsApi();
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/interviews");
  });

  it("getInterviewsTemplatesApi → GET /api/v1/templates", async () => {
    await getInterviewsTemplatesApi();
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/templates");
  });

  it("getInterviewTemplateDetailApi(id) → GET /api/v1/templates/{id}", async () => {
    await getInterviewTemplateDetailApi("t-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/templates/t-1");
  });
});

describe("api/interview — extract / ocr / save", () => {
  it("extractInterviewFieldsApi({transcript,...}, signal) → POST /api/v1/interviews/extract，传 data+signal", async () => {
    const data = {
      transcript: "hi",
      template_id: "t",
      fields: ["a"],
      field_labels: {},
      field_types: {},
      current_values: {}
    };
    const ac = new AbortController();
    await extractInterviewFieldsApi(data, ac.signal);
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/extract");
    expect(p).toEqual({ data, signal: ac.signal });
  });

  it("extractInterviewFieldsApi 第二个参数缺省时不传 signal", async () => {
    const data = {
      transcript: "hi",
      template_id: "t",
      fields: [],
      field_labels: {},
      field_types: {},
      current_values: {}
    };
    await extractInterviewFieldsApi(data);
    const [, , p] = requestMock.mock.calls[0];
    expect(p).toEqual({ data, signal: undefined });
  });

  it("ocrInterviewImageApi({image_base64}) → POST /api/v1/interviews/ocr", async () => {
    await ocrInterviewImageApi({ image_base64: "BASE64" });
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/ocr");
    expect(p).toEqual({ data: { image_base64: "BASE64" } });
  });

  it("saveInterviewApi(form) → POST /api/v1/interviews", async () => {
    const form = {
      base_info: {
        title: "x",
        project: "p",
        interviewee: "i",
        start_time: "t",
        duration: "d",
        end_time: "e"
      },
      goal: "g",
      template_id: "t-1"
    };
    await saveInterviewApi(form);
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews");
    expect(p).toEqual({ data: form });
  });
});

describe("api/interview — single interview lifecycle", () => {
  it("getInterviewDetailApi(id) → GET /api/v1/interviews/{id}", async () => {
    await getInterviewDetailApi("s-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/interviews/s-1");
  });

  it("firstBatchInterviewApi(sessionId) → POST /api/v1/interviews/{id}/first-batch", async () => {
    await firstBatchInterviewApi("s-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/first-batch");
  });

  it("ignoreInterviewItemApi → POST .../items/{itemId}/ignore", async () => {
    await ignoreInterviewItemApi("s-1", "i-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/items/i-1/ignore");
  });

  it("unignoreInterviewItemApi → POST .../items/{itemId}/unignore", async () => {
    await unignoreInterviewItemApi("s-1", "i-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/items/i-1/unignore");
  });

  it("endInterviewApi → POST /api/v1/interviews/{id}/end", async () => {
    await endInterviewApi("s-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/end");
  });

  it("suspendInterviewApi → POST /api/v1/interviews/{id}/suspend", async () => {
    await suspendInterviewApi("s-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/suspend");
  });

  it("resumeInterviewApi → POST /api/v1/interviews/{id}/resume", async () => {
    await resumeInterviewApi("s-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/resume");
  });

  it("deleteInterviewApi → DELETE /api/v1/interviews/{id}", async () => {
    await deleteInterviewApi("s-1");
    const [m, u] = requestMock.mock.calls[0];
    expect(m).toBe("delete");
    expect(u).toBe("/api/v1/interviews/s-1");
  });
});

describe("api/interview — report / export", () => {
  it("getInterviewReportApi(id) → GET .../report，缺省 options 不发 force 参数", async () => {
    await getInterviewReportApi("s-1");
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/interviews/s-1/report");
    expect(p).toEqual({ params: { force: undefined } });
  });

  it("getInterviewReportApi(id, {force:true}) → params.force === true", async () => {
    await getInterviewReportApi("s-1", { force: true });
    const [, , p] = requestMock.mock.calls[0];
    expect(p).toEqual({ params: { force: true } });
  });

  it("exportInterviewReportApi 默认 format='md' → POST .../export?format=md, responseType=blob", async () => {
    await exportInterviewReportApi("s-1");
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/interviews/s-1/export");
    expect(p).toEqual({ params: { format: "md" }, responseType: "blob" });
  });

  it("exportInterviewReportApi(id, 'pdf') → format='pdf'", async () => {
    await exportInterviewReportApi("s-1", "pdf");
    const [, , p] = requestMock.mock.calls[0];
    expect(p.params.format).toBe("pdf");
  });
});