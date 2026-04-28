import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useKeyboard } from "../hooks/useKeyboard";

interface CmdItem {
  id: string;
  icon: string;
  label: string;
  hint: string;
  action: () => void;
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useKeyboard("k", () => setOpen(true), { meta: true });
  useKeyboard("Escape", () => setOpen(false), { enabled: open });

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const items = useMemo<CmdItem[]>(
    () => [
      { id: "dash", icon: "\u25A3", label: "Dashboard", hint: "/", action: () => navigate("/") },
      { id: "atlas", icon: "\u2B22", label: "Atlas — Metadata", hint: "/atlas", action: () => navigate("/atlas") },
      { id: "probe", icon: "\u25CE", label: "Probe — Logs", hint: "/probe", action: () => navigate("/probe") },
      { id: "lens", icon: "\u25C8", label: "Lens — Data Query", hint: "/lens", action: () => navigate("/lens") },
      { id: "search", icon: "\u2315", label: "Search Logs...", hint: "Probe", action: () => navigate("/probe?tab=search") },
      { id: "errors", icon: "\u26A0", label: "Recent Errors", hint: "Probe", action: () => navigate("/probe?tab=errors") },
      { id: "trace", icon: "\u21C4", label: "Trace Request", hint: "Probe", action: () => navigate("/probe?tab=trace") },
      { id: "entities", icon: "\u2637", label: "Business Entities", hint: "Lens", action: () => navigate("/lens") },
      { id: "services", icon: "\u229A", label: "Service Discovery", hint: "Atlas", action: () => navigate("/atlas?tab=services") },
      { id: "schemas", icon: "\u2592", label: "Schema Browser", hint: "Atlas", action: () => navigate("/atlas?tab=schemas") },
    ],
    [navigate]
  );

  const filtered = query
    ? items.filter(
        (i) =>
          i.label.toLowerCase().includes(query.toLowerCase()) ||
          i.hint.toLowerCase().includes(query.toLowerCase())
      )
    : items;

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter" && filtered[selected]) {
      filtered[selected].action();
      setOpen(false);
    }
  }

  if (!open) return null;

  return (
    <div className="cmd-overlay" onClick={() => setOpen(false)}>
      <div className="cmd-box" onClick={(e) => e.stopPropagation()}>
        <div className="cmd-input-wrap">
          <span className="cmd-search-icon">{"\u2315"}</span>
          <input
            ref={inputRef}
            className="cmd-input"
            placeholder="Search commands, pages, entities..."
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelected(0); }}
            onKeyDown={handleKeyDown}
          />
        </div>
        <div className="cmd-results">
          {filtered.map((item, i) => (
            <div
              key={item.id}
              className={`cmd-item ${i === selected ? "selected" : ""}`}
              onClick={() => { item.action(); setOpen(false); }}
              onMouseEnter={() => setSelected(i)}
            >
              <span className="cmd-item-icon">{item.icon}</span>
              <span className="cmd-item-label">{item.label}</span>
              <span className="cmd-item-hint">{item.hint}</span>
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: "16px", textAlign: "center", color: "var(--t4)", fontSize: 13 }}>
              No results
            </div>
          )}
        </div>
        <div className="cmd-footer">
          <span><kbd>{"\u2191\u2193"}</kbd> navigate</span>
          <span><kbd>{"\u23CE"}</kbd> select</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
