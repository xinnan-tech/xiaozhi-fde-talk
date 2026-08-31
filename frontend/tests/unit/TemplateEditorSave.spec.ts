import { mount, flushPromises } from "@vue/test-utils";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { createI18n } from "vue-i18n";
import { createRouter, createMemoryHistory } from "vue-router";

// 顶层 vi.mock 必须在 import 业务模块之前——vitest 会自动 hoist，
// 但这里留出显眼注释便于后人维护。
vi.mock("@/api/interview", () => ({
  getInterviewTemplateDetailApi: vi.fn().mockResolvedValue({
    id: "tpl-1",
    version: "1",
    icon_url: "",
    icon_alt: "📋",
    name: "示例",
    session: {
      name: "",
      goal: "",
      base_fields: [],
      setup: { intro: "", extract_to: [], required: [] },
      title_default: "",
      goal_default: ""
    },
    coaching: { playbook: "", must_ask: [] },
    report: { doc: "" },
    safety: []
  })
}));
vi.mock("@/api/admin", () => ({
  createAdminTemplateApi: vi.fn(),
  updateAdminTemplateApi: vi.fn().mockResolvedValue({
    id: "tpl-1",
    version: "1",
    icon_url: "",
    icon_alt: "📋",
    name: "示例",
    session: {
      name: "",
      goal: "",
      base_fields: [],
      setup: { intro: "", extract_to: [], required: [] },
      title_default: "",
      goal_default: ""
    },
    coaching: { playbook: "", must_ask: [] },
    report: { doc: "" },
    safety: []
  }),
  generateAdminTemplateApi: vi.fn()
}));

/** JsonMode 真组件要 CodeMirror，在 happy-dom 下 import 都不稳；
 *  整体 mock 掉这个模块（@vue/test-utils 的 stubs 只挡渲染层，
 *  顶层的 `import ... from "codemirror"` 仍会跑），换成可控 stub：
 *  通过「写 stub.vm.nextCode 后 vm.$emit("update:code", ...)」
 *  即可让父组件收到任意文本。vi.mock 工厂会被 hoist 到文件顶端，
 *  所以 stub 对象必须用 vi.hoisted 拿出来——直接在顶层 const 声明
 *  会让工厂在它赋值之前就被调用。 */
const { jsonModeStub } = vi.hoisted(() => ({
  jsonModeStub: {
    name: "TemplateEditorJson",
    props: ["code"],
    emits: ["update:code"],
    template: `<button class="json-mode-stub" type="button" />`
  }
}));
vi.mock("@/components/template-editor/JsonMode.vue", () => ({
  default: jsonModeStub
}));

// import 放在 mock 之后。
import SystemTemplateEdit from "@/views/system/templates/edit.vue";
import { ElMessage } from "element-plus";

// 仅装进测试用到的 i18n key，避免 loading 完整 locale tree。
const i18n = createI18n({
  legacy: false,
  locale: "zh-CN",
  messages: {
    "zh-CN": {
      "system.template.editor_title_edit": "编辑模板",
      "system.template.section_base": "基础信息",
      "system.template.section_session": "会话",
      "system.template.section_coaching": "追问清单",
      "system.template.section_report": "报告",
      "system.template.mode_form": "表单",
      "system.template.mode_json": "JSON",
      "system.template.cancel": "取消",
      "system.template.save": "保存",
      "system.template.json_errors": "JSON 错误",
      "system.template.json_apply_blocked": "Fix JSON errors before switching back to form mode",
      "system.template.save_json_parse_failed": "保存失败：JSON 解析错误（第 {line} 行 第 {column} 列）：{message}",
      "system.template.save_json_struct_invalid": "保存失败：JSON 结构校验未通过：{details}"
    }
  }
});

/** 各 section 占位组件，避免引入它们的依赖。 */
const sectionStub = { template: "<div />" };

/** 当前测试用例挂在 document.body 上的 wrapper——afterEach 负责 unmount 并清 DOM，
 *  否则上一个用例残留的 save 按钮会接住新用例的 click 事件，导致 save 被双调用
 *  （症状就是 warningSpy 拿到 2 个不同分支的 toast）。 */
let activeWrapper: ReturnType<typeof mount> | null = null;

function mountEditor(routePath: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/system/templates/edit/:id",
        name: "SystemTemplateEdit",
        component: SystemTemplateEdit
      },
      {
        path: "/system/templates/new",
        name: "SystemTemplateNew",
        component: SystemTemplateEdit
      }
    ]
  });
  router.push(routePath);
  const w = mount(SystemTemplateEdit, {
    global: {
      plugins: [i18n, router],
      stubs: {
        AiGenerateSection: sectionStub,
        BaseInfoSection: sectionStub,
        SessionSection: sectionStub,
        CoachingSection: sectionStub,
        ReportSection: sectionStub,
        JsonMode: jsonModeStub
      }
    },
    attachTo: document.body
  });
  activeWrapper = w;
  return w;
}

describe("SystemTemplateEdit · JSON 模式下 Save 报错文案", () => {
  let warningSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    setActivePinia(createPinia());
    // vi.spyOn 不会自动清理；新一轮 spyOn 会替换方法本体，新 spy 的 mock.calls 是空的。
    warningSpy = vi.spyOn(ElMessage, "warning").mockImplementation(() => {});
    // 清空 document.body：旧 wrapper 不清掉会让 click 串到上一个用例的 save 按钮。
    document.body.innerHTML = "";
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.restoreAllMocks();
  });

  it("JSON 语法错误时 Save 弹「保存失败：JSON 解析错误（行 N 列 N）…」而非切回 form 提示", async () => {
    const wrapper = mountEditor("/system/templates/edit/tpl-1");
    await flushPromises(); // onMounted 拉详情

    // 切到 JSON 模式——直接点 data-testid="mode-json" 容器（el-radio-button 包 label）
    const jsonTab = wrapper.find('[data-testid="mode-json"]');
    expect(jsonTab.exists()).toBe(true);
    await jsonTab.trigger("click");
    await flushPromises();

    // 灌一份故意写错的 JSON：触发 parseJsonSafe 走到 syntaxError 分支
    const jsonStub = wrapper.findComponent({ name: "TemplateEditorJson" });
    expect(jsonStub.exists()).toBe(true);
    await jsonStub.vm.$emit("update:code", "{invalid json: hello}");
    await flushPromises();

    // 点 Save
    const saveBtn = wrapper.find('[data-testid="tpl-save"]');
    expect(saveBtn.exists()).toBe(true);
    await saveBtn.trigger("click");
    await flushPromises();

    expect(warningSpy).toHaveBeenCalledTimes(1);
    const msg = warningSpy.mock.calls[0][0];
    // 必须命中「保存失败」字样 + 包含真实行/列定位信息
    expect(msg).toMatch(/^保存失败：JSON 解析错误/);
    expect(msg).toMatch(/第 \d+ 行 第 \d+ 列/);
    // 不能再用「切回 form」的旧文案（issue #142 的核心 bug）
    expect(msg).not.toMatch(/switching back to form mode/);
    expect(msg).not.toMatch(/切回表单模式/);

    // 语法错误时 JSON 没并入 tpl，update API 不应触发
    const { updateAdminTemplateApi } = await import("@/api/admin");
    expect(updateAdminTemplateApi).not.toHaveBeenCalled();
  });

  it("JSON 结构校验失败时 Save 弹「保存失败：JSON 结构校验未通过：…」", async () => {
    const wrapper = mountEditor("/system/templates/edit/tpl-1");
    await flushPromises();

    const jsonTab = wrapper.find('[data-testid="mode-json"]');
    expect(jsonTab.exists()).toBe(true);
    await jsonTab.trigger("click");
    await flushPromises();

    // 合法 JSON 但根节点是数组 → validateTemplateStructure 报错
    const jsonStub = wrapper.findComponent({ name: "TemplateEditorJson" });
    await jsonStub.vm.$emit("update:code", "[1,2,3]");
    await flushPromises();

    await wrapper.find('[data-testid="tpl-save"]').trigger("click");
    await flushPromises();

    expect(warningSpy).toHaveBeenCalledTimes(1);
    const msg = warningSpy.mock.calls[0][0];
    expect(msg).toMatch(/^保存失败：JSON 结构校验未通过：/);
    // 结构错误应带字段路径，至少含一处「$：根节点必须是对象」
    expect(msg).toMatch(/根节点必须是对象|session\.base_fields/);
  });
});