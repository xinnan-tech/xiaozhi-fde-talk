import Axios from "axios";
import { onBeforeUnmount } from "vue";

/** 按请求 key 管理可取消的 HTTP 请求 */
export function useAbortableRequests() {
  const controllers = new Map<string, AbortController>();

  /** 创建请求 signal；同 key 的旧请求会先取消 */
  const createSignal = (key: string) => {
    controllers.get(key)?.abort();

    const controller = new AbortController();
    controllers.set(key, controller);
    return controller.signal;
  };

  /** 请求结束后清除map中的controller */
  const finish = (key: string, signal: AbortSignal) => {
    if (controllers.get(key)?.signal === signal) {
      controllers.delete(key);
    }
  };

  /** 取消指定key请求 */
  const cancel = (key: string) => {
    controllers.get(key)?.abort();
    controllers.delete(key);
  };

  /** 取消全部请求 */
  const cancelAll = () => {
    for (const controller of controllers.values()) {
      controller.abort();
    }
    controllers.clear();
  };

  /** 手动取消的请求不提示错误 */
  const isCanceled = (error: unknown) => Axios.isCancel(error);

  onBeforeUnmount(cancelAll);

  return {
    createSignal,
    finish,
    cancel,
    cancelAll,
    isCanceled
  };
}
