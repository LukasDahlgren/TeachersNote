import { useEffect, useState } from "react";
import type { AuthUser, Program } from "../types";
import { register, ApiError, getPublicPrograms, updateProfileProgram } from "../api";
import ProgramPicker from "./ProgramPicker";

interface Props {
  onSignup: (user: AuthUser) => void;
  onGoToLogin: () => void;
}

const SCHOOLS = [
  { id: "SU", name: "Stockholms universitet" },
];

const cardStyle: React.CSSProperties = {
  background: "white",
  padding: "2rem",
  borderRadius: "8px",
  boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
  width: "100%",
  maxWidth: "400px",
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.5rem",
  border: "1px solid #ccc",
  borderRadius: "4px",
  fontSize: "1rem",
  boxSizing: "border-box",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  marginBottom: "0.25rem",
  fontSize: "0.875rem",
  fontWeight: 500,
};

const primaryBtnStyle = (disabled: boolean): React.CSSProperties => ({
  width: "100%",
  padding: "0.625rem",
  background: disabled ? "#93c5fd" : "#2563eb",
  color: "white",
  border: "none",
  borderRadius: "4px",
  fontSize: "1rem",
  fontWeight: 500,
  cursor: disabled ? "not-allowed" : "pointer",
});

const skipBtnStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.5rem",
  background: "none",
  border: "1px solid #d1d5db",
  borderRadius: "4px",
  fontSize: "0.875rem",
  color: "#6b7280",
  cursor: "pointer",
  marginTop: "0.5rem",
};

type Step = "credentials" | "school" | "program";

export default function SignupPage({ onSignup, onGoToLogin }: Props) {
  const [step, setStep] = useState<Step>("credentials");

  // Step 1 state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [registeredUser, setRegisteredUser] = useState<AuthUser | null>(null);

  // Step 2+3 state
  const [selectedSchool, setSelectedSchool] = useState<string | null>(null);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [programsLoading, setProgramsLoading] = useState(false);
  const [selectedProgramId, setSelectedProgramId] = useState<number | null>(null);
  const [savingProgram, setSavingProgram] = useState(false);

  useEffect(() => {
    if (step === "school") {
      setProgramsLoading(true);
      getPublicPrograms()
        .then(setPrograms)
        .catch(() => setPrograms([]))
        .finally(() => setProgramsLoading(false));
    }
  }, [step]);

  async function handleCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await register(email, password, displayName || undefined);
      setRegisteredUser(res.user);
      setStep("school");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  function handleSchoolSelect(schoolId: string) {
    setSelectedSchool(schoolId);
    setStep("program");
  }

  function handleSkipSchool() {
    onSignup(registeredUser!);
  }

  async function handleProgramSubmit() {
    if (selectedProgramId === null) {
      onSignup(registeredUser!);
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
    onSignup(registeredUser!);
  }

  function handleSkipProgram() {
    onSignup(registeredUser!);
  }

  const stepLabel = step === "credentials" ? "1 / 3" : step === "school" ? "2 / 3" : "3 / 3";

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "#f5f5f5" }}>
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1.5rem" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: 700, margin: 0 }}>Create account</h1>
          <span style={{ fontSize: "0.75rem", color: "#9ca3af", fontWeight: 500 }}>{stepLabel}</span>
        </div>

        {/* Step 1: Credentials */}
        {step === "credentials" && (
          <form onSubmit={handleCredentialsSubmit}>
            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Display name (optional)</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                style={inputStyle}
              />
            </div>
            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                style={inputStyle}
              />
            </div>
            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Password (min. 8 characters)</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                style={inputStyle}
              />
            </div>
            {error && <p style={{ color: "red", fontSize: "0.875rem", marginBottom: "0.75rem" }}>{error}</p>}
            <button type="submit" disabled={loading} style={primaryBtnStyle(loading)}>
              {loading ? "Creating account..." : "Create account"}
            </button>
          </form>
        )}

        {/* Step 2: School selection */}
        {step === "school" && (
          <div>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginBottom: "1.25rem" }}>
              Which school do you attend? This helps us show relevant content.
            </p>
            {programsLoading && (
              <p style={{ color: "#9ca3af", fontSize: "0.875rem", textAlign: "center" }}>Loading…</p>
            )}
            {!programsLoading && SCHOOLS.map((school) => (
              <button
                key={school.id}
                onClick={() => handleSchoolSelect(school.id)}
                style={{
                  width: "100%",
                  padding: "0.75rem 1rem",
                  marginBottom: "0.5rem",
                  background: selectedSchool === school.id ? "#eff6ff" : "white",
                  border: `1px solid ${selectedSchool === school.id ? "#3b82f6" : "#d1d5db"}`,
                  borderRadius: "6px",
                  textAlign: "left",
                  fontSize: "0.95rem",
                  fontWeight: 500,
                  cursor: "pointer",
                  color: "#111827",
                }}
              >
                🎓 {school.name}
              </button>
            ))}
            <button style={skipBtnStyle} onClick={handleSkipSchool}>
              Skip — I'll set this up later
            </button>
          </div>
        )}

        {/* Step 3: Program selection (SU) */}
        {step === "program" && (
          <div>
            <p style={{ color: "#6b7280", fontSize: "0.875rem", marginBottom: "1.25rem" }}>
              Select your program at Stockholms universitet. This sets up your course list automatically.
            </p>
            <div style={{ marginBottom: "1rem" }}>
              <label style={labelStyle}>Program</label>
              <ProgramPicker
                value={selectedProgramId}
                programs={programs}
                onChange={setSelectedProgramId}
                placeholder="Select your program"
              />
            </div>
            <button
              onClick={handleProgramSubmit}
              disabled={savingProgram}
              style={primaryBtnStyle(savingProgram)}
            >
              {savingProgram ? "Saving…" : selectedProgramId !== null ? "Continue" : "Continue without program"}
            </button>
            <button style={skipBtnStyle} onClick={handleSkipProgram}>
              Skip — I'll set this up later
            </button>
          </div>
        )}

        {step === "credentials" && (
          <p style={{ textAlign: "center", marginTop: "1rem", fontSize: "0.875rem", color: "#666" }}>
            Already have an account?{" "}
            <button
              onClick={onGoToLogin}
              style={{ background: "none", border: "none", color: "#2563eb", cursor: "pointer", fontSize: "0.875rem", textDecoration: "underline" }}
            >
              Sign in
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

