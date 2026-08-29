<script setup lang="ts">
import LayFrame from "../lay-frame/index.vue";
import LayFooter from "../lay-footer/index.vue";
import { useGlobal } from "@pureadmin/utils";
import BackTopIcon from "@/assets/svg/back_top.svg?component";
import {
  h,
  computed,
  nextTick,
  ref,
  Transition,
  defineComponent,
  watch
} from "vue";
import { useRoute } from "vue-router";
import { usePermissionStoreHook } from "@/store/modules/permission";

const { $config } = useGlobal<GlobalPropertiesApi>();

const route = useRoute();
const scrollbarRef = ref();

// 页面滚动发生在这个 el-scrollbar（不是 window），路由切换时它的
// scrollTop 会原样带到新页面（如 system/config 滚到底部再进模板编辑器，
// 编辑器就停在半截）。切换 fullPath 后归零，新页面从顶部开始。
watch(
  () => route.fullPath,
  async () => {
    await nextTick();
    scrollbarRef.value?.setScrollTop(0);
  }
);

const transitions = computed(() => {
  return route => {
    return route.meta.transition;
  };
});

const hideFooter = computed(() => {
  return $config.HideFooter ?? true;
});

const transitionMain = defineComponent({
  props: {
    route: {
      type: undefined,
      required: true
    }
  },
  render() {
    const transitionName =
      transitions.value(this.route)?.name || "fade-transform";
    const enterTransition = transitions.value(this.route)?.enterTransition;
    const leaveTransition = transitions.value(this.route)?.leaveTransition;
    return h(
      Transition,
      {
        name: enterTransition ? "pure-classes-transition" : transitionName,
        enterActiveClass: enterTransition
          ? `animate__animated ${enterTransition}`
          : undefined,
        leaveActiveClass: leaveTransition
          ? `animate__animated ${leaveTransition}`
          : undefined,
        mode: "out-in",
        appear: true
      },
      {
        default: () => [this.$slots.default?.() ?? []]
      }
    );
  }
});
</script>

<template>
  <section class="app-main">
    <router-view>
      <template #default="{ Component, route }">
        <LayFrame :currComp="Component" :currRoute="route">
          <template #default="{ Comp, fullPath, frameInfo }">
            <el-scrollbar
              ref="scrollbarRef"
              class="content-scroll"
              :wrap-style="{
                display: 'flex',
                'flex-wrap': 'wrap',
                'max-width': '100%',
                margin: '0 auto',
                transition: 'all 300ms cubic-bezier(0.4, 0, 0.2, 1)'
              }"
              :view-style="{
                display: 'flex',
                flex: 'auto',
                'min-width': '0',
                overflow: 'visible',
                'flex-direction': 'column'
              }"
            >
              <el-backtop
                title="回到顶部"
                target=".app-main .el-scrollbar__wrap"
              >
                <BackTopIcon />
              </el-backtop>
              <div class="grow content-wrapper">
                <transitionMain :route="route">
                  <div class="main-content">
                    <keep-alive
                      :include="
                        usePermissionStoreHook().cachePageList.filter(
                          (name): name is string => typeof name === 'string'
                        )
                      "
                    >
                      <component
                        :is="Comp"
                        :key="fullPath"
                        v-bind="frameInfo ? { frameInfo } : undefined"
                      />
                    </keep-alive>
                  </div>
                </transitionMain>
              </div>
              <LayFooter v-if="!hideFooter" class="content-footer" />
              <!-- 高度归零：内容视口底已与侧边栏 24px inset 对齐，
                   不再需要额外底部占位（否则内容底线超出侧边栏底线） -->
              <div v-else class="not-footer h-0" />
            </el-scrollbar>
          </template>
        </LayFrame>
      </template>
    </router-view>
  </section>
</template>

<style scoped>
.app-main {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow-x: hidden;
}

/* 底部留出与侧边栏（big-sidebar-container 的 24px inset）一致的安全区：
   收窄滚动视口可视高度，内容卡片底边与侧边栏圆角条底线对齐，
   滚动条也止于同一底线 */
.content-scroll {
  height: calc(100% - 24px);
}

.content-wrapper {
  min-height: 0;
  min-width: 0;
}

.content-footer {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}
</style>
