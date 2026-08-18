import { markRaw, type Component } from "vue";

const MAP = new Map<string, Component>();

export const useMultiFrame = () => {
  function setMap(path: string, Comp: Component) {
    MAP.set(path, markRaw(Comp));
  }

  function getMap(path: string): Component | undefined;
  function getMap(path?: undefined): Array<[string, Component]>;
  function getMap(path?: string) {
    if (path) {
      return MAP.get(path);
    }
    return [...MAP.entries()];
  }

  function delMap(path: string) {
    MAP.delete(path);
  }

  return {
    setMap,
    getMap,
    delMap,
    MAP
  };
};
