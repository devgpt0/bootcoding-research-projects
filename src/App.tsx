import { useEffect, useMemo, useState } from "react";
import SearchBar from "./components/SearchBar";
import ConnectorCard from "./components/ConnectorCard";
import ConfirmModal from "./components/ConfirmModal";
import { CONNECTORS, type ConnectorId } from "./data/connectors";

interface Pending {
  id: ConnectorId;
  action: "connect" | "disconnect";
}

export default function App() {
  const [query, setQuery] = useState("");
  const [connected, setConnected] = useState<Record<ConnectorId, boolean>>({
    "google-forms": false,
    "google-calendar": false,
    "google-drive": false,
    "microsoft-outlook": false,
  });
  const [pending, setPending] = useState<Pending | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? CONNECTORS.filter((c) => c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q))
      : CONNECTORS;
  }, [query]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2500);
    return () => clearTimeout(t);
  }, [toast]);

  const pendingConnector = pending ? CONNECTORS.find((c) => c.id === pending.id) : undefined;

  const confirm = () => {
    if (!pending || !pendingConnector) return;
    const next = pending.action === "connect";
    setConnected((s) => ({ ...s, [pending.id]: next }));
    setToast(`${pendingConnector.name} ${next ? "connected" : "disconnected"}`);
    setPending(null);
  };

    return (
    <div className="flex h-full">
      <main className="flex flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-5 pt-10 pb-10 sm:px-8 md:pt-16">
          <h1 className="text-center font-serif text-[32px] leading-tight tracking-tight">Connectors</h1>
          <p className="mt-2 text-center text-[15px] text-muted">
            Connect your tools and services to work seamlessly.
          </p>

          <div className="mt-8">
            <SearchBar value={query} onChange={setQuery} />
          </div>

          {visible.length > 0 ? (
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {visible.map((c) => (
                <ConnectorCard
                  key={c.id}
                  connector={c}
                  connected={connected[c.id]}
                  onConnect={() => setPending({ id: c.id, action: "connect" })}
                  onDisconnect={() => setPending({ id: c.id, action: "disconnect" })}
                />
              ))}
            </div>
          ) : (
            <div className="mt-6 rounded-2xl border border-dashed border-line px-6 py-12 text-center">
              <p className="text-sm font-medium">No connectors found</p>
              <p className="mt-1 text-sm text-muted">Try a different name, like “Drive” or “Outlook”.</p>
            </div>
          )}
        </div>
      </main>

      {pending && pendingConnector && (
        <ConfirmModal
          connector={pendingConnector}
          action={pending.action}
          onConfirm={confirm}
          onCancel={() => setPending(null)}
        />
      )}

      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
        {toast && (
          <div className="animate-pop rounded-lg bg-ink px-4 py-2 text-sm text-paper shadow-lg">{toast}</div>
        )}
      </div>
    </div>
  );
}