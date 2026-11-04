import { useEffect, useState } from "react";

export type Route =
  | { page: "home" }
  | { page: "setup"; mode: "debate" | "meeting" | "sales" }
  | { page: "bout"; id: string }
  | { page: "record"; mode: "debate" | "meeting" | "sales" };

const MODES = ["debate", "meeting", "sales"] as const;

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const mode = MODES.find((m) => m === parts[1]);
  if (parts[0] === "new" && mode) return { page: "setup", mode };
  if (parts[0] === "bout" && parts[1] && /^[a-f0-9]{16}$/.test(parts[1])) return { page: "bout", id: parts[1] };
  if (parts[0] === "record") return { page: "record", mode: mode ?? "debate" };
  return { page: "home" };
}

export const href = (route: Route): string => {
  switch (route.page) {
    case "home":
      return "#/";
    case "setup":
      return `#/new/${route.mode}`;
    case "bout":
      return `#/bout/${route.id}`;
    case "record":
      return `#/record/${route.mode}`;
  }
};

export const go = (route: Route) => {
  window.location.hash = href(route);
};

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const on = () => {
      setRoute(parse(window.location.hash));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
