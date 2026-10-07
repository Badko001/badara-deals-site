import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../services/api";
import type { Dashboard } from "../types/api";

const REFRESH_MS = 5000;
export const BOOKING_NOT_FOUND = "BOOKING_NOT_FOUND";

export function useDashboard(bookingId: string | null) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.dashboard(bookingId));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setError(BOOKING_NOT_FOUND);
        return;
      }
      setError(e instanceof Error ? e.message : "Backend injoignable");
    }
  }, [bookingId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [refresh]);

  return { data, error, refresh };
}
