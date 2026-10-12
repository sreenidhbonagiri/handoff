import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Landing from "./components/Landing";
import "./styles.css";

const base = import.meta.env.BASE_URL || "/";
const normalizedBase = base.replace(/\/+$/, "") || "/";
const path = window.location.pathname.replace(/\/+$/, "") || "/";
if (path !== normalizedBase && !path.endsWith("/index.html")) {
  const next = base.endsWith("/") ? base : `${base}/`;
  window.history.replaceState({}, "", `${next}${window.location.hash}`);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Landing />
  </StrictMode>,
);
