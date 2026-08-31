import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// 用 vi.hoisted 让 request 在 vi.mock 工厂内拿到一份 spy。
// 必须在 import 业务模块前生效（vitest 会自动 hoist vi.mock 本身）。
const { requestMock, baseUrlApiSpy } = vi.hoisted(() => ({
  requestMock: vi.fn(),
  baseUrlApiSpy: vi.fn((url: string) => url)
}));

vi.mock("@/utils/http", () => ({
  http: {
    request: (...args: unknown[]) => {
      requestMock(...args);
      return Promise.resolve("RESULT");
    }
  }
}));

vi.mock("@/api/utils", () => ({
  baseUrlApi: (url: string) => {
    baseUrlApiSpy(url);
    return url;
  }
}));

import {
  loginApi,
  registerApi,
  refreshApi,
  logoutApi,
  changePasswordApi,
  registrationStatusApi
} from "@/api/user";

describe("api/user — baseUrlApi passthrough", () => {
  beforeEach(() => {
    requestMock.mockClear();
    baseUrlApiSpy.mockClear();
  });
  afterEach(() => {
    requestMock.mockReset();
    baseUrlApiSpy.mockReset();
  });

  it("baseUrlApi 不修改 url（仅返回原值，符合 utils.ts 的实现）", () => {
    expect(baseUrlApiSpy("/x")).toBe("/x");
  });
});

describe("api/user — loginApi", () => {
  beforeEach(() => {
    requestMock.mockClear();
    baseUrlApiSpy.mockClear();
  });
  afterEach(() => {
    requestMock.mockReset();
  });

  it("loginApi({username, password}) 调用 http.request('post', url, {data})", async () => {
    await loginApi({ username: "alice", password: "pw" });
    expect(requestMock).toHaveBeenCalledTimes(1);
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/auth/login");
    expect(param).toEqual({ data: { username: "alice", password: "pw" } });
  });

  it("loginApi 返回 http.request 的 resolve 值", async () => {
    await expect(
      loginApi({ username: "u", password: "p" })
    ).resolves.toBe("RESULT");
  });
});

describe("api/user — registerApi", () => {
  beforeEach(() => requestMock.mockClear());
  afterEach(() => requestMock.mockReset());

  it("registerApi({username, password, confirm_password}) → POST /api/v1/auth/register", async () => {
    await registerApi({
      username: "u",
      password: "p",
      confirm_password: "p"
    });
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/auth/register");
    expect(param).toEqual({
      data: { username: "u", password: "p", confirm_password: "p" }
    });
  });
});

describe("api/user — changePasswordApi", () => {
  beforeEach(() => requestMock.mockClear());
  afterEach(() => requestMock.mockReset());

  it("changePasswordApi({old_password, new_password}) → POST /api/v1/auth/change-password", async () => {
    await changePasswordApi({ old_password: "old", new_password: "new" });
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/auth/change-password");
    expect(param).toEqual({ data: { old_password: "old", new_password: "new" } });
  });
});

describe("api/user — registrationStatusApi", () => {
  beforeEach(() => requestMock.mockClear());
  afterEach(() => requestMock.mockReset());

  it("registrationStatusApi() → GET /api/v1/auth/registration-status", async () => {
    await registrationStatusApi();
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("get");
    expect(url).toBe("/api/v1/auth/registration-status");
    expect(param).toBeUndefined();
  });
});

describe("api/user — refreshApi", () => {
  beforeEach(() => requestMock.mockClear());
  afterEach(() => requestMock.mockReset());

  it("refreshApi({refresh_token}) → POST /api/v1/auth/refresh", async () => {
    await refreshApi({ refresh_token: "rt-1" });
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/auth/refresh");
    expect(param).toEqual({ data: { refresh_token: "rt-1" } });
  });
});

describe("api/user — logoutApi", () => {
  beforeEach(() => requestMock.mockClear());
  afterEach(() => requestMock.mockReset());

  it("logoutApi({refresh_token}) → POST /api/v1/auth/logout", async () => {
    await logoutApi({ refresh_token: "rt-1" });
    const [method, url, param] = requestMock.mock.calls[0];
    expect(method).toBe("post");
    expect(url).toBe("/api/v1/auth/logout");
    expect(param).toEqual({ data: { refresh_token: "rt-1" } });
  });
});