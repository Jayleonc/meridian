import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  chat,
  type ChatConfig,
  type ChatMessage,
  type ChatSession,
  type ChatSessionSummary,
  type ChatToolCall,
} from "../../api/client";
import { useApp } from "../../context/AppContext";

const EXAMPLES = [
  "最近 1 小时有什么错误？",
  "列出当前可观测服务",
  "搜索 timeout 相关日志",
];
const CHAT_SESSION_KEY = "meridian.chat.session_id";
const TURN_RECONCILE_TIMEOUT_MS = 90000;

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

function sessionTime(ts: number): string {
  const date = new Date(ts * 1000);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return date.toLocaleString("zh-CN", {
    month: sameDay ? undefined : "2-digit",
    day: sameDay ? undefined : "2-digit",
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

function roleLabel(role?: string | null): string {
  if (role === "user") return "你";
  if (role === "assistant") return "Agent";
  return "会话";
}

function summarizeSession(session: ChatSession): ChatSessionSummary {
  const last = session.messages[session.messages.length - 1];
  return {
    id: session.id,
    title: session.title,
    created_at: session.created_at,
    updated_at: session.updated_at,
    message_count: session.messages.length,
    last_message_role: last?.role ?? null,
    last_message_preview: last?.content?.slice(0, 120) ?? "",
  };
}

function mergeSessionSummary(
  sessions: ChatSessionSummary[],
  session: ChatSession
): ChatSessionSummary[] {
  const summary = summarizeSession(session);
  return [summary, ...sessions.filter((item) => item.id !== session.id)].sort(
    (a, b) => b.updated_at - a.updated_at
  );
}

export default function ChatPage() {
  const { toast } = useApp();
  const [params, setParams] = useSearchParams();
  const [config, setConfig] = useState<ChatConfig | null>(null);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [sessionListLoading, setSessionListLoading] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const sendingRef = useRef(false);
  const importedPromptRef = useRef("");

  const modelLabel = useMemo(() => {
    if (!config) return "checking";
    return `${config.provider}:${config.model}`;
  }, [config]);

  async function loadSessionList(showToast = true) {
    setSessionListLoading(true);
    try {
      const result = await chat.listSessions(30);
      setSessions(result.sessions);
      return result.sessions;
    } catch (e) {
      if (showToast) {
        toast("error", e instanceof Error ? e.message : "会话列表加载失败");
      }
      return [];
    } finally {
      setSessionListLoading(false);
    }
  }

  function applySession(next: ChatSession) {
    window.localStorage.setItem(CHAT_SESSION_KEY, next.id);
    setSession((current) => {
      if (current && current.id !== next.id) return current;
      if (
        current &&
        current.id === next.id &&
        current.messages.some((message) => message.id.startsWith("local_")) &&
        next.messages.length < current.messages.length
      ) {
        return current;
      }
      if (current && current.id === next.id && next.updated_at < current.updated_at) {
        return current;
      }
      return next;
    });
    setSessions((current) => mergeSessionSummary(current, next));
  }

  async function waitForAssistantMessage(
    sessionId: string,
    baselineMessageCount: number,
    timeoutMs: number
  ): Promise<ChatSession> {
    return new Promise((resolve, reject) => {
      const source = new EventSource(
        chat.sessionEventsUrl(sessionId, baselineMessageCount, Math.ceil(timeoutMs / 1000))
      );
      let settled = false;
      const timer = window.setTimeout(() => {
        finish();
        reject(new Error("Agent 回复同步超时，请刷新会话或稍后重试"));
      }, timeoutMs + 3000);

      function finish() {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        source.close();
      }

      function handleSession(event: MessageEvent<string>) {
        try {
          const fresh = JSON.parse(event.data) as ChatSession;
          setSessions((current) => mergeSessionSummary(current, fresh));
          const newMessages = fresh.messages.slice(baselineMessageCount);
          if (newMessages.some((message) => message.role === "assistant")) {
            finish();
            resolve(fresh);
          }
        } catch (e) {
          finish();
          reject(e);
        }
      }

      source.addEventListener("session", handleSession);
      source.addEventListener("timeout", (event) => {
        handleSession(event as MessageEvent<string>);
        if (!settled) {
          finish();
          reject(new Error("Agent 回复同步超时，请刷新会话或稍后重试"));
        }
      });
      source.addEventListener("error", () => {
        finish();
        reject(new Error("Agent 推送连接中断，请刷新会话或稍后重试"));
      });
    });
  }

  useEffect(() => {
    let alive = true;
    async function boot() {
      setLoading(true);
      try {
        const [cfg, list] = await Promise.all([
          chat.config(),
          chat.listSessions(30).catch(() => ({ sessions: [] })),
        ]);
        const savedSessionId = window.localStorage.getItem(CHAT_SESSION_KEY);
        let activeSession: ChatSession | null = null;
        if (savedSessionId) {
          try {
            activeSession = await chat.getSession(savedSessionId);
          } catch {
            window.localStorage.removeItem(CHAT_SESSION_KEY);
          }
        }
        if (!activeSession && list.sessions.length > 0) {
          activeSession = await chat.getSession(list.sessions[0].id);
          window.localStorage.setItem(CHAT_SESSION_KEY, activeSession.id);
        }
        if (!activeSession) {
          activeSession = await chat.createSession("Console Agent");
          window.localStorage.setItem(CHAT_SESSION_KEY, activeSession.id);
        }
        if (!alive) return;
        setConfig(cfg);
        setSession(activeSession);
        setSessions(mergeSessionSummary(list.sessions, activeSession));
      } catch (e) {
        toast("error", e instanceof Error ? e.message : "Agent 初始化失败");
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

  useEffect(() => {
    const prompt = params.get("prompt") || "";
    if (!prompt || loading || !session || importedPromptRef.current === prompt) return;

    importedPromptRef.current = prompt;
    const nextParams = new URLSearchParams(params);
    const autoSend = nextParams.get("auto_send") === "1";
    nextParams.delete("prompt");
    nextParams.delete("auto_send");
    setParams(nextParams, { replace: true });

    if (autoSend) {
      void send(prompt);
    } else {
      setInput(prompt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, session?.id, params]);

  async function send(text?: string) {
    const content = (text ?? input).trim();
    if (!content || !session || sendingRef.current) return;

    const sessionId = session.id;
    const baselineMessageCount = session.messages.length;
    sendingRef.current = true;
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
      const eventPromise = waitForAssistantMessage(
        sessionId,
        baselineMessageCount,
        TURN_RECONCILE_TIMEOUT_MS
      );
      const responsePromise = chat.sendMessage(sessionId, content).then((result) => result.session);

      void eventPromise.then(applySession).catch(() => undefined);
      void responsePromise.then(applySession).catch(() => undefined);

      const next = await Promise.any([responsePromise, eventPromise]);
      applySession(next);
    } catch (e) {
      try {
        applySession(await chat.getSession(sessionId));
      } catch {
        setSession((current) => {
          if (!current || current.id !== sessionId) return current;
          return {
            ...current,
            messages: current.messages.filter((message) => message.id !== optimistic.id),
          };
        });
      }
      const detail =
        e instanceof AggregateError
          ? e.errors.find((item): item is Error => item instanceof Error)?.message
          : e instanceof Error
            ? e.message
            : "";
      toast("error", detail || "消息发送失败");
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  async function createNewSession() {
    if (sendingRef.current) return;
    setLoading(true);
    try {
      const created = await chat.createSession("Console Agent");
      window.localStorage.setItem(CHAT_SESSION_KEY, created.id);
      setSession(created);
      setSessions((current) => mergeSessionSummary(current, created));
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "新建会话失败");
    } finally {
      setLoading(false);
    }
  }

  async function openSession(sessionId: string) {
    if (sendingRef.current || session?.id === sessionId) return;
    setLoading(true);
    try {
      const next = await chat.getSession(sessionId);
      window.localStorage.setItem(CHAT_SESSION_KEY, next.id);
      setSession(next);
      setSessions((current) => mergeSessionSummary(current, next));
    } catch (e) {
      toast("error", e instanceof Error ? e.message : "会话加载失败");
    } finally {
      setLoading(false);
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
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => void createNewSession()} disabled={loading || sending}>
              新会话
            </button>
            <span className={`badge ${config?.configured ? "badge-emerald" : "badge-warn"}`}>
              {config?.configured ? "模型已配置" : "缺少模型 Key"}
            </span>
            <span className="badge badge-dim">{modelLabel}</span>
          </div>
        </div>
      </div>

      <div className="page-body chat-page">
        <aside className="chat-session-panel">
          <div className="chat-session-head">
            <div>
              <h3>会话</h3>
              <div className="chat-session-count">{sessions.length} 个最近会话</div>
            </div>
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={() => void loadSessionList()}
              disabled={sessionListLoading || sending}
            >
              {sessionListLoading ? <span className="spinner" /> : "刷新"}
            </button>
          </div>

          <div className="chat-session-list">
            {sessionListLoading && sessions.length === 0 && (
              <div className="empty" style={{ padding: 18 }}>
                <div className="empty-text">正在加载会话</div>
              </div>
            )}

            {!sessionListLoading && sessions.length === 0 && (
              <div className="empty" style={{ padding: 18 }}>
                <div className="empty-text">还没有历史会话</div>
              </div>
            )}

            {sessions.map((item) => (
              <button
                key={item.id}
                className={`chat-session-item ${session?.id === item.id ? "active" : ""}`}
                type="button"
                onClick={() => void openSession(item.id)}
                disabled={loading || sending}
                title={item.title}
              >
                <div className="chat-session-title">
                  <span>{item.title}</span>
                  <time>{sessionTime(item.updated_at)}</time>
                </div>
                <div className="chat-session-preview">
                  {item.last_message_preview
                    ? `${roleLabel(item.last_message_role)}：${item.last_message_preview}`
                    : "空会话"}
                </div>
                <div className="chat-session-meta">{item.message_count} 条消息</div>
              </button>
            ))}
          </div>
        </aside>

        <div className="chat-workspace">
          <div className="chat-thread" ref={threadRef}>
            {loading && (
              <div className="empty">
                <div className="empty-text">正在加载 Agent 会话</div>
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
                    <span className="badge badge-amber"><span className="spinner" /> 思考中</span>
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
              aria-label="Agent 消息"
              placeholder="问 Meridian，例如：最近 1 小时有哪些错误？"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
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
              {sending ? <><span className="spinner" /> 发送中</> : "发送"}
            </button>
          </form>
        </div>
      </div>
    </>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const speaker = message.role === "user" ? "你" : "Agent";
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
          <div className="chat-tool-label">参数</div>
          <pre>{formatValue(tool.arguments)}</pre>
        </div>
        <div>
          <div className="chat-tool-label">结果</div>
          <pre>{formatValue(tool.result)}</pre>
        </div>
      </div>
    </details>
  );
}
