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
    rank: 2,
    roles: ["admin"]
  },
  children: [
    {
      path: "/system/config",
      name: "SystemConfig",
      component: () => import("@/views/system/index.vue"),
      meta: {
        title: "系统配置",
        titleKey: "menu.system",
        roles: ["admin"]
        // keepAlive: true // 开启缓存
      }
    },
    {
      path: "/system/templates/new",
      name: "SystemTemplateNew",
      component: () => import("@/views/system/templates/edit.vue"),
      meta: {
        title: "新建模板",
        titleKey: "system.template.editor_title_new",
        roles: ["admin"],
        showLink: false
      }
    },
    {
      path: "/system/templates/edit/:id",
      name: "SystemTemplateEdit",
      component: () => import("@/views/system/templates/edit.vue"),
      meta: {
        title: "编辑模板",
        titleKey: "system.template.editor_title_edit",
        roles: ["admin"],
        showLink: false
      }
    }
  ]
} satisfies RouteConfigsTable;
