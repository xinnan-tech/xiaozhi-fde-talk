export default {
  path: "/admin/users",
  name: "AdminUsers",
  component: () => import("@/views/admin/users/index.vue"),
  meta: {
    icon: "tabler:users",
    title: "用户管理",
    titleKey: "menu.users",
    rank: 3,
    roles: ["admin"],
    // 管理员关闭 allow_registration 时，「用户管理」菜单直接不渲染；
    // 重置密码入口随之消失，关闭注册后管理员也无需再管账号。
    requiresRegistrationAllowed: true
  }
} satisfies RouteConfigsTable;
