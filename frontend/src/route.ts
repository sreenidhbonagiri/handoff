export type Route =
  | { name: "landing" }
  | { name: "dashboard" }
  | { name: "map" }
  | { name: "job"; id: number };

export function parseRoute(path = window.location.pathname): Route {
  const job = path.match(/^\/jobs\/(\d+)\/?$/);
  if (job) return { name: "job", id: Number(job[1]) };
  if (path === "/jobs" || path === "/jobs/") return { name: "dashboard" };
  if (path === "/map" || path === "/map/") return { name: "map" };
  return { name: "landing" };
}

export function jobPath(id: number): string {
  return `/jobs/${id}`;
}

export function dashboardPath(): string {
  return "/jobs";
}

export function mapPath(): string {
  return "/map";
}

export function landingPath(): string {
  return "/";
}
