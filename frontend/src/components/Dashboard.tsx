import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { pendingFacts, unresolvedIssues } from "../closeout";
import { compactEquipment, compactMissing, equipmentLabel, jobLocation, jobTitle } from "../format";
import type { JobListItem } from "../types";
import BrandLogo from "./BrandLogo";

const PAGE_SIZE = 10;

type Filter = "all" | "open" | "review";

interface Props {
  items: JobListItem[];
  onOpen: (id: number) => void;
  onCreate: (title: string, location: string) => void;
  onHome: () => void;
  creating: boolean;
}

function matches(item: JobListItem, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const title = item.job.title;
  const location = item.job.location ?? "";
  const equipment = equipmentLabel(item);
  return [title, jobTitle(title), location, jobLocation(location), equipment, compactEquipment(item)].some((value) =>
    value.toLowerCase().includes(q),
  );
}

function updatedLabel(item: JobListItem): string {
  const raw = item.job.updated_at || item.job.created_at;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function Dashboard(props: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState(false);
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const titleRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    return props.items.filter((item) => {
      if (!matches(item, query)) return false;
      if (filter === "open") return unresolvedIssues(item).length > 0;
      if (filter === "review") return pendingFacts(item).length > 0;
      return true;
    });
  }, [props.items, query, filter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const slice = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const from = filtered.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1;
  const to = Math.min(safePage * PAGE_SIZE, filtered.length);

  useEffect(() => {
    setPage(1);
  }, [query, filter]);

  useEffect(() => {
    if (dialog) titleRef.current?.focus();
  }, [dialog]);

  useEffect(() => {
    if (!dialog) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDialog(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dialog]);

  const submitNew = (e: FormEvent) => {
    e.preventDefault();
    props.onCreate(title, location);
  };

  return (
    <div className="dashboard">
      <header className="topbar">
        <div className="job-heading">
          <a
            className="logo-link home-link"
            href="/"
            aria-label="Handoff home"
            onClick={(e) => {
              e.preventDefault();
              props.onHome();
            }}
          >
            <BrandLogo size="app" />
          </a>
          <h1>Jobs</h1>
        </div>
        <div className="topbar-right">
          <a
            className="muted small home-link"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              props.onHome();
            }}
          >
            Overview
          </a>
          <button className="primary" type="button" onClick={() => setDialog(true)}>
            New job
          </button>
        </div>
      </header>
      <main className="dashboard-body compact-dash">
        <div className="dash-toolbar">
          <label className="search-field">
            <span className="muted small">Search</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Title, equipment ID, or location"
            />
          </label>
          <div className="filters" role="group" aria-label="Filter jobs">
            <button type="button" className={filter === "all" ? "active" : undefined} onClick={() => setFilter("all")}>
              All jobs
            </button>
            <button type="button" className={filter === "open" ? "active" : undefined} onClick={() => setFilter("open")}>
              With open issues
            </button>
            <button type="button" className={filter === "review" ? "active" : undefined} onClick={() => setFilter("review")}>
              Needs review
            </button>
          </div>
        </div>

        {props.items.length === 0 ? (
          <p className="empty-jobs">Your jobs will appear here. Start by adding your first job.</p>
        ) : filtered.length === 0 ? (
          <p className="empty-jobs">No jobs match that search.</p>
        ) : (
          <>
            <table className="job-table">
              <thead>
                <tr>
                  <th>Job title</th>
                  <th>Equipment</th>
                  <th>Location</th>
                  <th>Open issues</th>
                  <th>Needs review</th>
                  <th>Updated</th>
                  <th>Open</th>
                </tr>
              </thead>
              <tbody>
                {slice.map((item) => {
                  const open = unresolvedIssues(item).length;
                  const review = pendingFacts(item).length;
                  return (
                    <tr key={item.job.id}>
                      <td data-label="Job title">{jobTitle(item.job.title)}</td>
                      <td data-label="Equipment">{compactEquipment(item)}</td>
                      <td data-label="Location">{compactMissing(item.job.location)}</td>
                      <td data-label="Open issues">{open}</td>
                      <td data-label="Needs review">{review}</td>
                      <td data-label="Updated">{updatedLabel(item)}</td>
                      <td data-label="">
                        <button type="button" className="primary" onClick={() => props.onOpen(item.job.id)}>
                          Open
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div className="pager">
              <p className="muted small">
                {from}–{to} of {filtered.length}
              </p>
              <div className="row">
                <button type="button" disabled={safePage <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  Previous
                </button>
                <button
                  type="button"
                  disabled={safePage >= pageCount}
                  onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </main>

      {dialog && (
        <div
          className="dialog-overlay"
          role="presentation"
          onClick={(e) => {
            if (e.target === e.currentTarget) setDialog(false);
          }}
        >
          <form className="dialog" role="dialog" aria-labelledby="new-job-title" onSubmit={submitNew}>
            <h2 id="new-job-title">New job</h2>
            <div className="job-fields">
              <label>
                <span className="muted small">Title</span>
                <input
                  ref={titleRef}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Untitled service visit"
                  maxLength={200}
                />
              </label>
              <label>
                <span className="muted small">Location</span>
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Not added"
                  maxLength={200}
                />
              </label>
            </div>
            <div className="row">
              <button className="primary" type="submit" disabled={props.creating}>
                {props.creating ? "Starting a new job…" : "New job"}
              </button>
              <button type="button" onClick={() => setDialog(false)}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
