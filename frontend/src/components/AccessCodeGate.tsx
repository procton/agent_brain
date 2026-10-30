// Access-code gate: the local dashboard access code is submitted in the
// request body (never a URL) in exchange for an HttpOnly session cookie.
// The code itself is printed by the backend at startup and stored in the
// application data directory; it is never embedded in frontend assets.

import { useState } from "react";
import { loginWithCode } from "../api/client";

export function AccessCodeGate(props: { onSuccess: () => void; authRequired: boolean }) {
  const { onSuccess, authRequired } = props;
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <div className="state state-auth" role="dialog" aria-label="Dashboard access">
      <h1>Dashboard access code</h1>
      {authRequired ? (
        <p>enter the dashboard access code again to continue.</p>
      ) : (
        <p>Enter the access code shown by the backend at startup.</p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          loginWithCode(code.trim())
            .then(() => onSuccess())
            .catch((err: Error) => setError(err.message))
            .finally(() => setBusy(false));
        }}
      >
        <input
          aria-label="Access code"
          type="text"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          autoComplete="off"
          autoFocus
        />
        <button type="submit" disabled={busy || code.trim().length === 0}>
          Unlock dashboard
        </button>
      </form>
      {error ? <p role="alert">{error}</p> : null}
      <p className="state-note">
        The code lives in the local data directory (dashboard_code, 0600). It is
        only sent in this request body — never in URLs or page assets.
      </p>
    </div>
  );
}
