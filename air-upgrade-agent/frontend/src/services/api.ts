import type {
  BookingInfo,
  CostLimits,
  Dashboard,
  MockScenarios,
  NewBooking,
  NewPriceWatch,
  PriceAlert,
  PriceWatchStatus,
  UpgradeExecutionResult,
  WatchSummary,
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

const q = (bookingId: string | null): string =>
  bookingId ? `?booking_id=${encodeURIComponent(bookingId)}` : "";

export const api = {
  dashboard: (bookingId: string | null) => request<Dashboard>(`/dashboard${q(bookingId)}`),
  checkNow: (bookingId: string | null) =>
    request<unknown>(`/check${q(bookingId)}`, { method: "POST" }),
  startMonitoring: (bookingId: string | null) =>
    request<unknown>(`/monitoring/start${q(bookingId)}`, { method: "POST" }),
  stopMonitoring: (bookingId: string | null) =>
    request<unknown>(`/monitoring/stop${q(bookingId)}`, { method: "POST" }),
  addBooking: (booking: NewBooking) =>
    request<BookingInfo>("/bookings", { method: "POST", body: JSON.stringify(booking) }),
  updateBooking: (bookingId: string, changes: Partial<Omit<NewBooking, "mock_scenario">>) =>
    request<BookingInfo>(`/bookings/${encodeURIComponent(bookingId)}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    }),
  deleteBooking: (bookingId: string) =>
    request<unknown>(`/bookings/${encodeURIComponent(bookingId)}`, { method: "DELETE" }),
  confirm: (id: string) =>
    request<UpgradeExecutionResult>(`/confirmations/${encodeURIComponent(id)}/confirm`, {
      method: "POST",
    }),
  decline: (id: string) =>
    request<unknown>(`/confirmations/${encodeURIComponent(id)}/decline`, { method: "POST" }),
  setLimits: (
    bookingId: string | null,
    cash_limit: number,
    miles_limit: number,
    passengers_target: number,
  ) =>
    request<CostLimits>(`/settings/limits${q(bookingId)}`, {
      method: "PUT",
      body: JSON.stringify({ cash_limit, miles_limit, passengers_target }),
    }),
  startSession: () =>
    request<unknown>("/session/start", { method: "POST", body: JSON.stringify({}) }),
  priceWatchStatus: () => request<PriceWatchStatus>("/pricewatch/status"),
  watches: () => request<WatchSummary[]>("/pricewatch/watches"),
  addWatch: (watch: NewPriceWatch) =>
    request<unknown>("/pricewatch/watches", { method: "POST", body: JSON.stringify(watch) }),
  deleteWatch: (id: string) =>
    request<unknown>(`/pricewatch/watches/${encodeURIComponent(id)}`, { method: "DELETE" }),
  checkWatch: (id: string) =>
    request<unknown>(`/pricewatch/watches/${encodeURIComponent(id)}/check`, { method: "POST" }),
  priceAlerts: () => request<PriceAlert[]>("/pricewatch/alerts"),
  startPriceWatch: () => request<unknown>("/pricewatch/start", { method: "POST" }),
  stopPriceWatch: () => request<unknown>("/pricewatch/stop", { method: "POST" }),
  mockScenarios: (bookingId: string | null) =>
    request<MockScenarios>(`/mock/scenarios${q(bookingId)}`),
  setMockScenario: (bookingId: string | null, name: string) =>
    request<unknown>(`/mock/scenario${q(bookingId)}`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  mockPageUrl: (bookingId: string | null) => `${BASE}/api/mock/page${q(bookingId)}`,
};
