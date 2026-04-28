import { useEffect } from "react";

/** Register a global keyboard shortcut. */
export function useKeyboard(
  key: string,
  handler: (e: KeyboardEvent) => void,
  opts: { meta?: boolean; shift?: boolean; enabled?: boolean } = {}
) {
  const { meta = false, shift = false, enabled = true } = opts;

  useEffect(() => {
    if (!enabled) return;

    function onKey(e: KeyboardEvent) {
      if (meta && !(e.metaKey || e.ctrlKey)) return;
      if (shift && !e.shiftKey) return;
      if (e.key.toLowerCase() !== key.toLowerCase()) return;

      // Don't fire inside input/textarea unless it's Escape
      const tag = (e.target as HTMLElement)?.tagName;
      if (key !== "Escape" && (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT")) return;

      e.preventDefault();
      handler(e);
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, handler, meta, shift, enabled]);
}
