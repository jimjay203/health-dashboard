import { useEffect, useState } from "react";

const STORAGE_KEY = "health-dashboard-sidebar-collapsed";

function readStoredCollapsed(): boolean {
  return localStorage.getItem(STORAGE_KEY) === "true";
}

export function useSidebarCollapsed(): [boolean, (collapsed: boolean) => void] {
  const [collapsed, setCollapsed] = useState<boolean>(readStoredCollapsed);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(collapsed));
  }, [collapsed]);

  return [collapsed, setCollapsed];
}
