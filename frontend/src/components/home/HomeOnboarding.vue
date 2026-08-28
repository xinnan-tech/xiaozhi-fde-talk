<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import StepCreateIcon from "@/assets/onboarding/create-interview.svg?component";
import StepStartIcon from "@/assets/onboarding/start-interview.svg?component";
import StepInsightIcon from "@/assets/onboarding/ai-insight.svg?component";
import StepReportIcon from "@/assets/onboarding/generate-report.svg?component";
import RobotAvatar from "@/assets/onboarding/robot-avatar.svg?component";
import BuildingIcon from "@/assets/onboarding/building.svg?component";

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
      <li v-for="(step, index) in steps" :key="step.titleKey" class="step-card">
        <span class="step-badge" aria-hidden="true">{{ index + 1 }}</span>
        <component
          :is="step.icon"
          class="step-illustration"
          aria-hidden="true"
        />
        <h3 class="step-title">{{ t(step.titleKey) }}</h3>
        <p class="step-desc">{{ t(step.descKey) }}</p>
        <span
          v-if="index < steps.length - 1"
          class="step-arrow"
          aria-hidden="true"
        />
      </li>
    </ol>

    <footer class="onboarding-tip">
      <RobotAvatar class="tip-avatar" aria-hidden="true" />
      <div class="tip-bubble">
        <p class="tip-text">
          <strong class="tip-label">{{ t("home.guide.tip_title") }}</strong
          >{{ t("home.guide.tip_pre")
          }}<span class="tip-button"
            >+&nbsp;{{ t("home.create_interview") }}</span
          >{{ t("home.guide.tip_post") }}
        </p>
      </div>
      <BuildingIcon class="tip-building" aria-hidden="true" />
    </footer>
  </section>
</template>

<style lang="scss" scoped>
.home-onboarding {
  padding: 40px 32px 36px;
  background: #fff;
  border: 1px solid rgb(255 255 255 / 65%);
  border-radius: 20px;
  box-shadow: 0 4px 20px rgb(0 0 0 / 8%);
}

.onboarding-head {
  margin-bottom: 36px;
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

.onboarding-steps {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.step-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 16px 20px;
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

/* 步骤间虚线箭头：只在 4 列布局展示，指向插画行（top ≈ 卡片上内边距 + 插画半高） */
.step-arrow {
  position: absolute;
  top: 64px;
  right: -20px;
  width: 20px;
  border-top: 2px dashed #b9c9ee;
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
  border-left: 6px solid #b9c9ee;
}

.onboarding-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 32px;
}

.tip-avatar {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  margin-right: -14px;
}

.tip-bubble {
  max-width: 660px;
  padding: 14px 28px;
  background: #eef3ff;
  border: 1px solid #cdd9f6;
  border-radius: 20px;
}

.tip-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: #4b5b76;
  text-align: center;
}

.tip-label {
  font-weight: 600;
}

.tip-button {
  font-weight: 600;
  color: #409eff;
  white-space: nowrap;
}

.tip-building {
  flex-shrink: 0;
  width: 64px;
  height: 64px;
  margin-left: 12px;
  transform: translateY(6px);
}

/* 容器断点与 views/home/index.vue 保持一致（container 是 .home） */
@container (width < 1250px) {
  .onboarding-steps {
    gap: 16px;
  }

  .step-arrow {
    right: -16px;
    width: 16px;
  }
}

@container (width < 640px) {
  .home-onboarding {
    padding: 28px 16px 24px;
  }

  .onboarding-head {
    margin-bottom: 24px;
  }

  .tip-avatar {
    width: 44px;
    height: 44px;
  }

  .tip-bubble {
    padding: 12px 18px;
  }

  .tip-building {
    display: none;
  }
}
</style>
