import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";

/* ── Types ── */

export interface InvStep {
  type: "error" | "trace" | "service" | "schema" | "entity" | "query";
  label: string;
  path: string;
  data?: Record<string, unknown>;
}

interface InvState {
  steps: InvStep[];
  push: (step: InvStep) => void;
  goTo: (index: number) => void;
  clear: () => void;
}

const Ctx = createContext<InvState | null>(null);

/* Icons per step type */
const ICONS: Record<InvStep["type"], string> = {
  error: "\u26A0",
  trace: "\u21C4",
  service: "\u2B22",
  schema: "\u2637",
  entity: "\u25C8",
  query: "\u25B6",
};

export function getStepIcon(type: InvStep["type"]) {
  return ICONS[type];
}

/* ── Provider ── */

export function InvestigationProvider({ children }: { children: ReactNode }) {
  const [steps, setSteps] = useState<InvStep[]>([]);
  const navigate = useNavigate();

  const push = useCallback(
    (step: InvStep) => {
      setSteps((prev) => [...prev, step]);
      navigate(step.path);
    },
    [navigate]
  );

  const goTo = useCallback(
    (index: number) => {
      setSteps((prev) => prev.slice(0, index + 1));
      const target = steps[index];
      if (target) navigate(target.path);
    },
    [steps, navigate]
  );

  const clear = useCallback(() => setSteps([]), []);

  return (
    <Ctx.Provider value={{ steps, push, goTo, clear }}>
      {children}
    </Ctx.Provider>
  );
}

export function useInvestigation() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useInvestigation must be inside InvestigationProvider");
  return ctx;
}
