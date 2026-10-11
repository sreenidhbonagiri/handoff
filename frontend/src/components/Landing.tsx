import type { MouseEvent } from "react";
import BrandLogo from "./BrandLogo";

interface Props {
  onOpenWorkspace: () => void;
}

export default function Landing({ onOpenWorkspace }: Props) {
  const open = (e: MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    onOpenWorkspace();
  };

  return (
    <div className="landing">
      <header className="landing-bar">
        <div className="landing-nav">
          <a className="logo-link" href="/" aria-label="Handoff home">
            <BrandLogo size="nav" />
          </a>
          <nav>
            <a href="#how-it-works">How it works</a>
            <a href="#why-handoff">Why Handoff</a>
            <a href="#about">About</a>
            <a className="button primary" href="/jobs" onClick={open}>
              Open workspace
            </a>
          </nav>
        </div>
      </header>

      <main>
        <section className="hero">
          <div className="hero-copy">
            <p className="hero-label">For maintenance teams</p>
            <h1>Leave a clear handoff.</h1>
            <p className="hero-lead">
              Turn spoken notes, photos, and job updates into a clear record of what’s done, what’s still
              open, and what needs to happen next—even without internet.
            </p>
            <div className="hero-actions">
              <a className="button primary large" href="/jobs" onClick={open}>
                Open workspace
              </a>
              <a className="text-link" href="#how-it-works">
                See how it works
              </a>
            </div>
            <p className="muted small hero-note">Local AI · Works offline after setup</p>
          </div>
          <aside className="product-demo" aria-label="Example workflow illustration">
            <p className="example-label">Example workflow</p>
            <div className="demo-input">
              <span className="tag">Note</span>
              <p>Replaced two filters—actually three. The rattling is still there. I’ll test it tomorrow.</p>
            </div>
            <ul className="demo-output">
              <li>
                <span className="badge reported_complete">Reported done</span>
                <div>
                  <p>3 filters replaced</p>
                  <p className="corr">Quantity corrected from 2 to 3</p>
                </div>
              </li>
              <li>
                <span className="badge unresolved">Still open</span>
                <div>
                  <p>Problem: Rattling</p>
                </div>
              </li>
              <li>
                <span className="badge planned">Planned</span>
                <div>
                  <p>Final equipment test</p>
                </div>
              </li>
            </ul>
          </aside>
        </section>

        <section id="why-handoff" className="problem">
          <p className="section-kicker">Why Handoff</p>
          <h2>The repair is only part of the job.</h2>
          <p>
            After a service visit, someone still needs to understand what changed, what wasn’t finished,
            and what to do next. Those details can get lost between quick notes, photos, and conversations.
          </p>
          <p>
            Handoff turns those observations into a record the next technician can check: completed work,
            open problems, planned tests, and the original notes they came from.
          </p>
        </section>

        <section id="how-it-works" className="workflow">
          <p className="section-kicker">How it works</p>
          <h2>From job notes to a clear next step.</h2>
          <ol className="workflow-steps">
            <li>
              <span>1</span>
              <div>
                <h3>Capture the work</h3>
                <p>Type or record a note and attach photos.</p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <h3>Review the details</h3>
                <p>Check corrections, missing information, and anything that needs confirmation.</p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <h3>Prepare the handoff</h3>
                <p>Export a report showing completed work and what remains open.</p>
              </div>
            </li>
          </ol>
        </section>

        <section className="offline">
          <div>
            <h2>Useful even when the connection isn’t.</h2>
            <p>
              After setup, this prototype keeps the core workflow on the computer running it. You can
              prepare a handoff without sending job information to a cloud AI service.
            </p>
          </div>
          <ul>
            <li>Keep capturing and processing notes without internet after setup.</li>
            <li>Speech transcription and note analysis run on the local computer.</li>
            <li>No cloud AI service is required for the core workflow.</li>
            <li>Notes and photos are stored locally, and you choose when to share an exported report.</li>
          </ul>
        </section>

        <section className="record">
          <div className="record-copy">
            <h2>A record you can check.</h2>
            <ol className="annotations">
              <li>
                <strong>Linked to the original note</strong>
                Each recorded fact stays tied to the words that produced it.
              </li>
              <li>
                <strong>Earlier values kept</strong>
                When a quantity is corrected, the previous value remains visible.
              </li>
              <li>
                <strong>Planned work stays planned</strong>
                A test scheduled for later is not treated as completed work.
              </li>
              <li>
                <strong>Open problems stay visible</strong>
                Unresolved issues remain listed until they are explicitly addressed.
              </li>
              <li>
                <strong>Unclear statements flagged</strong>
                Ambiguous or conflicting notes are marked for review instead of being guessed.
              </li>
            </ol>
          </div>
          <aside className="product-demo record-demo" aria-label="Annotated record example">
            <p className="example-label">Example record</p>
            <p className="demo-quote">“Replaced two filters—actually three.”</p>
            <ul className="demo-output">
              <li>
                <span className="badge reported_complete">Reported done</span>
                <div>
                  <p>Replace 3 × filter</p>
                  <p className="small muted">From the note above</p>
                  <p className="corr">Earlier version: 2</p>
                </div>
              </li>
              <li>
                <span className="badge unresolved">Still open</span>
                <div>
                  <p>Problem: Rattling</p>
                  <p className="small muted">Kept visible</p>
                </div>
              </li>
              <li>
                <span className="badge planned">Planned</span>
                <div>
                  <p>Final equipment test</p>
                  <p className="small muted">Not recorded as done</p>
                </div>
              </li>
              <li>
                <span className="badge pending">Please review</span>
                <div>
                  <p>Which unit was serviced?</p>
                  <p className="small muted">Flagged for confirmation</p>
                </div>
              </li>
            </ul>
          </aside>
        </section>

        <section id="about" className="about">
          <h2>Built for the person picking up the next job.</h2>
          <p>
            Handoff helps maintenance technicians turn observations into a record someone else can use. It
            brings together job notes, photos, completed work, and open questions so the next person can
            understand where things stand.
          </p>
          <p>
            Our focus is simple: useful documentation at the point of work, including places where a
            reliable internet connection isn’t available.
          </p>
        </section>

        <section className="faq">
          <h2>Questions</h2>
          <dl>
            <div>
              <dt>Does it work offline?</dt>
              <dd>Yes, after the application and local models are installed.</dd>
            </div>
            <div>
              <dt>Does the AI inspect my photos?</dt>
              <dd>No. Photos are attached as evidence; only the technician’s written caption is analyzed.</dd>
            </div>
            <div>
              <dt>Does Handoff send the report to anyone?</dt>
              <dd>No. Reports are saved locally for the user to share.</dd>
            </div>
            <div>
              <dt>Does a completed report certify equipment safety?</dt>
              <dd>No. It records reported work and checks; it does not certify equipment safety.</dd>
            </div>
          </dl>
        </section>

        <section className="final-cta">
          <h2>Make the next handoff clearer.</h2>
          <a className="button primary large" href="/jobs" onClick={open}>
            Open workspace
          </a>
        </section>
      </main>

      <footer className="landing-footer">
        <a className="logo-link" href="/" aria-label="Handoff home">
          <BrandLogo size="footer" />
        </a>
        <nav>
          <a href="#how-it-works">How it works</a>
          <a href="#why-handoff">Why Handoff</a>
          <a href="#about">About</a>
          <a href="/jobs" onClick={open}>
            Open workspace
          </a>
        </nav>
      </footer>
    </div>
  );
}
