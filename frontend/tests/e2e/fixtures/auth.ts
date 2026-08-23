// 管理员账号：从环境变量读，CI 与本地各自覆盖；默认值与
// backend/tests/conftest.py::_TEST_ADMIN_PASSWORD 保持一致（仅供本地默认）。
// CI 必须显式注入 E2E_ADMIN_USER / E2E_ADMIN_PASSWORD，避免硬编码密钥泄漏进仓库。
const FALLBACK_USER = "admin"
const FALLBACK_PWD = "longenough1234"

export const ADMIN_USER = process.env.E2E_ADMIN_USER || FALLBACK_USER
export const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || FALLBACK_PWD