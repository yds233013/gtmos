import {
  Activity,
  Building2,
  FlaskConical,
  Gauge,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  Megaphone,
  MessageSquareText,
  Radio,
  Route,
  Settings,
  ShieldCheck,
  Stethoscope,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Revenue",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/accounts", label: "Accounts", icon: Building2 },
      { href: "/contacts", label: "Contacts", icon: Users },
      { href: "/signals", label: "Signals", icon: Radio },
      { href: "/approvals", label: "Approvals", icon: Inbox },
      { href: "/pipeline", label: "Pipeline", icon: KanbanSquare },
    ],
  },
  {
    section: "Go-to-market",
    items: [
      { href: "/campaigns", label: "Campaigns", icon: Megaphone },
      { href: "/experiments", label: "Experiments", icon: FlaskConical },
      { href: "/copilot", label: "Copilot", icon: MessageSquareText },
    ],
  },
  {
    section: "Systems",
    items: [
      { href: "/workflows", label: "Workflows", icon: Workflow },
      { href: "/routing", label: "Routing", icon: Route },
      { href: "/data-quality", label: "Data Quality", icon: ShieldCheck },
      { href: "/operations", label: "Operations", icon: Activity },
      { href: "/stack-inspector", label: "Stack Inspector", icon: Stethoscope },
      { href: "/scoring", label: "ICP & Scoring", icon: Gauge },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];
