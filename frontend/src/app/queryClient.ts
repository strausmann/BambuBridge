import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";

/** A 4xx will not get better by asking again; a dropped connection or a 5xx might. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      // "always": without a network a query fails (and the page says the server cannot be
      // reached) instead of waiting silently on a splash until the browser reports online.
      queries: { retry: shouldRetry, staleTime: 15_000, networkMode: "always" },
    },
  });
}
