import { useEffect, useMemo, useRef, useState } from "react";
import { chat, type ChatConfig, type ChatMessage, type ChatSession, type ChatToolCall } from "../../api/client";
import { useApp } from "../../context/AppContext";

const EXAMPLES = [
  "最近 1 小时有什么错误？",
  "列出当前可观测服务",
  "搜索 timeout 相关日志",
];

function formatToolName(name: string): string {
  if (name.startsWith("probe_")) return name.replace(/^probe_/, "probe.");
  return name;
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function timeOf(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function ChatPage() {
  const { toast } = useApp();
  const [config, setConfig] = useState<ChatConfig | null>(null);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);

  const modelLabel = useMemo(() => {
    if (!config) return "checking";
    return `${config.provider}:${config.model}`;
  }, [config]);

  useEffect(() => {
    let alive = true;
    async function boot() {
      setLoading(true);
      try {
        const [cfg, created] = await Promise.all([
          chat.config(),
          chat.createSession("Console Agent"),
        ]);
        if (!alive) return;
        setConfig(cfg);
        setSession(created);
      } catch (e) {
        toast("error", e instanceof Error ? e.message : "Agent init failed");
      } finally {
        if (alive) setLoading(false);
      }
    }
    void boot();
    return () => {
      alive = false;
    };
  }, [toast]);

  useEffect(() => {
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [session?.messages.length, sending]);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || !session || sending) return;

    setInput("");
    setSending(true);
    const optimistic: ChatMessage = {
      id: `local_${Date.now()}`,
      role: "user",
      content,
      created_at: Date.now() / 1000,
      tool_calls: [],
    };
    setSession((current) =>
      current ? { ...current, messages: [...current.messages, optimistic] } : current
    );

    try {
      const result = await chat.sendMessage(session.id, content);
      setSession(result.session);
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "Message failed");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <div className="page-header">
        <div className="flex-between">
          <div>
            <h2>Agent</h2>
            <div className="page-desc">Nexus 编排 — 当前接入 Probe 诊断工具</div>
          </div>
          <div className="row gap-sm wrap">
            <span className={`badge ${config?.configured ? "badge-emerald" : "badge-warn"}`}>
              {config?.configured ? "MODEL READY" : "MODEL KEY MISSING"}
            </span>
            <span className="badge badge-dim">{modelLabel}</span>
          </div>
        </div>
      </div>

      <div className="page-body chat-page">
        <div className="chat-thread" ref={threadRef}>
          {loading && (
            <div className="empty">
              <div className="empty-text">Loading agent session</div>
            </div>
          )}

          {!loading && session?.messages.length === 0 && (
            <div className="chat-empty">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  className="chat-example"
                  type="button"
                  onClick={() => void send(example)}
                  disabled={sending || !session}
                >
                  {example}
                </button>
              ))}
            </div>
          )}

          {session?.messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}

          {sending && (
            <div className="chat-row assistant">
              <div className="chat-message">
                <div className="chat-meta">
                  <span>Agent</span>
                  <span className="badge badge-amber"><span className="spinner" /> Thinking</span>
                </div>
              </div>
            </div>
          )}
        </div>

        <form
          className="chat-composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <textarea
            className="input chat-input"
            aria-label="Agent message"
            placeholder="Ask Meridian..."
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            disabled={loading || sending || !session}
          />
          <button
            className="btn btn-primary chat-send"
            type="submit"
            disabled={loading || sending || !input.trim() || !session}
          >
            {sending ? <><span className="spinner" /> Sending</> : "Send"}
          </button>
        </form>
      </div>
    </>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const speaker = message.role === "user" ? "You" : "Agent";
  return (
    <div className={`chat-row ${message.role}`}>
      <div className="chat-message">
        <div className="chat-meta">
          <span>{speaker}</span>
          <span>{timeOf(message.created_at)}</span>
        </div>
        {message.content && <div className="chat-content">{message.content}</div>}
        {message.tool_calls.length > 0 && (
          <div className="chat-tools">
            {message.tool_calls.map((tool) => (
              <ToolCall key={tool.id} tool={tool} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolCall({ tool }: { tool: ChatToolCall }) {
  return (
    <details className={`chat-tool ${tool.error ? "error" : ""}`}>
      <summary>
        <span>{formatToolName(tool.name)}</span>
        <span>{tool.duration_ms}ms</span>
      </summary>
      <div className="chat-tool-grid">
        <div>
          <div className="chat-tool-label">Arguments</div>
          <pre>{formatValue(tool.arguments)}</pre>
        </div>
        <div>
          <div className="chat-tool-label">Result</div>
          <pre>{formatValue(tool.result)}</pre>
        </div>
      </div>
    </details>
  );
}
