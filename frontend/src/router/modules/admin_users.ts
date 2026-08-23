const Layout = () => import("@/layout/index.vue");

export default {
  path: "/admin/users",
  name: "AdminUsers",
  component: Layout,
  meta: {
    icon: "tabler:users",
    title: "用户管理",
    titleKey: "menu.users",
    rank: 3,
    roles: ["admin"]
  },
  children: [
    {
      path: "",
      name: "AdminUsersList",
      component: () => import("@/views/admin/users/index.vue"),
      meta: {
        title: "用户管理",
        titleKey: "menu.users",
        roles: ["admin"]
      }
    }
  ]
} satisfies RouteConfigsTable;
