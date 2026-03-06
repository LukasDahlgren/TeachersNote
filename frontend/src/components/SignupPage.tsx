import { useState } from "react";
import type { AuthUser } from "../types";
import { register, ApiError } from "../api";
import AuthHero from "./AuthHero";
import "./AuthPages.css";

interface Props {
  onSignup: (user: AuthUser) => void;
  onGoToLogin: () => void;
}

export default function SignupPage({ onSignup, onGoToLogin }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await register(email, password, displayName || undefined);
      onSignup(res.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
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
          title="Create your lecture workspace."
          text="Set up your account to upload lectures, review aligned notes, and keep everything in one place."
          bullets={[
            "Organize lecture uploads in one place",
            "Keep notes aligned with slide content",
            "Add course context when you upload",
          ]}
        />

        <section className="auth-card" aria-labelledby="signup-title">
          <div className="auth-card__head">
            <div>
              <h1 id="signup-title" className="auth-card__title">Create account</h1>
              <p className="auth-card__subtitle">Start with your sign-in details.</p>
            </div>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="auth-field">
              <label className="auth-label" htmlFor="signup-display-name">Display name (optional)</label>
              <input
                id="signup-display-name"
                className="auth-input"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
              />
            </div>

            <div className="auth-field">
              <label className="auth-label" htmlFor="signup-email">Email</label>
              <input
                id="signup-email"
                className="auth-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
            </div>

            <div className="auth-field">
              <label className="auth-label" htmlFor="signup-password">Password (min. 8 characters)</label>
              <div className="auth-input-wrap">
                <input
                  id="signup-password"
                  className="auth-input auth-input--has-toggle"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={8}
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
              <button type="submit" disabled={loading} className="auth-btn">
                {loading ? "Creating account..." : "Create account"}
              </button>
            </div>
          </form>

          <p className="auth-footer">
            Already have an account?
            <button
              type="button"
              onClick={onGoToLogin}
              className="auth-inline-link"
            >
              Sign in
            </button>
          </p>
        </section>
      </div>
    </div>
  );
}
