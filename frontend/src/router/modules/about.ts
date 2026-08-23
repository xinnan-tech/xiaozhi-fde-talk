export default {
  path: "/about",
  name: "About",
  component: () => import("@/views/about/index.vue"),
  meta: {
    icon: "tabler:info-circle-filled",
    title: "关于",
    titleKey: "menu.about",
    rank: 99
  }
} satisfies RouteConfigsTable;
