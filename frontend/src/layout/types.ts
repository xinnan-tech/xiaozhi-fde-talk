import type { FunctionalComponent } from "vue";

export type routeMetaType = {
  title?: string;
  icon?: string | FunctionalComponent;
  showLink?: boolean;
  savedPosition?: boolean;
  auths?: Array<string>;
};

export interface setType {
  sidebar: {
    opened: boolean;
    withoutAnimation: boolean;
    isClickCollapse: boolean;
  };
  device: string;
  classes: {
    hideSidebar: boolean;
    openSidebar: boolean;
    withoutAnimation: boolean;
    mobile: boolean;
  };
}

export type menuType = {
  id?: number;
  name?: string;
  path?: string;
  noShowingChildren?: boolean;
  children?: menuType[];
  value: unknown;
  meta?: {
    icon?: string;
    title?: string;
    titleKey?: string;
    rank?: number;
    showParent?: boolean;
    extraIcon?: string;
  };
  showTooltip?: boolean;
  parentId?: number;
  pathList?: number[];
  redirect?: string;
};

export interface scrollbarDomType extends HTMLElement {
  wrap?: {
    offsetWidth: number;
  };
}
