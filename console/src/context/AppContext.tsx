import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { checkServiceHealth, nexus, type ServiceStatus } from "../api/client";

/* ── Types ── */

export interface Toast {
  id: string;
  type: "info" | "success" | "error";
  message: string;
}

interface AppState {
  health: Record<"atlas" | "probe" | "lens", ServiceStatus>;
  configLoaded: boolean;
  demoMode: boolean;
  demoAllowedPages: string[];
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
  const [configLoaded, setConfigLoaded] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [demoAllowedPages, setDemoAllowedPages] = useState<string[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  useEffect(() => {
    let cancelled = false;
    async function loadConfig() {
      try {
        const info = await nexus.info();
        if (cancelled) return;
        setDemoMode(Boolean(info.demo?.enabled));
        setDemoAllowedPages(info.demo?.allowed_pages ?? []);
      } catch {
        if (cancelled) return;
        setDemoMode(false);
        setDemoAllowedPages([]);
      } finally {
        if (!cancelled) setConfigLoaded(true);
      }
    }
    void loadConfig();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!configLoaded) return;
    if (demoMode) {
      setHealth({ atlas: "offline", probe: "offline", lens: "offline" });
      return;
    }

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
  }, [configLoaded, demoMode]);

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
    <Ctx.Provider value={{ health, configLoaded, demoMode, demoAllowedPages, sidebarOpen, toasts, toggleSidebar, toast, dismissToast }}>
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be inside AppProvider");
  return ctx;
}
