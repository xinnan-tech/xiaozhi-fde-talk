<script setup lang="ts">
import { useMultiFrame } from "@/layout/hooks/useMultiFrame";
import { type Component, shallowRef, watch, computed, markRaw } from "vue";
import { type RouteLocationNormalizedLoaded } from "vue-router";

const props = defineProps<{
  currRoute: RouteLocationNormalizedLoaded;
  currComp: Component;
}>();

const compList = shallowRef<Array<[string, Component]>>([]);
const { setMap, getMap, MAP } = useMultiFrame();

const keep = computed(() => {
  return props.currRoute.meta?.keepAlive && !!props.currRoute.meta?.frameSrc;
});
// 避免重新渲染 LayFrame
// 守 props.currComp：路由切换瞬间或 keep-alive 缓存命中时，<router-view> 的
// slot prop Component 可能短暂为 undefined；markRaw(undefined) 内部 def(value, ...)
// 会触发 hasOwnProperty.call(undefined, ...) → "Cannot convert undefined or null
// to object"，整页直接空白且后续路由都打不开。null 兜底让 <component :is="null">
// 静默跳过渲染，由 keep-alive / transition 兜底下一帧渲染正确组件。
const normalComp = computed(() =>
  !keep.value && props.currComp ? markRaw(props.currComp) : null
);

watch(
  () => props.currRoute.fullPath,
  path => {
    if (keep.value && props.currComp && !MAP.has(path)) {
      setMap(path, props.currComp);
    }

    if (MAP.size > 0) {
      compList.value = getMap();
    }
  },
  {
    immediate: true
  }
);
</script>
<template>
  <template v-for="[fullPath, Comp] in compList" :key="fullPath">
    <div v-show="fullPath === currRoute.fullPath" class="w-full h-full">
      <slot
        :fullPath="fullPath"
        :Comp="Comp"
        :frameInfo="{ frameSrc: currRoute.meta?.frameSrc, fullPath }"
      />
    </div>
  </template>
  <div v-show="!keep" class="w-full h-full">
    <slot
      :Comp="normalComp"
      :fullPath="currRoute.fullPath"
      :frameInfo="undefined"
    />
  </div>
</template>
