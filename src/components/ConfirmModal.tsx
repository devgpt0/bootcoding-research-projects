import { useEffect } from "react";
import { ShieldCheck } from "lucide-react";
import type { Connector } from "../data/connectors";
import ConnectorIcon from "./ConnectorIcon";

interface Props {
  connector: Connector;
  action: "connect" | "disconnect";
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({ connector, action, onConfirm, onCancel }: Props) {
  const isConnect = action === "connect";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 animate-fade bg-ink/40" onClick={onCancel} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className="relative w-full max-w-md animate-pop rounded-2xl border border-line bg-white p-6 shadow-xl"
      >
        <div className="mb-4 grid h-12 w-12 place-items-center rounded-xl border border-line bg-paper">
          <ConnectorIcon id={connector.id} size={26} />
        </div>

        <h2 id="modal-title" className="font-serif text-xl">
          {isConnect ? `Connect ${connector.name}?` : `Disconnect ${connector.name}?`}
        </h2>

        {isConnect ? (
          <>
            <p className="mt-2 text-sm text-muted">Claude will be able to:</p>
            <ul className="mt-2 space-y-2">
              {connector.permissions.map((p) => (
                <li key={p} className="flex items-start gap-2 text-sm">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
                  {p}
                </li>
              ))}
            </ul>
            <p className="mt-4 rounded-lg bg-paper px-3 py-2 text-xs text-muted">
              This is a demo. No sign-in happens and no data is shared.
            </p>
          </>
        ) : (
          <p className="mt-2 text-sm text-muted">
            Claude will no longer have access to {connector.name}. You can reconnect at any time.
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-line px-4 py-2 text-sm hover:bg-hover">
            Cancel
          </button>
          <button
            onClick={onConfirm}
            autoFocus
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-paper hover:bg-ink/85"
          >
            {isConnect ? "Connect" : "Disconnect"}
          </button>
        </div>
      </div>
    </div>
  );
}
