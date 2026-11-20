import { Check } from "lucide-react";
import type { Connector } from "../data/connectors";
import ConnectorIcon from "./ConnectorIcon";

interface Props {
  connector: Connector;
  connected: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
}

export default function ConnectorCard({ connector, connected, onConnect, onDisconnect }: Props) {
  return (
    <article className="flex flex-col justify-between gap-5 rounded-2xl border border-line bg-white p-5">
      <div className="flex items-start gap-4">
        <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl border border-line bg-paper">
          <ConnectorIcon id={connector.id} size={26} />
        </div>
        <div className="min-w-0">
          <h3 className="text-[15px] font-medium leading-6">{connector.name}</h3>
          <p className="mt-0.5 text-sm leading-5 text-muted">{connector.description}</p>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        {connected ? (
          <>
            <button
              onClick={onDisconnect}
              className="rounded-lg px-3 py-1.5 text-sm text-muted transition-colors hover:bg-hover hover:text-ink"
            >
              Disconnect
            </button>
            <span className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm font-medium text-ok">
              <Check className="h-4 w-4" />
              Connected
            </span>
          </>
        ) : (
          <button
            onClick={onConnect}
            className="rounded-lg bg-ink px-4 py-1.5 text-sm font-medium text-paper transition-colors hover:bg-ink/85"
          >
            Connect
          </button>
        )}
      </div>
    </article>
  );
}
