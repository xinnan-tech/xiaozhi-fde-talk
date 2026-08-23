import { createI18n } from "vue-i18n";
import enUS from "@/locales/en-US.json";
import zhCN from "@/locales/zh-CN.json";
import zhTW from "@/locales/zh-TW.json";
import viVN from "@/locales/vi-VN.json";
import {
  DEFAULT_LOCALE,
  getInitialLocale,
  LOCALE_STORAGE_KEY,
  type SupportedLocale
} from "./locale";

export {
  DEFAULT_LOCALE,
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  isSupportedLocale,
  type SupportedLocale
} from "./locale";

export const i18n = createI18n({
  legacy: false,
  locale: getInitialLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    "zh-CN": zhCN,
    "zh-TW": zhTW,
    "en-US": enUS,
    "vi-VN": viVN
  },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV
});

export function getCurrentLocale(): SupportedLocale {
  return i18n.global.locale.value as SupportedLocale;
}

export function setLocale(locale: SupportedLocale): void {
  i18n.global.locale.value = locale;
  localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  document.documentElement.lang = locale;
}
