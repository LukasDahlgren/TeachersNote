import { useState } from "react";
import type { AuthUser } from "../types";
import { login, ApiError } from "../api";
import AuthHero from "./AuthHero";
import "./AuthPages.css";

interface Props {
  onLogin: (user: AuthUser) => void;
  onGoToSignup: () => void;
}

export default function LoginPage({ onLogin, onGoToSignup }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await login(email, password);
      onLogin(res.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-page__shape auth-page__shape--one" aria-hidden="true" />
      <div className="auth-page__shape auth-page__shape--two" aria-hidden="true" />

      <div className="auth-shell">
        <AuthHero
          title="Study smarter with every lecture."
          text="Upload slides and recordings, then review aligned notes and key takeaways in one place."
          bullets={[
            "Keep your lectures organized",
            "Follow each slide with transcript context",
            "Download polished presentation notes",
          ]}
        />

        <section className="auth-card" aria-labelledby="login-title">
          <div className="auth-card__head">
            <div>
              <h1 id="login-title" className="auth-card__title">Welcome back</h1>
              <p className="auth-card__subtitle">Sign in to continue in TeachersNote.</p>
            </div>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-field">
              <label className="auth-label" htmlFor="login-email">Email</label>
              <input
                id="login-email"
                className="auth-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="auth-field">
              <label className="auth-label" htmlFor="login-password">Password</label>
              <div className="auth-input-wrap">
                <input
                  id="login-password"
                  className="auth-input auth-input--has-toggle"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="auth-password-toggle"
                  onClick={() => setShowPassword((prev) => !prev)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}

            <div className="auth-row">
              <button
                type="submit"
                disabled={loading}
                className="auth-btn"
              >
                {loading ? "Signing in..." : "Sign in"}
              </button>
            </div>
          </form>

          <p className="auth-footer">
            Don&apos;t have an account?
            <button type="button" onClick={onGoToSignup} className="auth-inline-link">
              Sign up
            </button>
          </p>
        </section>
      </div>
    </div>
  );
}
