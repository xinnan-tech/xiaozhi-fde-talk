import { defineFakeRoute } from "vite-plugin-fake-server/client";

const mockInterviewList = [
  {
    id: 1,
    title: "产品体验访谈",
    status: "进行中",
    statusType: "info",
    interviewee: "张三",
    type: "深度访谈",
    recentTime: "2小时前",
    pendingCount: 5,
    coveredCount: 12,
    askedCount: 8
  },
  {
    id: 2,
    title: "功能反馈访谈",
    status: "已结束",
    statusType: "success",
    interviewee: "李四",
    type: "焦点小组",
    recentTime: "1天前",
    pendingCount: 0,
    coveredCount: 20,
    askedCount: 18
  },
  {
    id: 3,
    title: "用户调研访谈",
    status: "进行中",
    statusType: "info",
    interviewee: "王五",
    type: "深度访谈",
    recentTime: "30分钟前",
    pendingCount: 3,
    coveredCount: 8,
    askedCount: 5
  }
];

export default defineFakeRoute([
  {
    url: "/interview-statistics",
    method: "get",
    timeout: 1500,
    response: () => {
      return {
        success: true,
        data: {
          inProgress: 12, // 进行中‑访谈数量
          weekFinish: 2, // 本周完成‑访谈数量
          assistDiscovery: 10, // 辅助发现‑问题数量
          interviewCoverage: 32 // 访谈覆盖‑访谈数量
        }
      };
    }
  },
  {
    url: "/interview-list",
    method: "get",
    timeout: 1800,
    response: () => {
      return {
        success: true,
        data: mockInterviewList
      };
    }
  }
]);
