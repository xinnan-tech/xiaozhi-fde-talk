/**
 * 访谈路由统一约定。
 *
 * 多个入口（home 卡片点击、App.vue 新建后跳转、未来的侧边栏快捷入口等）
 * 都要按 status 决定去 /interview/:id 还是 /report/:id。若不同入口用不同
 * 条件方向（=== "ended" / !== "ended"），任意一边改了另一边忘了同步，
 * 就会出现"新建完跳错页 / 卡片点错页"类症状且难复现。
 *
 * 全部入口必须走 interviewRouteTarget(item)。要扩展（多 status / 灰度路径）
 * 改这里一处即可。
 */

/** 路由判定用的最小契约：仅依赖 id + status 两个字段，避免与具体 item 类型耦合 */
export type InterviewRouteSource = {
  id: string;
  status: string;
};

/** 已结束的访谈统一去报告页，其它状态去访谈页。 */
export const interviewRouteTarget = (item: InterviewRouteSource): string =>
  item.status === "ended" ? `/report/${item.id}` : `/interview/${item.id}`;
