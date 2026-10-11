# FieldPilot — AGI prize build brief

Prepared for Sreenidh Bonagiri and one teammate • c0mpiled-15, October 11, 2026
Status: proposed implementation and evaluation plan. No application has been built or benchmarked in this brief.

## Product decision

Build Track 1B. Target the AGI on-device intelligence award first, while retaining a credible overall podium entry. This is a strategy, not a prediction of winning odds. Entrant quality, sponsor-specific judging criteria, laptop eligibility, and prize stacking are unconfirmed.

**FieldPilot is an offline job-closeout assistant for field technicians. It turns spoken observations into evidence-linked records, reconciles corrections, checks a supplied procedure, and asks what is missing before drafting the final report.**

Use one narrow example: a facilities maintenance service visit. The initial buyer hypothesis is a small facilities or maintenance team whose technicians document jobs after the work. Validate that hypothesis with a brief conversation; do not present it as established demand.

Map the project to YC Fall 2026's “New Operating Systems for the Physical World.” Describe it as a focused entry point into that category, not an operating system for every worker.

## The differentiating mechanism

A useful chain is: observe → interpret → check → ask → update → draft.

1. Capture a short spoken observation and its timestamped transcript locally.
2. The local language model extracts candidate facts, corrections, negations, planned actions, and unresolved issues into a strict schema.
3. Application code validates source references and applies allowed state changes.
4. A supplied checklist determines which required evidence is present, missing, or contradictory.
5. The assistant asks one high-priority follow-up question.
6. The answer updates the job state and generates a reviewable report.

The product must distinguish “reported complete,” “planned,” “explicitly not complete,” “not recorded,” and “conflicting.” Missing evidence does not establish that work was not performed. A transcript quotation supports what someone said; it does not independently verify the real-world work.

The application may create a local follow-up ticket when an unresolved issue remains. This is a real local action, stored on the device, not a mock claim of sending a ticket to an external service.

## Build priorities

| Priority | Capability | Definition of done |
|---|---|---|
| P0 | Local text-to-job workflow | New observations produce structured facts and a reviewable report without internet access |
| P0 | Corrections and task state | Explicit corrections supersede old values; planned work never automatically becomes completed work |
| P0 | Evidence references | Clicking a field opens its original source, quotation, and timestamp when available |
| P0 | Checklist and follow-up | Supplied requirements produce missing/conflicting evidence items and a useful next question |
| P0 | Local voice capture | Push-to-talk audio passes through local transcription; transcript can be corrected |
| P0 | Review and export | User can edit facts and export printable HTML plus JSON; unfinished work remains visible |
| P0 | Offline demonstration | New input, follow-up, state update, and export all work after internet disconnection |
| P1 | Camera label cross-check | Local OCR extracts a printed asset ID; mismatch with the current job requests confirmation |
| P1 | Small document retrieval | Search a local plain-text procedure and show the exact supporting section |
| P2 | Local follow-up ticket | Store a reviewed ticket for an unresolved issue with linked sources |
| P2 | Playback and history | Open audio evidence and display superseded facts with undo |

P1 camera is the first stretch upgrade. Once the voice workflow is reliable, it adds another useful source of evidence. It must be described accurately as printed-label OCR, not a model diagnosing equipment from images.

Avoid parallel feature work that delays the integrated P0 flow. General visual inspection, acoustic fault diagnosis, model fine-tuning, cloud synchronization, mobile packaging, authentication, and multiple trades are beyond this event's scope. MongoDB is not a requirement for this design; SQLite fits its offline core.

## One demonstrable physical workflow

Bring a printed asset label, a simple object to stand in for a facility asset, and a one-page sample closeout procedure. A desk fan is an example; the workflow does not require operating or repairing a live appliance.

Clearly identify the procedure as a sample demonstration procedure rather than manufacturer guidance.

Suggested demo checklist:
- Asset ID confirmed.
- Completed action and parts/quantity recorded.
- Final functional-test result recorded.
- Remaining issue status recorded.
- Follow-up recorded when an issue remains.

Example observation:
“Unit FP-017. Replaced two filters—actually three. There is still a rattling noise. I'll do the final test later.”

Expected state:
- Reported asset: FP-017.
- Parts quantity: three, with the earlier two superseded.
- Remaining noise: reported unresolved.
- Final test: planned, not complete.
- Closeout: missing required test evidence and an unresolved issue.
- Next question: ask for the final-test result, grounded in the checklist.

A later statement of a successful functional test must not silently resolve the earlier noise report. The assistant must separately reconcile that issue.

If camera is finished, photograph a clear printed label showing FP-071. The photo belongs to a different apparent asset. The app should surface the mismatch and ask whether the job, label reading, or photograph is wrong. It should not automatically overwrite the asset ID.

A final completed documentation state can coexist with a reviewed follow-up issue. “Report ready” must not mean “equipment certified safe.”

## UI

One screen with three connected areas:
- Left: push-to-talk, transcript, attached label photo, source timeline.
- Center: job facts and checklist statuses; show pending, missing, conflicting, and reported states.
- Right: follow-up question, report preview, and review/export actions.

Use a simple, restrained field-work design. Highlight the changing job facts as the demo runs. Display source excerpts, not model reasoning traces or invented confidence percentages.

A small disclosure panel can show model tag, quantization, device, and measured latency. Those values must come from the actual run. User-facing work controls should remain about the job rather than implementation details.

## Implementation

Suggested stack:
- React + Vite + TypeScript for the locally served UI.
- FastAPI + Pydantic for ingestion, state validation, and local tool endpoints.
- SQLite for jobs, sources, fact revisions, checklist items, and tickets.
- Ollama with qwen3:4b as an initial language-model candidate.
- whisper.cpp with a small English speech model for push-to-talk transcription.
- Tesseract for printed label OCR if camera reaches P1.
- SQLite full-text search or simple ranked text chunks for the short local procedure.

Ollama currently lists qwen3:4b as Q4_K_M with approximately 2.5 GB of model weights. This is disk/model-weight size, not total runtime RAM. Context, speech processing, development tools, and the operating system need additional memory.

Benchmark the 4B model on the actual M3. Keep language-model calls sequential, use a bounded context, and request compact schema-constrained output. Check the model's supported thinking controls and disable thinking when permitted for this extraction workload. This is a starting configuration, not a validated optimum or a claim that it is the newest/best small model.

whisper.cpp supports Apple Silicon and Metal. Actual acceleration, speech accuracy, and end-to-end latency must be measured. Do not claim Apple Neural Engine execution unless the deployed configuration actually uses it.

Use local audio processing rather than browser speech recognition whose offline behavior has not been verified. Serve scripts, fonts, styles, models, and sample procedures locally. No CDN or remote model fallback in the demonstrated workflow.

### State and tool boundaries

The model proposes structured changes; code decides whether to apply them.

Suggested conceptual objects:
- Source: immutable ID, type, text or OCR content, local file path, timestamps.
- Fact revision: field, value, state, source ID, exact quotation, superseded revision, review status.
- Requirement: ID, supplied-procedure section, required evidence, status.
- Job: asset ID, active revisions, requirements, unresolved issues.
- Local ticket: issue, cited evidence, proposed follow-up, review status.

Allowlisted operations:
- Search supplied procedure.
- Propose a fact update.
- Validate evidence references.
- Evaluate required documentation.
- Ask a follow-up question.
- Draft a local ticket.
- Generate a report preview.

Validate schema shape, known field names, existing source IDs, actual substring quotations, permitted transitions, and checklist conditions. These validations do not prove that a model's semantic interpretation is correct. Manual review and fresh-case evaluation remain necessary.

Ambiguous conflicts require confirmation. Explicit self-correction may supersede a value while retaining the source history. User transcript edits invalidate dependent interpretations and trigger reevaluation.

Do not implement arbitrary shell execution or external service actions as part of the agent.

## Evaluation that makes the project credible

Use the same local model and same supplied inputs/documents for a simple one-pass report baseline and the FieldPilot workflow. Give the baseline a sensible report/issue-detection prompt; avoid deliberately weakening it.

Make the comparison about this workflow, not a claim of superior general model intelligence.

Development cases:
1. Explicit quantity correction.
2. “I will test it later” versus a completed test.
3. “I didn't replace the part.”
4. Missing test result.
5. An unresolved issue despite a successful test.
6. Explicitly resolved issue.
7. Conflicting readings without an explicit correction.
8. A photo showing a different asset ID.
9. Unclear OCR that requires confirmation.
10. An unrelated observation.
11. A user correction to the transcript.
12. A request to mark a job complete without required recorded evidence.

Before prompt tuning ends, one teammate should write a separate fresh evaluation set and keep it out of prompts and implementation decisions. Run it after freezing the pipeline. Report sample size and examples of failures; a small hackathon set is preliminary evidence, not production validation.

| Metric | How to calculate/report |
|---|---|
| Fact correctness | Correct extracted field values / labeled field values; count omitted required values separately |
| Task-state correctness | Correct planned/completed/not-complete/missing/conflicting states / labeled states |
| False completion | Number of planned or explicitly unfinished tasks incorrectly recorded as completed |
| Correction handling | Correct explicit corrections / correction cases |
| Evidence validity | Existing quotations plus manual assessment of whether each quotation supports the recorded interpretation |
| Unsupported additions | Count report actions or observations with no supporting input |
| Follow-up quality | Whether the first question addresses a genuinely missing or conflicting requirement |
| End-to-end latency | Audio capture end to usable state/question; also separate transcription and extraction |
| Memory | Measured process usage and observed whole-device memory pressure, with measurement method disclosed |
| Offline operation | Successful full new-input runs while internet access is disconnected |

Treat a clear false-completion failure as a blocker for demo readiness. Do not promise zero hallucinations, production safety, compliance certification, or validated cost savings.

## Two-person schedule

The published event build window is noon–8 PM. All times are America/New_York.

| Time | Sreenidh: inference and state | Teammate: UI and evidence | Shared checkpoint |
|---|---|---|---|
| 12–12:30 | Verify runtime and model response | Define recording/report UI | Confirm sponsor requirements and allowed preparation |
| 12:30–2 | Extraction schema and state validator | Text-input UI and evidence links | End-to-end text input by 2 PM |
| 2–3:30 | Local transcription and checklist logic | Recording and dynamic report view | Voice → state → question → report works |
| 3:30–4:30 | Fix corrections/conflicts | Camera OCR only if P0 is stable | Feature freeze decision |
| 4:30–5:30 | Baseline and fresh evaluation | Offline run and evidence review | Actual metrics and failures captured |
| 5:30–6:30 | Fix failures; no new major features | Export, polish, backup recording | Reliable core demonstration |
| 6:30–8 | Runtime warmup and final checks | Pitch, demo video, submission | Submit with time to spare |

Before 2 PM, if the local model or schema is failing, simplify the schema and context or use a smaller candidate. Do not compensate with a hidden cloud call. If audio is unreliable at 3:30, keep correctable transcript entry and focus on resolving audio; defer the camera. If P0 is unstable at 4:30, remove P1/P2 from the competition demonstration.

## Demo and pitch

Prepare a 90-second version plus a live version. Confirm the actual submission format onsite; the public sources available during research do not establish a complete sponsor-specific submission rubric.

Demo sequence:
- 0–10 seconds: one sentence explaining the technician's documentation problem.
- 10–15: show internet disconnected and app ready.
- 15–35: new voice input with a quantity correction and a planned test.
- 35–50: highlight corrected state, missing evidence, and a follow-up question.
- 50–60: camera asset mismatch, only if reliable; otherwise show one source link.
- 60–75: new response changes the state; draft a reviewed report and local follow-up.
- 75–90: show measured results, device/model, and why offline matters.

Invite an unexpected judge-provided correction in the live version. If that fails, acknowledge it; do not substitute a prerecorded result while describing it as live.

Suggested pitch language:
“Field technicians finish work with voice notes and paperwork, often where connectivity is unreliable. FieldPilot turns those observations into an evidence-linked job record, checks the supplied closeout requirements, and asks for what is missing. Speech recognition and language understanding run on this Mac. Nothing in the core workflow needs a cloud model.”

Insert actual measured results only after evaluation. Distinguish an estimated workflow benefit from measured time saved. A backup recording protects submission reliability but is not evidence that a live run succeeded.

## Judge relevance

These are inferences from public work, not confirmed preferences or vote weights.

- Joe/Luminal: show hardware-aware choices, measured performance, and a defensible evaluation.
- Amanda/Unseen: connect intelligence to actual field observations; do not equate speech transcription with acoustic fault diagnosis.
- Kevin/VetRec: emphasize accurate state, evidence, review, and completing a professional workflow beyond summarization.
- Shevy/NPU: articulate buyer, adoption, and a consent-based route to useful real-world data.
- Ted and Greg: show a clear operational need and a short, authentic customer-discovery finding.
- Kartikey: make local execution and differentiation visible; his portfolio already contains on-device notes and edge-AI work.
- AGI/Vivek: make useful device-side perception, interpretation, and actions visible.

No public evidence establishes that all listed judges evaluate AGI or that one judge controls the award.

## Preparation and onsite questions

Tonight: obtain permitted dependencies/model weights, check local runtime on the Mac, prepare physical labels/headphones/power, and review the event's prebuilding policy before creating competition code or assets. Dependency preparation may also be governed by event rules.

At check-in:
1. Does the AGI award accept inference on an Apple Silicon laptop?
2. Is a particular AGI SDK or model required?
3. What qualifies as on-device intelligence, and who judges it?
4. Can AGI and overall Track 1 awards stack?
5. What are the final submission format and deadline?

Ask a potential technician or facilities worker, if accessible:
- How do you document a finished job today?
- What information most often needs a follow-up?
- When is connectivity a problem?
- Would this particular workflow help, and why?

One conversation can sharpen the prototype; it is not broad market validation.

## Sources

Accessed October 10, 2026. Public pages may change.
- Event and published prizes/agenda: https://luma.com/compiled-jjvw
- YC Fall 2026 RFS: https://www.ycombinator.com/rfs
- AGI device-agent positioning: https://www.theagi.company/agent
- Luminal: https://www.luminal.com/
- Unseen: https://unseen.inc/ and https://www.linkedin.com/company/unseen-ai
- VetRec: https://www.ycombinator.com/companies/vetrec
- NPU Ventures: https://npu.vc/
- Penn State entrepreneurship faculty: https://www.sedi.psu.edu/eship/faculty.aspx
- Kartikey's portfolio: https://www.kartikey.fyi/record
- Model configuration: https://ollama.com/library/qwen3:4b
- Ollama structured outputs: https://docs.ollama.com/capabilities/structured-outputs
- Ollama thinking controls: https://docs.ollama.com/capabilities/thinking
- Local transcription: https://github.com/ggml-org/whisper.cpp
- Local OCR: https://tesseract-ocr.github.io/tessdoc/
- Past Penn State submissions and winners: https://www.compiled.sh/articles/c0mpiled-6-ai-for-productivity-research

