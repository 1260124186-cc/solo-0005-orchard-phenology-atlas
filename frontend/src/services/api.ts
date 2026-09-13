import type { ApiErrorPayload, ApiFailure } from "../domain/types";

type QueryValue = string | number | boolean | null | undefined;

export class ApiError extends Error {
  readonly failure: ApiFailure;

  constructor(failure: ApiFailure) {
    super(failure.message);
    this.name = "ApiError";
    this.failure = failure;
  }
}

function encodeQuery(query?: Record<string, QueryValue>): string {
  if (!query) return "";
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    params.set(key, String(value));
  });
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

async function request<T>(
  path: string,
  requestInit: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...requestInit,
    headers: {
      Accept: "application/json",
      ...(requestInit.body ? { "Content-Type": "application/json" } : {}),
      ...requestInit.headers,
    },
  });
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new ApiError({
        code: "invalid_response",
        message: "服务返回了无法解析的数据",
        details: { status: response.status },
        status: response.status,
      });
    }
  }
  if (!response.ok) {
    const typed = payload as ApiErrorPayload | null;
    throw new ApiError({
      code: typed?.error?.code ?? "request_failed",
      message: typed?.error?.message ?? `请求失败（${response.status}）`,
      details: typed?.error?.details ?? {},
      status: response.status,
    });
  }
  return payload as T;
}

function jsonBody(value: unknown): RequestInit {
  return { body: JSON.stringify(value) };
}

export const api = {
  health: () => request<{ status: string; service: string }>("/health"),
  listPlots: (query?: Record<string, QueryValue>) =>
    request(`/plots${encodeQuery(query)}`),
  getPlot: (id: string) => request(`/plots/${encodeURIComponent(id)}`),
  createPlot: (body: unknown) => request("/plots", {
    method: "PUT",
    ...jsonBody(body),
  }),
  updatePlot: (id: string, body: unknown) =>
    request(`/plots/${encodeURIComponent(id)}`, {
      method: "PATCH",
      ...jsonBody(body),
    }),
  confirmPlot: (id: string, revision: number) =>
    request(`/plots/${encodeURIComponent(id)}/confirm`, {
      method: "PUT",
      ...jsonBody({ revision }),
    }),
  listTrees: (query?: Record<string, QueryValue>) =>
    request(`/trees${encodeQuery(query)}`),
  createTree: (body: unknown) =>
    request("/trees", { method: "PUT", ...jsonBody(body) }),
  closeTree: (id: string, body: unknown) =>
    request(`/trees/${encodeURIComponent(id)}/close`, {
      method: "PUT",
      ...jsonBody(body),
    }),
  listObservations: (query?: Record<string, QueryValue>) =>
    request(`/observations${encodeQuery(query)}`),
  getObservation: (id: string) =>
    request(`/observations/${encodeURIComponent(id)}`),
  createObservation: (body: unknown) =>
    request("/observations", { method: "PUT", ...jsonBody(body) }),
  updateObservation: (id: string, body: unknown) =>
    request(`/observations/${encodeURIComponent(id)}`, {
      method: "PATCH",
      ...jsonBody(body),
    }),
  addStage: (id: string, body: unknown) =>
    request(`/observations/${encodeURIComponent(id)}/stages`, {
      method: "PUT",
      ...jsonBody(body),
    }),
  removeStage: (id: string, stage: string, revision: number) =>
    request(
      `/observations/${encodeURIComponent(id)}/stages/${encodeURIComponent(stage)}`,
      { method: "DELETE", ...jsonBody({ revision }) },
    ),
  completeObservation: (id: string, revision: number) =>
    request(`/observations/${encodeURIComponent(id)}/complete`, {
      method: "PUT",
      ...jsonBody({ revision }),
    }),
  listComparisons: () => request("/comparisons"),
  createComparison: (body: unknown) =>
    request("/comparisons", { method: "PUT", ...jsonBody(body) }),
  listBriefs: (query?: Record<string, QueryValue>) =>
    request(`/briefs${encodeQuery(query)}`),
  createBrief: (plotId: string, title: string) =>
    request(`/plots/${encodeURIComponent(plotId)}/briefs`, {
      method: "PUT",
      ...jsonBody({ title }),
    }),
  getBrief: (id: string) => request(`/briefs/${encodeURIComponent(id)}`),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "发生未知错误，请稍后重试";
}
