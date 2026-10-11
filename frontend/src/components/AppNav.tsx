import { IconClipboard, IconHome, IconMap } from "../icons";

export type NavPlace = "home" | "jobs" | "map";

interface Props {
  current: NavPlace;
  onHome: () => void;
  onJobs?: () => void;
  onMap?: () => void;
}

export default function AppNav(props: Props) {
  return (
    <nav className="app-nav-group" aria-label="Handoff">
      <a
        className={props.current === "home" ? "app-nav is-current" : "app-nav"}
        href="/"
        aria-current={props.current === "home" ? "page" : undefined}
        onClick={(e) => {
          e.preventDefault();
          props.onHome();
        }}
      >
        <IconHome />
        Home
      </a>
      <a
        className={props.current === "jobs" ? "app-nav is-current" : "app-nav"}
        href="/jobs"
        aria-current={props.current === "jobs" ? "page" : undefined}
        onClick={(e) => {
          e.preventDefault();
          props.onJobs?.();
        }}
      >
        <IconClipboard />
        Jobs
      </a>
      <a
        className={props.current === "map" ? "app-nav is-current" : "app-nav"}
        href="/map"
        aria-current={props.current === "map" ? "page" : undefined}
        onClick={(e) => {
          e.preventDefault();
          props.onMap?.();
        }}
      >
        <IconMap />
        Site map
      </a>
    </nav>
  );
}
