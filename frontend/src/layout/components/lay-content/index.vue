<script setup lang="ts">
import LayFrame from "../lay-frame/index.vue";
import LayFooter from "../lay-footer/index.vue";
import { useGlobal } from "@pureadmin/utils";
import BackTopIcon from "@/assets/svg/back_top.svg?component";
import { h, computed, Transition, defineComponent } from "vue";
import { usePermissionStoreHook } from "@/store/modules/permission";

const { $config } = useGlobal<GlobalPropertiesApi>();

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
        default: () => [this.$slots.default()]
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
                      :include="usePermissionStoreHook().cachePageList"
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
              <div v-else class="not-footer h-[18px]" />
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

.content-scroll {
  height: 100%;
}

.content-wrapper {
  min-height: 0;
}

.content-footer {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}
</style>
