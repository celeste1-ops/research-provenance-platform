import { useState } from "react";
import { api } from "../api";

export function Setup({ onDone }: { onDone: () => void }) {
  const [label, setLabel] = useState("");
  const [project, setProject] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createIdentity(label);
      if (project.trim()) await api.createProject(project.trim());
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="setup">
      <form className="card" onSubmit={submit}>
        <h1>Set up your research record</h1>
        <p>
          This creates your <b>signing key</b>, kept in the macOS Keychain on this computer. Every record you make
          is signed with it. A signature shows that the same key signed all records — it does not identify a person.
        </p>
        <label>
          Author label <span className="muted">(shown as a self-declaration)</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Your name or pen name" required />
        </label>
        <label>
          First research project
          <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="e.g. FSF" />
        </label>
        <p className="note">
          Back up the key after your first record (you will be reminded). If the key is lost, new records start a new
          identity; old records stay verifiable.
        </p>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy || !label.trim()}>
          Create signing key
        </button>
      </form>
    </div>
  );
}
