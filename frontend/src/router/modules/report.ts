const Layout = () => import("@/layout/index.vue");

export default {
  path: "/reports",
  name: "Reports",
  component: Layout,
  redirect: "/report",
  meta: {
    icon: "tabler:file-text",
    title: "访谈报告",
    rank: 2,
    showLink: false
  },
  children: [
    {
      path: "/report",
      name: "Report",
      component: () => import("@/views/report/index.vue"),
      meta: {
        title: "访谈报告",
        showLink: false
      }
    }
  ]
} satisfies RouteConfigsTable;
