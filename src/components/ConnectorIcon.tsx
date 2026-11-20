import type { ConnectorId } from "../data/connectors";

interface Props {
  id: ConnectorId;
  size?: number;
}

export default function ConnectorIcon({ id, size = 28 }: Props) {
  const common = { width: size, height: size, "aria-hidden": true as const };

  switch (id) {
    case "google-forms":
      return (
        <svg viewBox="0 0 48 48" {...common}>
          <path d="M10 6a4 4 0 0 1 4-4h14l10 10v30a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4z" fill="#7248B9" />
          <path d="M28 2l10 10h-7a3 3 0 0 1-3-3z" fill="#B39DDB" />
          <rect x="16" y="20" width="4" height="4" rx="1" fill="#fff" />
          <rect x="23" y="20" width="10" height="4" rx="1" fill="#fff" />
          <rect x="16" y="28" width="4" height="4" rx="1" fill="#fff" />
          <rect x="23" y="28" width="10" height="4" rx="1" fill="#fff" />
          <rect x="16" y="36" width="4" height="4" rx="1" fill="#fff" />
          <rect x="23" y="36" width="10" height="4" rx="1" fill="#fff" />
        </svg>
      );
    case "google-calendar":
      return (
        <svg viewBox="0 0 48 48" {...common}>
          <rect x="6" y="6" width="36" height="36" rx="4" fill="#fff" stroke="#DADCE0" />
          <path d="M6 10a4 4 0 0 1 4-4h28a4 4 0 0 1 4 4v6H6z" fill="#4285F4" />
          <path d="M34 42h4a4 4 0 0 0 4-4v-4h-8z" fill="#EA4335" />
          <path d="M42 34v-4h-8v4z" fill="#FBBC04" />
          <path d="M6 34h8v8h-4a4 4 0 0 1-4-4z" fill="#34A853" />
          <rect x="14" y="34" width="20" height="8" fill="#34A853" opacity="0" />
          <text x="24" y="33" textAnchor="middle" fontSize="15" fontWeight="600" fill="#1A73E8" fontFamily="Arial, sans-serif">31</text>
        </svg>
      );
    case "google-drive":
      return (
        <svg viewBox="0 0 87.3 78" {...common}>
          <path d="M6.6 66.85l3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da" />
          <path d="M43.65 25L29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0-1.2 4.5h27.5z" fill="#00ac47" />
          <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 11.5z" fill="#ea4335" />
          <path d="M43.65 25L57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d" />
          <path d="M59.8 53H27.5L13.75 76.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc" />
          <path d="M73.4 26.5l-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3L43.65 25 59.8 53h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00" />
        </svg>
      );
    case "microsoft-outlook":
      return (
        <svg viewBox="0 0 48 48" {...common}>
          <rect x="16" y="9" width="28" height="30" rx="3" fill="#28A8EA" />
          <path d="M16 15l14 9 14-9v-2a4 4 0 0 0-4-4H20a4 4 0 0 0-4 4z" fill="#0F6CBD" opacity=".55" />
          <path d="M16 18l14 9 14-9" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
          <rect x="3" y="12" width="26" height="24" rx="3.5" fill="#0F6CBD" />
          <ellipse cx="16" cy="24" rx="6" ry="6.6" fill="none" stroke="#fff" strokeWidth="3.2" />
        </svg>
      );
  }
}
