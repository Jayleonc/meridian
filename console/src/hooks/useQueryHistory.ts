import { useCallback, useState } from "react";

interface HistoryEntry {
  entity: string;
  dsl: Record<string, unknown>;
  timestamp: number;
  resultCount?: number;
  durationMs?: number;
}

const STORAGE_KEY = "meridian_query_history";
const MAX = 50;

function load(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function save(entries: HistoryEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, MAX)));
}

export function useQueryHistory() {
  const [history, setHistory] = useState<HistoryEntry[]>(load);

  const push = useCallback(
    (entry: Omit<HistoryEntry, "timestamp">) => {
      const next = [{ ...entry, timestamp: Date.now() }, ...history].slice(0, MAX);
      setHistory(next);
      save(next);
    },
    [history]
  );

  const clear = useCallback(() => {
    setHistory([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return { history, push, clear };
}
