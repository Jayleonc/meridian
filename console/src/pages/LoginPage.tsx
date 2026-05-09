import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { auth } from "../api/client";

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}

export default function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    auth.me()
      .then((state) => {
        if (!cancelled && state.authenticated) navigate(next, { replace: true });
      })
      .catch(() => {
        // Login page remains visible when the current session is absent or expired.
      });
    return () => {
      cancelled = true;
    };
  }, [navigate, next]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await auth.login(username, password);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-screen">
      <div className="grid-bg" />
      <section className="login-panel">
        <div className="login-brand">
          <div className="brand-mark">M</div>
          <div>
            <div className="login-title">MERIDIAN</div>
            <div className="login-subtitle">Demo Access</div>
          </div>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label className="field-label" htmlFor="username">账号</label>
          <input
            id="username"
            className="field-input"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            autoFocus
          />

          <label className="field-label" htmlFor="password">密码</label>
          <input
            id="password"
            className="field-input"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />

          {error && <div className="login-error">{error}</div>}

          <button className="login-submit" type="submit" disabled={submitting}>
            {submitting ? "登录中" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
