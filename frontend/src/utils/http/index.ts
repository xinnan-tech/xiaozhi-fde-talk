import Axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type CustomParamsSerializer
} from "axios";
import type {
  PureHttpError,
  RequestMethods,
  PureHttpResponse,
  PureHttpRequestConfig
} from "./types.d";
import { stringify } from "qs";
import { getToken, setToken, formatToken, removeToken } from "@/utils/auth";
import { useUserStoreHook } from "@/store/modules/user";
import { message } from "@/utils/message";
import { getCurrentLocale, i18n } from "@/i18n";
import { extractDetailText } from "@/utils/error";
import { refreshApi } from "@/api/user";

// 相关配置请参考：www.axios-js.com/zh-cn/docs/#axios-request-config-1
const defaultConfig: AxiosRequestConfig = {
  // 请求超时时间
  timeout: 60000,
  headers: {
    Accept: "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest"
  },
  // 数组格式参数序列化
  paramsSerializer: {
    serialize: stringify as unknown as CustomParamsSerializer
  }
};

/** 用 refresh token 换 access 的响应体。refreshApi 已在 @/api/user 暴露同名类型。 */

/**
 * 401 后允许静默重放的 HTTP 方法集合：HTTP 语义上保证幂等，重放不会产生副作用。
 * POST/PUT/DELETE/PATCH 一律不重放，避免「改密双扣 / 新建访谈双发 / 写两条
 * 审计」之类的二阶事故。来源：RFC 9110 §9.2.2（safe methods）。
 */
const SAFE_REPLAY_METHODS = new Set(["get", "head", "options"]);

class PureHttp {
  constructor() {
    this.httpInterceptorsRequest();
    this.httpInterceptorsResponse();
  }

  /** 初始化配置对象 */
  private static initConfig: PureHttpRequestConfig = {};

  /** 保存当前`Axios`实例对象 */
  private static axiosInstance: AxiosInstance = Axios.create(defaultConfig);

  /**
   * 401 自动续 access：用一个共享标志 + 等待队列避免并发请求各刷各的。
   * - 第一个 401 命中：发起 refresh，promise resolve 后逐个用新 access 重放原请求；
   * - 后续 401 命中：进入等待队列，待 refresh 完一起重放；
   * - refresh 失败：统一清 token + 弹「登录已过期」。
   */
  private static refreshing: Promise<string | null> | null = null;

  /** 请求拦截 */
  private httpInterceptorsRequest(): void {
    PureHttp.axiosInstance.interceptors.request.use(
      async (config: PureHttpRequestConfig): Promise<any> => {
        const locale = getCurrentLocale();
        config.headers = config.headers ?? {};
        config.headers["X-Lang"] = locale;
        config.headers["Accept-Language"] = locale;

        // 优先判断post/get等方法是否传入回调，否则执行初始化设置等回调
        if (typeof config.beforeRequestCallback === "function") {
          config.beforeRequestCallback(config);
          return config;
        }
        if (PureHttp.initConfig.beforeRequestCallback) {
          PureHttp.initConfig.beforeRequestCallback(config);
          return config;
        }
        /** 请求白名单，放置一些不需要`token`的接口（通过设置请求白名单，防止`token`过期后再请求造成的死循环问题） */
        const whiteList = ["/api/v1/auth/login"];
        return whiteList.some(url => config.url?.endsWith(url) ?? false)
          ? config
          : new Promise(resolve => {
              const data = getToken();
              if (data) {
                if (config.headers)
                  config.headers["Authorization"] = formatToken(
                    data.accessToken
                  );
                resolve(config);
              } else {
                resolve(config);
              }
            });
      },
      error => {
        return Promise.reject(error);
      }
    );
  }

  /** 响应拦截 */
  private httpInterceptorsResponse(): void {
    const instance = PureHttp.axiosInstance;
    instance.interceptors.response.use(
      (response: PureHttpResponse) => {
        const $config = response.config;
        // 优先判断post/get等方法是否传入回调，否则执行初始化设置等回调
        if (typeof $config.beforeResponseCallback === "function") {
          $config.beforeResponseCallback(response);
          return response.data;
        }
        if (PureHttp.initConfig.beforeResponseCallback) {
          PureHttp.initConfig.beforeResponseCallback(response);
          return response.data;
        }
        return response.data;
      },
      async (error: PureHttpError) => {
        const $error = error;
        $error.isCancelRequest = Axios.isCancel($error);
        const response = $error.response;
        const responseData = response?.data;
        const responseBody =
          typeof responseData === "object" && responseData !== null
            ? (responseData as { code?: unknown; detail?: unknown })
            : undefined;
        const hasBusinessCode =
          typeof responseBody?.code === "string" &&
          responseBody.code.length > 0;

        const originalConfig = $error.config as
          | PureHttpRequestConfig
          | undefined;
        const isExpiredSession = response?.status === 401 && !hasBusinessCode;
        // refresh 调用自身的 401：不二次触发 refresh-on-401，杜绝递归。
        const isRefreshCall = originalConfig?._refreshRequest === true;
        // 重放过的请求再 401：不再触发第二轮 refresh。
        const isRetry = originalConfig?._refreshRetried === true;

        if (isExpiredSession && !isRefreshCall && !isRetry) {
          const token = getToken();

          if (token?.refreshToken && originalConfig) {
            // 共享一次 refresh：第一个 401 触发 refreshApi，后续 401 等同一 promise。
            // refreshApi 走 http.request 套上请求拦截器（自动注入 X-Lang 等），同时
            // config 上挂 _refreshRequest: true 让响应拦截器看到 401 不再二次递归。
            if (!PureHttp.refreshing) {
              PureHttp.refreshing = refreshApi({
                refresh_token: token.refreshToken
              })
                .then(res => {
                  PureHttp.refreshing = null;
                  const newAccess = res?.access_token;
                  if (newAccess) {
                    // 把新 access 写回 store + localStorage；refresh 自身保留。
                    const refreshed = { ...token, accessToken: newAccess };
                    setToken(refreshed);
                    return newAccess;
                  }
                  // refresh 返回 200 但 access_token 缺失（极少见，业务异常）：
                  // 走清会话 + 提示。
                  PureHttp.clearSession();
                  message(i18n.global.t("msg.session_expired"), {
                    type: "warning",
                    grouping: true
                  });
                  return null;
                })
                .catch(() => {
                  PureHttp.refreshing = null;
                  // refresh 自身 reject（含 401 refresh token 过期 / 429 / 5xx / 网络错误）：
                  // 统一清会话 + 提示，让所有共享 promise 的并发 401 都走「已过期」分支。
                  PureHttp.clearSession();
                  message(i18n.global.t("msg.session_expired"), {
                    type: "warning",
                    grouping: true
                  });
                  return null;
                });
            }

            const newAccess = await PureHttp.refreshing;
            if (newAccess) {
              // P1.1: 仅对幂等方法重放。非幂等（POST/PUT/DELETE 等）一旦 401 触发
              // 静默续期会被二次提交：改密双扣 / 新建访谈双发 / 写两条审计。
              const method = (originalConfig.method ?? "").toLowerCase();
              const isSafeToReplay = SAFE_REPLAY_METHODS.has(method);
              if (!isSafeToReplay) {
                // 直接拒绝；上层已经在 refreshing.then 里通知过「session_expired」，
                // 没必要再 toast 一遍业务报错。
                return Promise.reject($error);
              }
              // 标记已重试，避免重放后再 401 触发第二次 refresh。
              originalConfig._refreshRetried = true;
              // request 拦截器会按 setToken(refreshed) 后最新的 accessToken 重写
              // Authorization header，无需在这里手动覆写。
              return PureHttp.axiosInstance.request(originalConfig);
            }
            // refresh 失败 → 走到下面 toast（已经在 refreshing.then 里弹过）。
            return Promise.reject($error);
          }

          // 无 refresh token（旧的登录会话 / 已主动登出），按老路径清 + 提示。
          if (token) PureHttp.clearSession();
          message(i18n.global.t("msg.session_expired"), {
            type: "warning",
            grouping: true
          });
        } else if (isExpiredSession && (isRetry || isRefreshCall)) {
          // 重放后仍 401，或 refresh 调用自身失败：refresh 拿到的是合法 access 但
          // 服务端仍拒（比如 refresh 与 access 之间服务端强制失效），或 refresh
          // token 本身已过期。直接拒绝，不再 toast ——上游已经在 refreshing.then
          // 里通知过用户。
          return Promise.reject($error);
        }

        if (response?.status && !isExpiredSession) {
          const errorMessage = extractDetailText(responseBody?.detail);
          if (errorMessage) {
            message(errorMessage, {
              type: response.status === 401 ? "warning" : "error",
              grouping: true
            });
          } else if (response.status === 500) {
            message(i18n.global.t("msg.server_error"), {
              type: "error",
              grouping: true
            });
          }
        }

        // 所有的响应异常 区分来源为取消请求/非取消请求
        return Promise.reject($error);
      }
    );
  }

  /** 清掉本端持有的会话：本地存储 + store。供 401 路径复用。 */
  private static clearSession() {
    removeToken();
    const userStore = useUserStoreHook();
    userStore.SET_ACCESS_TOKEN("");
    userStore.SET_REFRESH_TOKEN("");
    userStore.SET_USERNAME("");
  }

  /** 通用请求工具函数 */
  public request<T>(
    method: RequestMethods,
    url: string,
    param?: AxiosRequestConfig,
    axiosConfig?: PureHttpRequestConfig
  ): Promise<T> {
    const config = {
      method,
      url,
      ...param,
      ...axiosConfig
    } as PureHttpRequestConfig;

    // 单独处理自定义请求/响应回调
    return new Promise((resolve, reject) => {
      PureHttp.axiosInstance
        .request<PureHttpResponse, unknown>(config)
        .then((response: PureHttpResponse) => {
          // PureHttp 的 response 拦截器已 return response.data，
          // 这里拿到的就是后端 body，再 .data 会多拆一层导致 undefined。
          resolve(response as T);
        })
        .catch(error => {
          reject(error);
        });
    });
  }

  /** 单独抽离的`post`工具函数 */
  public post<T, P>(
    url: string,
    params?: AxiosRequestConfig<P>,
    config?: PureHttpRequestConfig
  ): Promise<T> {
    return this.request<T>("post", url, params, config);
  }

  /** 单独抽离的`get`工具函数 */
  public get<T, P>(
    url: string,
    params?: AxiosRequestConfig<P>,
    config?: PureHttpRequestConfig
  ): Promise<T> {
    return this.request<T>("get", url, params, config);
  }
}

export const http = new PureHttp();
