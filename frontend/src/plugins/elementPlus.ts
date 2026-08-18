import type { App, Component } from "vue";
import {
  ElAvatar,
  ElBacktop,
  ElBadge,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElButton,
  ElCard,
  ElCol,
  ElColorPicker,
  ElConfigProvider,
  ElDatePicker,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElMenu,
  ElMenuItem,
  ElMessage,
  ElMessageBox,
  ElNotification,
  ElOption,
  ElPopconfirm,
  ElScrollbar,
  ElSelect,
  ElSpace,
  ElSubMenu,
  ElSwitch,
  ElTabPane,
  ElTabs,
  ElTag,
  ElText,
  ElTooltip,
  ElCheckbox,
  ElSkeleton,
  ElSkeletonItem,
  ElDrawer
} from "element-plus";

const components: Component[] = [
  ElAvatar,
  ElBacktop,
  ElBadge,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElButton,
  ElCard,
  ElCol,
  ElColorPicker,
  ElConfigProvider,
  ElDatePicker,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPopconfirm,
  ElScrollbar,
  ElSelect,
  ElSpace,
  ElSubMenu,
  ElSwitch,
  ElTabPane,
  ElTabs,
  ElTag,
  ElText,
  ElTooltip,
  ElCheckbox,
  ElSkeleton,
  ElSkeletonItem,
  ElDrawer
];

const plugins = [ElLoading, ElMessage, ElMessageBox, ElNotification];

/** 按需引入 Element Plus，仅注册当前项目实际使用的组件和插件。 */
export function useElementPlus(app: App) {
  components.forEach(component => {
    app.component(component.name, component);
  });

  plugins.forEach(plugin => {
    app.use(plugin);
  });
}
