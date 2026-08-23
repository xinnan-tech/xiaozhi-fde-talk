const Layout = () => import("@/layout/index.vue");

export default {
  path: "/about",
  name: "About",
  component: Layout,
  meta: {
    icon: "tabler:info-circle-filled",
    title: "关于",
    titleKey: "menu.about",
    rank: 99
  },
  children: [
    {
      path: "/about",
      name: "AboutPage",
      component: () => import("@/views/about/index.vue"),
      meta: {
        title: "关于",
        titleKey: "menu.about"
      }
    }
  ]
} satisfies RouteConfigsTable;