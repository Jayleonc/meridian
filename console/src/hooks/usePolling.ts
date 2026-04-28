import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Generic polling hook.
 * Returns { data, loading, error, refresh }.
 * Automatically polls at `intervalMs`. Set to 0 to disable auto-poll.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 0,
  deps: unknown[] = []
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await fetcher();
      if (mountedRef.current) setData(result);
    } catch (e) {
      if (mountedRef.current) setError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    mountedRef.current = true;
    refresh();

    let timer: ReturnType<typeof setInterval> | undefined;
    if (intervalMs > 0) {
      timer = setInterval(refresh, intervalMs);
    }

    return () => {
      mountedRef.current = false;
      if (timer) clearInterval(timer);
    };
  }, [refresh, intervalMs]);

  return { data, loading, error, refresh };
}
