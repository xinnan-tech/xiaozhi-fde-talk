<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import StepCreateIcon from "@/assets/onboarding/create-interview.svg?component";
import StepStartIcon from "@/assets/onboarding/start-interview.svg?component";
import StepInsightIcon from "@/assets/onboarding/ai-insight.svg?component";
import StepReportIcon from "@/assets/onboarding/generate-report.svg?component";

defineOptions({
  name: "HomeOnboarding"
});

const { t } = useI18n();

const steps = computed(() => [
  {
    icon: StepCreateIcon,
    titleKey: "home.guide.step1.title",
    descKey: "home.guide.step1.desc"
  },
  {
    icon: StepStartIcon,
    titleKey: "home.guide.step2.title",
    descKey: "home.guide.step2.desc"
  },
  {
    icon: StepInsightIcon,
    titleKey: "home.guide.step3.title",
    descKey: "home.guide.step3.desc"
  },
  {
    icon: StepReportIcon,
    titleKey: "home.guide.step4.title",
    descKey: "home.guide.step4.desc"
  }
]);
</script>

<template>
  <section class="home-onboarding" :aria-label="t('home.guide.title')">
    <header class="onboarding-head">
      <h2 class="onboarding-title">{{ t("home.guide.title") }}</h2>
      <p class="onboarding-subtitle">{{ t("home.guide.subtitle") }}</p>
    </header>

    <ol class="onboarding-steps">
      <template v-for="(step, index) in steps" :key="step.titleKey">
        <li class="step-card">
          <span class="step-badge" aria-hidden="true">{{ index + 1 }}</span>
          <component
            :is="step.icon"
            class="step-illustration"
            aria-hidden="true"
          />
          <h3 class="step-title">{{ t(step.titleKey) }}</h3>
          <p class="step-desc">{{ t(step.descKey) }}</p>
        </li>
        <!-- 箭头槽位：flex:1 与其余槽位均分卡片间剩余空间，箭头长度自适应 -->
        <li
          v-if="index < steps.length - 1"
          class="step-arrow-slot"
          aria-hidden="true"
        >
          <span class="step-arrow" />
        </li>
      </template>
    </ol>
  </section>
</template>

<style lang="scss" scoped>
/* 自动高度：撑满 .home 剩余空间；负 margin 抵消 .home 的 padding-bottom(24px)，
   使面板底边与侧边栏圆角条底线（视口底 -24px）齐平 */
/* 紧凑间距：笔记本可视高（~775px）下整块面板需完整放下，
   压缩垂直留白约 64px（含 home 页上方区块的同步收紧） */
.home-onboarding {
  margin-bottom: -24px;
  padding: 28px 32px 36px;
  background: rgba(255, 255, 255, 0.6);
  border: 1px solid rgb(255 255 255 / 65%);
  border-radius: 20px;
  box-shadow: 0 4px 20px rgb(0 0 0 / 8%);
}

.onboarding-head {
  margin-bottom: 24px;
  text-align: center;
}

.onboarding-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #1a1a1a;
}

.onboarding-subtitle {
  margin: 8px 0 0;
  font-size: 14px;
  color: #999;
}

/* 原型图：四张窄卡片，卡片间的剩余空间均分给箭头槽位；
   steps 区弹性伸展，卡片区在剩余高度里垂直居中 */
.onboarding-steps {
  display: flex;
  flex: 1;
  align-items: center;
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-card {
  position: relative;
  flex: 0 1 200px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 16px 16px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgb(0 0 0 / 6%);
}

.step-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: #409eff;
  border-radius: 50%;
}

.step-illustration {
  width: 88px;
  height: 88px;
  margin-top: 10px;
}

.step-title {
  margin: 12px 0 0;
  font-size: 16px;
  font-weight: 600;
  color: #1a1a1a;
  text-align: center;
}

.step-desc {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #666;
  text-align: center;
}

/* 箭头槽位：与其它槽位均分间隙，垂直居中对齐卡片中线 */
.step-arrow-slot {
  position: relative;
  flex: 1 1 0;
  align-self: center;
  min-width: 0;
  height: 0;
  list-style: none;
}

/* 步骤间虚线箭头：横跨槽位（两头各留 8px 呼吸），从一张卡片中部指向下一张中部 */
.step-arrow {
  position: absolute;
  right: 8px;
  left: 8px;
  top: -1px;
  border-top: 2px dashed #409eff;
}

.step-arrow::after {
  position: absolute;
  top: -5px;
  right: -2px;
  width: 0;
  height: 0;
  content: "";
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
  border-left: 6px solid #409eff;
}

/* 容器断点与 views/home/index.vue 保持一致（container 是 .home）；
   间隙由箭头槽位自适应均分，无需按断点调 gap */
@container (width < 950px) {
  .onboarding-steps {
    flex-wrap: wrap;
    gap: 16px;
  }

  .step-card {
    flex: 1 1 calc(50% - 8px);
  }

  /* 两列布局：箭头失去指向意义，隐藏 */
  .step-arrow-slot {
    display: none;
  }
}

@container (width < 640px) {
  .home-onboarding {
    padding: 28px 16px 24px;
  }

  .onboarding-head {
    margin-bottom: 24px;
  }

  .step-card {
    flex-basis: 100%;
  }
}
</style>
