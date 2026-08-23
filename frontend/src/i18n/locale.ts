export const LOCALE_STORAGE_KEY = "xz_locale";

export const SUPPORTED_LOCALES = ["zh-CN", "zh-TW", "en-US", "vi-VN"] as const;

export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = "zh-CN";

export function isSupportedLocale(
  value: string | null | undefined
): value is SupportedLocale {
  return Boolean(value && SUPPORTED_LOCALES.includes(value as SupportedLocale));
}

export function detectBrowserLocale(): SupportedLocale {
  const language = navigator.language.toLowerCase();

  if (
    language.startsWith("zh-tw") ||
    language.startsWith("zh-hk") ||
    language.startsWith("zh-mo") ||
    language.startsWith("zh-hant")
  ) {
    return "zh-TW";
  }

  if (language.startsWith("vi")) {
    return "vi-VN";
  }

  if (language.startsWith("en")) {
    return "en-US";
  }

  return DEFAULT_LOCALE;
}

export function getInitialLocale(): SupportedLocale {
  const storedLocale = localStorage.getItem(LOCALE_STORAGE_KEY);
  return isSupportedLocale(storedLocale) ? storedLocale : detectBrowserLocale();
}
