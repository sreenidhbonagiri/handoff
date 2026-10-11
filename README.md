<div align="center">

# Handoff

### Less paperwork. Clearer handoffs. More time for the work.

An on-device AI assistant for field technicians and skilled tradespeople.

**Voice-first documentation · Local intelligence · Evidence-linked job records**

</div>

---

## Why Handoff?

Finishing the physical work is only part of finishing a job. Technicians still need to record what changed, which parts they used, what remains unresolved, and what the next person needs to know.

Those details can end up scattered across handwritten notes, photos, messages, and memory. Reconstructing them later adds paperwork and makes it easier to miss an unfinished task or lose an important observation.

**Handoff is designed to capture that context while the work is happening.** Speak naturally, attach supporting evidence, and build a clear job record with the information needed for the next step. Local intelligence helps interpret corrections, track outstanding work, and identify missing details before the documentation is finalized.

The goal is simple: give skilled workers more time for their craft and make every handoff easier to understand.

## Who it is for

Handoff starts with facilities maintenance technicians documenting a service visit. The broader vision is to support tradespeople who need a practical way to record work on-site, especially where connectivity is unreliable or job information should remain on the device.

## The core workflow

1. **Capture the work.** Record a spoken observation or enter a note about the current job.
2. **Organize the details.** Extract the asset, completed actions, parts used, observations, and outstanding tasks into a structured record.
3. **Clarify what is missing.** Compare the record with a supplied closeout checklist and ask a focused follow-up question.
4. **Review the evidence.** Inspect the source behind an extracted fact, confirm ambiguous changes, and correct the record.
5. **Prepare the handoff.** Generate a report for review and export, keeping unresolved work visible.

## What useful intelligence looks like

A technician says:

> “Unit FP-017. Just replaced two filt--uhh no, actually, three filters. The fan is still rattlin', and I’ll run the final test later.”

The intended result:

| Detail | Interpretation |
| --- | --- |
| Asset | FP-017 |
| Filters replaced | Three, with the earlier quantity retained in correction history |
| Fan noise | Still unresolved |
| Final test | Planned; not reported complete |
| Next question | Request the test result if the supplied checklist requires it |

If a later note reports that the test passed, the separate rattling issue remains open until it is explicitly addressed. Each extracted detail should link back to the observation that supports it.

**The value is in preserving the meaning of the update and helping the technician complete the record.**

## Product priorities

| Capability | Purpose |
| --- | --- |
| Local speech-to-text | Capture observations without stopping to type a report |
| Structured job records | Keep actions, parts, issues, and next steps together |
| Correction handling | Update facts while preserving their history |
| Task-state tracking | Distinguish completed, planned, and explicitly unfinished work |
| Checklist follow-ups | Surface required information that has not been recorded |
| Evidence references | Let the technician inspect where a statement came from |
| Review and export | Produce a clear record the technician can check before sharing |
| Photo attachments and local label OCR — stretch goal | Add supporting context and flag asset-identifier mismatches |

## Why on-device?

Local execution is central to the product's design:

- **Work without a connection.** The core workflow is intended to remain available after models and dependencies have been installed.
- **Keep job information local.** Recordings, transcripts, and job records are intended to stay on the device unless the user explicitly exports or shares them.
- **Maintain control over the record.** The worker can review the source material and the resulting report in one place.

The runtime design excludes cloud AI fallbacks, remote speech-recognition services, analytics, and externally hosted interface assets. Initial installation and model downloads may require internet access.

Local storage alone does not establish encryption or complete device security; those protections depend on the implementation and the host device.

## Proposed architecture and Software Stack

The language model interprets natural-language observations. Application logic validates the resulting structure, checks evidence references, and applies the rules for updating job state.

| Layer | Proposed technology | Responsibility |
| --- | --- | --- |
| Interface | React, Vite, TypeScript | Capture notes, review facts, and display reports |
| Local API | FastAPI, Pydantic | Validate inputs and coordinate processing |
| Storage | SQLite | Persist job records, evidence, and history |
| Language inference | Ollama with an initial Qwen3 4B candidate | Extract structured information from observations |
| Speech recognition | whisper.cpp | Transcribe audio locally |
| Optional OCR | Tesseract | Read printed asset labels |

The initial target development machine is an M3 MacBook Pro with 16 GB unified memory. Model choice and performance require measurement on the actual device.

## Record integrity

Handoff's design follows a few explicit rules:

- **Not recorded does not mean not performed.** Missing information remains unknown.
- **Planned work does not count as completed work.** Intent and completion have separate states.
- **Corrections keep their history.** Ambiguous contradictions require confirmation.
- **One successful check does not erase a separate issue.** Unresolved observations remain visible.
- **Evidence shows what was reported.** A transcript is not independent proof that physical work occurred.
- **The technician reviews the report.** Documentation readiness is separate from equipment safety.

***Handoff explores how on-device intelligence can turn everyday observations into useful records for the people doing the work.***
