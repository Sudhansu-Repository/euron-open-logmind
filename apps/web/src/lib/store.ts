"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

/**
 * Persisted UI preferences only (never server data): the sidebar state and the project
 * the person last scoped the dashboard to. Rehydrated after mount so the first client
 * render matches the server render. The theme itself is persisted by next-themes.
 */
interface UiPrefs {
  sidebarCollapsed: boolean;
  /** "" means every project. */
  projectId: string;
  toggleSidebar: () => void;
  setProjectId: (id: string) => void;
}

function safeStorage(): Storage {
  try {
    return window.localStorage;
  } catch {
    const mem = new Map<string, string>();
    return {
      get length() {
        return mem.size;
      },
      clear: () => mem.clear(),
      getItem: (k) => mem.get(k) ?? null,
      key: (i) => Array.from(mem.keys())[i] ?? null,
      removeItem: (k) => void mem.delete(k),
      setItem: (k, v) => void mem.set(k, v),
    };
  }
}

export const useUiPrefs = create<UiPrefs>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      projectId: "",
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setProjectId: (id) => set({ projectId: id }),
    }),
    {
      name: "logmind.ui",
      version: 1,
      skipHydration: true,
      storage: createJSONStorage(safeStorage),
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, projectId: s.projectId }),
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<UiPrefs>;
        return {
          ...current,
          sidebarCollapsed:
            typeof p.sidebarCollapsed === "boolean" ? p.sidebarCollapsed : current.sidebarCollapsed,
          projectId: typeof p.projectId === "string" ? p.projectId : current.projectId,
        };
      },
    }
  )
);
