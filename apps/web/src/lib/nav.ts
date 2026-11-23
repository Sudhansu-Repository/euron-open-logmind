import {
  ActivityIcon,
  BellRingIcon,
  BugIcon,
  LayoutDashboardIcon,
  RadioIcon,
  ScrollTextIcon,
  SettingsIcon,
  SparklesIcon,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** The dashboard surfaces (docs/PLAN.md "Screens"), grouped by what an engineer is doing. */
export const NAV: NavGroup[] = [
  {
    label: "Observe",
    items: [
      { href: "/overview", label: "Overview", icon: LayoutDashboardIcon },
      { href: "/live", label: "Live logs", icon: RadioIcon },
      { href: "/logs", label: "Log explorer", icon: ScrollTextIcon },
      { href: "/services", label: "Services", icon: ActivityIcon },
    ],
  },
  {
    label: "Investigate",
    items: [
      { href: "/errors", label: "Errors", icon: BugIcon },
      { href: "/investigations", label: "AI investigations", icon: SparklesIcon },
    ],
  },
  {
    label: "Configure",
    items: [
      { href: "/alerts", label: "Alerts", icon: BellRingIcon },
      { href: "/settings", label: "Settings", icon: SettingsIcon },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

/** The nav item a path belongs to: the longest matching prefix. */
export function activeNavItem(pathname: string): NavItem | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  return NAV_ITEMS.filter((i) => path === i.href || path.startsWith(`${i.href}/`)).sort(
    (a, b) => b.href.length - a.href.length
  )[0];
}

export function isActive(item: NavItem, pathname: string): boolean {
  return activeNavItem(pathname)?.href === item.href;
}
