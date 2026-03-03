import { useEffect, useState } from "react";
import type { AuthUser, Program } from "../types";
import { register, ApiError, getPublicPrograms, updateProfileProgram } from "../api";
import ProgramPicker from "./ProgramPicker";
import AuthHero from "./AuthHero";
import "./AuthPages.css";

interface Props {
  onSignup: (user: AuthUser) => void;
  onGoToLogin: () => void;
}

const SCHOOLS = [
  { id: "SU", name: "Stockholms universitet", hasPrograms: true },
] as const;

type Step = "credentials" | "profile";

export default function SignupPage({ onSignup, onGoToLogin }: Props) {
  const [step, setStep] = useState<Step>("credentials");

  // Step 1 state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [registeredUser, setRegisteredUser] = useState<AuthUser | null>(null);

  // Step 2 state
  const [selectedSchool, setSelectedSchool] = useState<string | null>(null);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [programsLoading, setProgramsLoading] = useState(false);
  const [selectedProgramId, setSelectedProgramId] = useState<number | null>(null);
  const [savingProgram, setSavingProgram] = useState(false);

  useEffect(() => {
    if (step !== "profile") return;
    setProgramsLoading(true);
    getPublicPrograms()
      .then(setPrograms)
      .catch(() => setPrograms([]))
      .finally(() => setProgramsLoading(false));
  }, [step]);

  async function handleCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await register(email, password, displayName || undefined);
      setRegisteredUser(res.user);
      setStep("profile");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  function handleSchoolSelect(schoolId: string) {
    const nextSchool = selectedSchool === schoolId ? null : schoolId;
    setSelectedSchool(nextSchool);
    const school = SCHOOLS.find((s) => s.id === nextSchool);
    if (!school?.hasPrograms) {
      setSelectedProgramId(null);
    }
  }

  async function handleProfileSubmit() {
    if (!registeredUser) return;
    if (selectedProgramId === null) {
      onSignup(registeredUser);
      return;
    }

    setSavingProgram(true);
    try {
      await updateProfileProgram(selectedProgramId);
    } catch {
      // Non-fatal — user can update later from profile
    } finally {
      setSavingProgram(false);
    }
    onSignup(registeredUser);
  }

  const stepLabel = step === "credentials" ? "1 / 2" : "2 / 2";

  return (
    <div className="auth-page">
      <div className="auth-page__shape auth-page__shape--one" aria-hidden="true" />
      <div className="auth-page__shape auth-page__shape--two" aria-hidden="true" />

      <div className="auth-shell">
        <AuthHero
          title="Create your study workspace."
          text="Set up your account and optionally connect your school profile to get more relevant content."
          bullets={[
            "Organize lecture uploads in one place",
            "Keep notes aligned with slide content",
            "Customize course context anytime later",
          ]}
        />

        <section className="auth-card" aria-labelledby="signup-title">
          <div className="auth-card__head">
            <div>
              <h1 id="signup-title" className="auth-card__title">Create account</h1>
              <p className="auth-card__subtitle">
                {step === "credentials"
                  ? "Start with your sign-in details."
                  : "Optional profile setup for better recommendations."}
              </p>
            </div>
            <span className="auth-step-badge">{stepLabel}</span>
          </div>

          {step === "credentials" && (
            <form className="auth-form" onSubmit={handleCredentialsSubmit}>
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
                  {loading ? "Creating account..." : "Continue"}
                </button>
              </div>
            </form>
          )}

          {step === "profile" && (() => {
            const selectedSchoolData = SCHOOLS.find((s) => s.id === selectedSchool) ?? null;
            return (
              <div className="auth-program-shell">
                <div className="auth-field">
                  <label className="auth-label">School (optional)</label>
                  <div className="auth-choice-group">
                    {SCHOOLS.map((school) => (
                      <button
                        key={school.id}
                        type="button"
                        className={`auth-choice${selectedSchool === school.id ? " auth-choice--selected" : ""}`}
                        onClick={() => handleSchoolSelect(school.id)}
                        aria-pressed={selectedSchool === school.id}
                      >
                        🎓 {school.name}
                      </button>
                    ))}
                  </div>
                </div>

                {selectedSchoolData?.hasPrograms && (
                  <div className="auth-field">
                    <label className="auth-label" htmlFor="signup-program-picker">Program (optional)</label>
                    <ProgramPicker
                      id="signup-program-picker"
                      value={selectedProgramId}
                      programs={programs}
                      onChange={setSelectedProgramId}
                      disabled={programsLoading}
                      placeholder={programsLoading ? "Loading programs..." : "Select your program"}
                    />
                  </div>
                )}

                {!selectedSchoolData?.hasPrograms && (
                  <p className="auth-helper">Select your school to optionally set a program now.</p>
                )}
                {selectedSchoolData?.hasPrograms && programsLoading && (
                  <p className="auth-helper">Loading program options...</p>
                )}
                {selectedSchoolData?.hasPrograms && !programsLoading && programs.length === 0 && (
                  <p className="auth-helper">No programs available right now. You can set this later in your profile.</p>
                )}

                <div className="auth-row">
                  <button
                    type="button"
                    disabled={savingProgram}
                    className="auth-btn"
                    onClick={handleProfileSubmit}
                  >
                    {savingProgram
                      ? "Saving..."
                      : selectedProgramId !== null
                        ? "Save and continue"
                        : "Continue without program"}
                  </button>
                  <button
                    type="button"
                    className="auth-btn-secondary"
                    onClick={handleProfileSubmit}
                    disabled={savingProgram}
                  >
                    Skip for now
                  </button>
                </div>
              </div>
            );
          })()}

          {step === "credentials" && (
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
          )}
        </section>
      </div>
    </div>
  );
}
