declare module "vue" {
  export interface GlobalComponents {
    IconifyIconOffline: (typeof import("../src/components/ReIcon"))["IconifyIconOffline"];
    IconifyIconOnline: (typeof import("../src/components/ReIcon"))["IconifyIconOnline"];
    FontIcon: (typeof import("../src/components/ReIcon"))["FontIcon"];
    Auth: (typeof import("../src/components/ReAuth"))["Auth"];
    Perms: (typeof import("../src/components/RePerms"))["Perms"];
    Vue3Signature: (typeof import("vue3-signature"))["default"];
  }
}

declare module "vue" {
  export interface GlobalComponents {
    ElAvatar: (typeof import("element-plus"))["ElAvatar"];
    ElBacktop: (typeof import("element-plus"))["ElBacktop"];
    ElBadge: (typeof import("element-plus"))["ElBadge"];
    ElBreadcrumb: (typeof import("element-plus"))["ElBreadcrumb"];
    ElBreadcrumbItem: (typeof import("element-plus"))["ElBreadcrumbItem"];
    ElButton: (typeof import("element-plus"))["ElButton"];
    ElCard: (typeof import("element-plus"))["ElCard"];
    ElCol: (typeof import("element-plus"))["ElCol"];
    ElColorPicker: (typeof import("element-plus"))["ElColorPicker"];
    ElConfigProvider: (typeof import("element-plus"))["ElConfigProvider"];
    ElDatePicker: (typeof import("element-plus"))["ElDatePicker"];
    ElDialog: (typeof import("element-plus"))["ElDialog"];
    ElDropdown: (typeof import("element-plus"))["ElDropdown"];
    ElDropdownItem: (typeof import("element-plus"))["ElDropdownItem"];
    ElDropdownMenu: (typeof import("element-plus"))["ElDropdownMenu"];
    ElEmpty: (typeof import("element-plus"))["ElEmpty"];
    ElForm: (typeof import("element-plus"))["ElForm"];
    ElFormItem: (typeof import("element-plus"))["ElFormItem"];
    ElIcon: (typeof import("element-plus"))["ElIcon"];
    ElInput: (typeof import("element-plus"))["ElInput"];
    ElInputNumber: (typeof import("element-plus"))["ElInputNumber"];
    ElMenu: (typeof import("element-plus"))["ElMenu"];
    ElMenuItem: (typeof import("element-plus"))["ElMenuItem"];
    ElOption: (typeof import("element-plus"))["ElOption"];
    ElPopconfirm: (typeof import("element-plus"))["ElPopconfirm"];
    ElScrollbar: (typeof import("element-plus"))["ElScrollbar"];
    ElSelect: (typeof import("element-plus"))["ElSelect"];
    ElSpace: (typeof import("element-plus"))["ElSpace"];
    ElSubMenu: (typeof import("element-plus"))["ElSubMenu"];
    ElSwitch: (typeof import("element-plus"))["ElSwitch"];
    ElTabPane: (typeof import("element-plus"))["ElTabPane"];
    ElTabs: (typeof import("element-plus"))["ElTabs"];
    ElTag: (typeof import("element-plus"))["ElTag"];
    ElText: (typeof import("element-plus"))["ElText"];
    ElTooltip: (typeof import("element-plus"))["ElTooltip"];
  }

  interface ComponentCustomProperties {
    $storage: ResponsiveStorage;
    $message: (typeof import("element-plus"))["ElMessage"];
    $notify: (typeof import("element-plus"))["ElNotification"];
    $msgbox: (typeof import("element-plus"))["ElMessageBox"];
    $messageBox: (typeof import("element-plus"))["ElMessageBox"];
    $alert: (typeof import("element-plus"))["ElMessageBox"]["alert"];
    $confirm: (typeof import("element-plus"))["ElMessageBox"]["confirm"];
    $prompt: (typeof import("element-plus"))["ElMessageBox"]["prompt"];
    $loading: (typeof import("element-plus"))["ElLoadingService"];
  }
}

export {};
