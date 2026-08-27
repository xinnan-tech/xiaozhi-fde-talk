<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch
} from "vue";
import type { SelectOption } from "./types";
import SelectIcon from "~icons/ep/select";

defineOptions({
  name: "BaseSelect"
});

const props = withDefaults(
  defineProps<{
    options?: SelectOption[];
    modelValue?: string | number;
    /**
     * 触发方式: hover鼠标移入 click点击触发
     */
    trigger?: "hover" | "click";
    /**
     * 是否保留选中状态
     */
    showSelectedState?: boolean;
    /**
     * 是否显示选中图标
     */
    showSelectedIcon?: boolean;
    /**
     * 是否显示前缀图标
     */
    showPrefixIcon?: boolean;
  }>(),
  {
    options: () => [],
    modelValue: undefined,
    trigger: "hover",
    showSelectedState: false,
    showSelectedIcon: true,
    showPrefixIcon: true
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string | number];
  change: [option: SelectOption];
}>();

const selectRef = ref<HTMLElement>();
const menuRef = ref<HTMLElement>();
const isHovering = ref(false);
const isClicked = ref(false);
const hoverCloseTimer = ref<number>();
const menuStyle = ref<{
  top: string;
  left: string;
  "--arrow-left": string;
}>({
  top: "0px",
  left: "0px",
  "--arrow-left": "18px"
});

const isOpen = computed(() =>
  props.trigger === "click" ? isClicked.value : isHovering.value
);

const toggle = () => {
  isClicked.value = !isClicked.value;
};

const handleTriggerClick = () => {
  if (props.trigger === "click") toggle();
};

const handleMouseEnter = () => {
  if (hoverCloseTimer.value) window.clearTimeout(hoverCloseTimer.value);
  if (props.trigger === "hover") isHovering.value = true;
};

const handleMouseLeave = () => {
  if (props.trigger !== "hover") return;

  hoverCloseTimer.value = window.setTimeout(() => {
    isHovering.value = false;
  }, 80);
};

const handleMenuEnter = () => {
  if (hoverCloseTimer.value) window.clearTimeout(hoverCloseTimer.value);
  if (props.trigger === "hover") isHovering.value = true;
};

const handleMenuLeave = () => {
  if (props.trigger === "hover") isHovering.value = false;
};

const handleFocusIn = () => {
  if (props.trigger === "click") isClicked.value = true;
};

const close = () => {
  isHovering.value = false;
  isClicked.value = false;
};

const select = (option: SelectOption) => {
  if (option.disabled) return;
  if (props.showSelectedState && option.value === props.modelValue) {
    close();
    return;
  }
  emit("update:modelValue", option.value);
  emit("change", option);
  close();
};

const handleDocumentClick = (event: MouseEvent) => {
  const target = event.target as Node;
  const inTrigger = selectRef.value?.contains(target);
  const inMenu = menuRef.value?.contains(target);

  if (!inTrigger && !inMenu) close();
};

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === "Escape") close();
};

const updateMenuPosition = () => {
  const trigger = selectRef.value;
  if (!trigger) return;

  const rect = trigger.getBoundingClientRect();
  const menuWidth = menuRef.value?.offsetWidth ?? 156;
  const gap = 8;
  const left = Math.min(rect.left, window.innerWidth - menuWidth - gap);
  const menuLeft = Math.max(gap, left);
  const arrowLeft = Math.min(
    Math.max(rect.left + rect.width / 2 - menuLeft - 5, 12),
    menuWidth - 22
  );

  menuStyle.value = {
    top: `${rect.bottom + gap}px`,
    left: `${menuLeft}px`,
    "--arrow-left": `${arrowLeft}px`
  };
};

const handleViewportChange = () => {
  if (isOpen.value) updateMenuPosition();
};

watch(isOpen, async open => {
  if (!open) {
    window.removeEventListener("resize", handleViewportChange);
    window.removeEventListener("scroll", handleViewportChange, true);
    return;
  }

  await nextTick();
  updateMenuPosition();
  window.addEventListener("resize", handleViewportChange);
  window.addEventListener("scroll", handleViewportChange, true);
});

onMounted(() => {
  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("keydown", handleKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", handleDocumentClick);
  document.removeEventListener("keydown", handleKeydown);
  window.removeEventListener("resize", handleViewportChange);
  window.removeEventListener("scroll", handleViewportChange, true);
  if (hoverCloseTimer.value) window.clearTimeout(hoverCloseTimer.value);
});
</script>

<template>
  <div
    ref="selectRef"
    class="base-select"
    :class="{ 'is-open': isOpen }"
    @click.stop
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
    @focusin="handleFocusIn"
  >
    <div class="base-select-trigger" @click="handleTriggerClick">
      <slot />
    </div>

    <Teleport to="body">
      <div
        v-if="options.length"
        ref="menuRef"
        class="base-select-menu"
        :class="{ 'is-open': isOpen }"
        role="listbox"
        :style="menuStyle"
        @mouseenter="handleMenuEnter"
        @mouseleave="handleMenuLeave"
        @click.stop
      >
        <button
          v-for="option in options"
          :key="option.value"
          type="button"
          role="option"
          :aria-selected="option.value === modelValue"
          :disabled="option.disabled"
          class="base-select-option"
          :class="{
            'is-selected': showSelectedState && option.value === modelValue
          }"
          @click="select(option)"
        >
          <slot name="option" :option="option">
            <span class="option-content">
              <span
                v-if="showPrefixIcon && option.icon"
                class="option-prefix-icon"
              >
                <component :is="option.icon" />
              </span>
              <span class="option-label">{{ option.label }}</span>
            </span>
            <SelectIcon
              v-if="
                showSelectedState &&
                showSelectedIcon &&
                option.value === modelValue
              "
              class="option-selected-icon"
            />
          </slot>
        </button>
      </div>
    </Teleport>
  </div>
</template>

<style scoped lang="scss">
.base-select {
  position: relative;
  display: inline-block;
  vertical-align: middle;
}

.base-select-trigger {
  cursor: pointer;
}

.base-select-menu {
  position: fixed;
  z-index: 1000;
  min-width: 128px;
  padding: 6px;
  visibility: hidden;
  background: rgb(255 255 255 / 96%);
  border: 1px solid rgb(223 231 240 / 90%);
  border-radius: 10px;
  box-shadow:
    0 4px 10px rgb(31 47 86 / 8%),
    0 16px 32px rgb(31 47 86 / 18%);
  opacity: 0;
  /* 预留顶部箭头区域，避免展开动画将箭头一起裁掉。 */
  clip-path: inset(-8px 0 100% 0 round 10px);
  transform: translateY(-4px);
  transform-origin: top left;
  will-change: clip-path, opacity, transform;
  transition:
    clip-path 0.26s cubic-bezier(0.2, 0.8, 0.2, 1),
    opacity 0.18s ease,
    transform 0.26s cubic-bezier(0.2, 0.8, 0.2, 1),
    visibility 0s linear 0.26s;

  &::before {
    position: absolute;
    top: -6px;
    left: var(--arrow-left);
    width: 10px;
    height: 10px;
    content: "";
    background: #fff;
    border-top: 1px solid rgb(223 231 240 / 90%);
    border-left: 1px solid rgb(223 231 240 / 90%);
    transform: rotate(45deg);
  }

  &.is-open {
    visibility: visible;
    opacity: 1;
    clip-path: inset(-8px 0 0 0 round 10px);
    transform: translateY(0);
    transition:
      clip-path 0.26s cubic-bezier(0.2, 0.8, 0.2, 1),
      opacity 0.18s ease,
      transform 0.26s cubic-bezier(0.2, 0.8, 0.2, 1),
      visibility 0s;
  }
}

.base-select-option {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  min-height: 36px;
  box-sizing: border-box;
  padding: 8px 10px;
  overflow: hidden;
  align-items: center;
  gap: 6px;
  font: inherit;
  font-size: 13px;
  line-height: 20px;
  color: #334155;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 6px;

  &:hover,
  &:focus-visible {
    background: #f1f5f9;
    outline: none;
  }

  &.is-selected {
    color: #409eff;
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .option-label,
  .option-icon {
    flex-shrink: 0;
  }

  .option-content {
    display: inline-flex;
    min-width: 0;
    flex: 1 1 auto;
    align-items: center;
    gap: 6px;
  }

  .option-label {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .option-prefix-icon {
    align-self: center;
    display: inline-flex;
    width: 14px;
    height: 20px;
    flex: 0 0 14px;
    align-items: center;
    justify-content: center;

    :deep(svg) {
      display: block;
      width: 14px;
      height: 14px;
    }
  }

  .option-selected-icon {
    display: block;
    position: absolute;
    top: 50%;
    right: 10px;
    flex-shrink: 0;
    transform: translateY(-50%);
  }
}
</style>
