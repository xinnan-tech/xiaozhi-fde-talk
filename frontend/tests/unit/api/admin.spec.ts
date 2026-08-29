import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const requestMock = vi.fn().mockResolvedValue("RESULT");

vi.mock("@/utils/http", () => ({
  http: { request: (...args: unknown[]) => requestMock(...args) }
}));

import { listUsersApi, resetPasswordApi } from "@/api/admin";

beforeEach(() => requestMock.mockClear());
afterEach(() => requestMock.mockReset());

describe("api/admin — listUsersApi", () => {
  it("listUsersApi → GET /api/v1/admin/users", async () => {
    await listUsersApi();
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("get");
    expect(u).toBe("/api/v1/admin/users");
    expect(p).toBeUndefined();
  });
});

describe("api/admin — resetPasswordApi", () => {
  it("resetPasswordApi(user_id, new_password) → POST /api/v1/admin/users/{id}/password", async () => {
    await resetPasswordApi("u-1", "new-pw");
    const [m, u, p] = requestMock.mock.calls[0];
    expect(m).toBe("post");
    expect(u).toBe("/api/v1/admin/users/u-1/password");
    expect(p).toEqual({ data: { new_password: "new-pw" } });
  });

  it("resetPasswordApi 接受不同的 user_id", async () => {
    await resetPasswordApi("u-99", "secret");
    const [, u] = requestMock.mock.calls[0];
    expect(u).toBe("/api/v1/admin/users/u-99/password");
  });
});