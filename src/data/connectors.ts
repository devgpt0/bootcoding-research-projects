export type ConnectorId = "google-forms" | "google-calendar" | "google-drive" | "microsoft-outlook";

export interface Connector {
  id: ConnectorId;
  name: string;
  description: string;
  permissions: string[];
}

export const CONNECTORS: Connector[] = [
  {
    id: "google-forms",
    name: "Google Forms",
    description: "Access and manage your Google Forms.",
    permissions: ["View your forms and responses", "Create and edit forms"],
  },
  {
    id: "google-calendar",
    name: "Google Calendar",
    description: "View and manage your calendar events.",
    permissions: ["View your calendars and events", "Create and update events"],
  },
  {
    id: "google-drive",
    name: "Google Drive",
    description: "Access and search your files.",
    permissions: ["Search and read your files", "See file names and sharing details"],
  },
  {
    id: "microsoft-outlook",
    name: "Microsoft Outlook",
    description: "Connect your Outlook email and calendar.",
    permissions: ["Read your email and calendar", "Draft messages for you to review"],
  },
];
