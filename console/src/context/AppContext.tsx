import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { checkServiceHealth, type ServiceStatus } from "../api/client";

/* ── Types ── */

export interface Toast {
  id: string;
  type: "info" | "success" | "error";
  message: string;
}

interface AppState {
  health: Record<"atlas" | "probe" | "lens", ServiceStatus>;
  sidebarOpen: boolean;
  toasts: Toast[];
}

interface AppActions {
  toggleSidebar: () => void;
  toast: (type: Toast["type"], message: string) => void;
  dismissToast: (id: string) => void;
}

const Ctx = createContext<(AppState & AppActions) | null>(null);

/* ── Provider ── */

export function AppProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<AppState["health"]>({
    atlas: "checking",
    probe: "checking",
    lens: "checking",
  });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  // Health polling
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      const [a, p, l] = await Promise.all([
        checkServiceHealth("atlas"),
        checkServiceHealth("probe"),
        checkServiceHealth("lens"),
      ]);
      if (!cancelled) setHealth({ atlas: a, probe: p, lens: l });
    }
    poll();
    const timer = setInterval(poll, 12000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const toggleSidebar = useCallback(() => setSidebarOpen((v) => !v), []);

  const toast = useCallback((type: Toast["type"], message: string) => {
    const id = String(++toastId.current);
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000);
  }, []);

  const dismissToast = useCallback(
    (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)),
    []
  );

  return (
    <Ctx.Provider value={{ health, sidebarOpen, toasts, toggleSidebar, toast, dismissToast }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be inside AppProvider");
  return ctx;
}
