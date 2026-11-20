import { FolderOpen, LayoutGrid, MessageSquare, Plug, Settings, SquarePen, X } from "lucide-react";
import type { ComponentType } from "react";

interface NavItem {
  label: string;
  icon: ComponentType<{ className?: string }>;
  active?: boolean;
}

const NAV: NavItem[] = [
  { label: "New chat", icon: SquarePen },
  { label: "Chats", icon: MessageSquare },
  { label: "Projects", icon: FolderOpen },
  { label: "Artifacts", icon: LayoutGrid },
  { label: "Connectors", icon: Plug, active: true },
];

interface Props {
  open: boolean;
  onClose: () => void;
}

function SidebarContent({ onClose }: { onClose?: () => void }) {
  return (
    <div className="flex h-full flex-col px-3 py-4">
      <div className="mb-4 flex items-center justify-between px-2">
        <span className="font-serif text-[22px] tracking-tight">Claude</span>
        {onClose && (
          <button onClick={onClose} aria-label="Close menu" className="rounded-md p-1.5 text-muted hover:bg-hover">
            <X className="h-5 w-5" />
          </button>
        )}
      </div>

      <nav aria-label="Main" className="flex flex-col gap-0.5">
        {NAV.map(({ label, icon: Icon, active }) => (
          <a
            key={label}
            href="#"
            onClick={(e) => e.preventDefault()}
            aria-current={active ? "page" : undefined}
            className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${
              active ? "bg-hover font-medium text-ink" : "text-ink/80 hover:bg-hover"
            }`}
          >
            <Icon className="h-[18px] w-[18px]" />
            {label}
          </a>
        ))}
      </nav>

      <div className="mt-auto flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm text-ink/80 hover:bg-hover">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-ink text-xs font-medium text-paper">U</span>
        <span className="flex-1 truncate">Your account</span>
        <Settings className="h-4 w-4 text-muted" />
      </div>
    </div>
  );
}

export default function Sidebar({ open, onClose }: Props) {
  return (
    <>
      <aside className="hidden w-64 shrink-0 border-r border-line bg-sidebar md:block">
        <SidebarContent />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 animate-fade bg-ink/30" onClick={onClose} />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85%] animate-fade border-r border-line bg-sidebar">
            <SidebarContent onClose={onClose} />
          </aside>
        </div>
      )}
    </>
  );
}
