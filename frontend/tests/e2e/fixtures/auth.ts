// 管理员账号：从环境变量读，CI 与本地各自覆盖；默认值与
// backend/tests/conftest.py::_TEST_ADMIN_PASSWORD 保持一致（仅供本地默认）。
// fallback 密码必须 ≥ 8 字符 + ≥ 3 类字符（小写/大写/数字/符号），才能过
// app/core/password_policy.py 的强度校验（否则 /api/v1/auth/register 返 400）。
// CI 仍推荐用 E2E_ADMIN_PASSWORD 注入不同的测试密码，避免共用同一密钥。
const FALLBACK_USER = "admin"
const FALLBACK_PWD = "AdminTest123!@#"

export const ADMIN_USER = process.env.E2E_ADMIN_USER || FALLBACK_USER
export const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || FALLBACK_PWD