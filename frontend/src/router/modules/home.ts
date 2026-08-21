const Layout = () => import("@/layout/index.vue");

export default {
  path: "/",
  name: "InterviewHome",
  component: Layout,
  redirect: "/home",
  meta: {
    icon: "tabler:message-chatbot-filled",
    title: "访谈主页",
    titleKey: "menu.home",
    rank: 0
  },
  children: [
    {
      path: "/home",
      name: "Home",
      component: () => import("@/views/home/index.vue"),
      meta: {
        title: "访谈主页",
        titleKey: "menu.home"
      }
    }
  ]
} satisfies RouteConfigsTable;
