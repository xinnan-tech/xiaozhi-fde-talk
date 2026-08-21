const Layout = () => import("@/layout/index.vue");

export default {
  path: "/system",
  name: "System",
  component: Layout,
  redirect: "/system/config",
  meta: {
    icon: "tabler:settings-filled",
    title: "系统配置",
    titleKey: "menu.system",
    rank: 2
  },
  children: [
    {
      path: "/system/config",
      name: "SystemConfig",
      component: () => import("@/views/system/index.vue"),
      meta: {
        title: "系统配置",
        titleKey: "menu.system"
        // keepAlive: true // 开启缓存
      }
    }
  ]
} satisfies RouteConfigsTable;
