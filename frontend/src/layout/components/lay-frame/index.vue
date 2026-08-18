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
const normalComp = computed(() =>
  !keep.value ? markRaw(props.currComp) : null
);

watch(
  () => props.currRoute.fullPath,
  path => {
    if (keep.value && !MAP.has(path)) {
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
