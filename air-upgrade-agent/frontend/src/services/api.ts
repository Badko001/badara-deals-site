import type {
  CostLimits,
  Dashboard,
  MockScenarios,
  UpgradeExecutionResult,
} from "../types/api";

const BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = (await response.json()) as { message?: string; detail?: unknown };
      message = body.message ?? (typeof body.detail === "string" ? body.detail : message);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export const api = {
  dashboard: () => request<Dashboard>("/dashboard"),
  checkNow: () => request<unknown>("/check", { method: "POST" }),
  startMonitoring: () => request<unknown>("/monitoring/start", { method: "POST" }),
  stopMonitoring: () => request<unknown>("/monitoring/stop", { method: "POST" }),
  confirm: (id: string) =>
    request<UpgradeExecutionResult>(`/confirmations/${encodeURIComponent(id)}/confirm`, {
      method: "POST",
    }),
  decline: (id: string) =>
    request<unknown>(`/confirmations/${encodeURIComponent(id)}/decline`, { method: "POST" }),
  setLimits: (cash_limit: number, miles_limit: number) =>
    request<CostLimits>("/settings/limits", {
      method: "PUT",
      body: JSON.stringify({ cash_limit, miles_limit }),
    }),
  startSession: () =>
    request<unknown>("/session/start", { method: "POST", body: JSON.stringify({}) }),
  mockScenarios: () => request<MockScenarios>("/mock/scenarios"),
  setMockScenario: (name: string) =>
    request<unknown>("/mock/scenario", { method: "POST", body: JSON.stringify({ name }) }),
};
