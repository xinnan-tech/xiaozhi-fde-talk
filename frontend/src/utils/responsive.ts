import type { App } from "vue";
import Storage from "responsive-storage";
import { responsiveStorageNameSpace } from "@/config";

export const injectResponsiveStorage = (app: App, config: PlatformConfigs) => {
  const nameSpace = responsiveStorageNameSpace();
  const storedConfigure = Storage.getData("configure", nameSpace) as
    | ResponsiveStorage["configure"]
    | undefined;

  app.use(Storage, {
    nameSpace,
    memory: {
      configure: storedConfigure ?? {
        hideFooter: config.HideFooter ?? true,
        showLogo: config.ShowLogo ?? true
      }
    }
  });
};
