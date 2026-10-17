# Asset Intelligence Copilot — System Design (Page 1)

## The one idea

**The model orchestrates; the data layer decides.** Every number, date and
name in an answer is computed by a deterministic engine over the records and
returned to the model with its evidence IDs. The LLM's job is to understand
the question, plan which tools to call, and phrase the answer - never to
remember a fact or invent one. That is what keeps the system correct on data
and questions it has never seen, and it is what makes corrections,
conflicts and citations cheap to get right.

## Pipeline

```
question -> agent loop (tool-calling LLM)
               |  plans calls, phrasing, visual choice
               v
        18 grounded tools (app/tools.py)
               |
        deterministic core (app/core.py + SQLite)
               |  rules engine, corrections overlay, memory, FTS
               v
        ingested dataset (app/ingest.py: any folder in the challenge format)
```

**Ingestion.** One command loads a dataset folder (fleet + per-well files)
into typed SQLite tables: wells, weekly inspections, maintenance, regulator
events, human notes, users/areas/teams. Manuals, SOPs and the ~1,500
free-text repair reports go into FTS5 indexes. Containment times exist only
inside the repair reports, so they are extracted at ingest with a strict
template parse (616 spill reports, 100% coverage of containment events) and
stored next to their report ID for citation. The test dataset loads with
the same command - nothing is tuned to the sample.

**Rules in code, with their sources.** The rules that decide answers are
applied by the engine, each citing where it lives: producing = wellhead at
least 15 °C (T200, OM-T200 §9.3) or 20 °C (T350, OM-T350 §3) above ambient
at reading time; downtime = 7 days per non-producing weekly inspection,
missed inspections add none, `downtime_hours` never used (Dataset Guide);
spill classes and SR-01/02/03 deadlines (Spill Response SOP §3-4); RC-01-05
(Regulatory Compliance SOP); RCA after 3 corrective events on one equipment
kind in 12 months (OM-T200 §10). A detected spill removed by a formal
correction note stops counting everywhere, with the note cited. The
compliance tool walks every reportable spill and checks the written-notice
time, the containment time from its repair report, the 60-day verification
and the NOV response, returning breaches and still-open obligations with
the records that prove each.

**Tools.** 18 tools cover: well status (with recorded-status staleness
flag), area lists, temperature series, downtime, spills (corrections
applied), repairs and costs, regulator events, notes, document/report
search, the rule book, compliance, RCA, and the four memory operations
below. Results carry evidence IDs; the agent must cite them.

## Memory at two levels, and honesty about conflicts

- **Shared corrections.** A user correction (wrong reading, wrong AI
  estimate) is stored with the original value, the author and the reason,
  at an exact scope: one inspection, one well, or every well of a type.
  Every later answer for every user uses the correction at that scope, and
  says when an answer follows a person's rule rather than the manual.
  Recording a correction re-runs the consequences: e.g. a 4.5 -> 5.4 bbl
  correction reclassifies the spill to reportable and immediately surfaces
  the missing 24 h notice, the new 60-day verification deadline, and the
  repair report whose classification no longer holds.
- **Shared knowledge.** Field facts one user posts (a planned shut-in) are
  stored attributed and visible to everyone.
- **Private memory.** Chat history is strictly per user; "the three wells
  we discussed yesterday" resolves from that user's own sessions only, and
  the copilot says so plainly when a user has no such history.
- **Conflicts.** A claim that contradicts the latest inspection or another
  person is stored, marked unconfirmed, and shown with the data that
  disagrees - both sides stay on record; the copilot asks for confirmation
  instead of silently choosing. Disagreeing informal notes (no formal
  correction) are presented with both sources and the detection stands.

## Generative UI

The challenge is two problems, not one: get the right data, then show it the
right way. The second half is a first-class part of the pipeline, not a
decoration. For every answer the agent returns two things: the prose answer
and a visualisation spec - a small, strict JSON object with a chart type and
a data payload built only from tool results. The chat client renders the
spec into a real, interactive visual inline with the answer.

Six visual forms, chosen by the shape of the question: a status card for one
well (producing / not producing with the rule that decided it), a table for
lists and rankings, a line chart for change over time (with not-producing
markers on the days a well was down), a bar chart for comparisons across
wells, a map for anything geographic (down wells as pins with labels), and a
heatmap for two-dimensional questions (spills by area and month). When the
user names a visual - "show a map", "as a heatmap" - that request wins over
the agent's own choice.

Two rules keep the visuals honest. First, they are drawn only from tool
data: a chart can never show a number the tools did not return, so the
visual layer cannot hallucinate. Second, the spec is validated before
rendering - unknown types, empty payloads and malformed series fall back to
the table/prose forms instead of drawing something wrong. The same spec
feeds the demo and the preloaded example conversations on the site, so what
you see in the write-up screenshots is exactly what the chat renders.

## Models and cost

Inference: one hosted open-weight model - Gemma 4 (26B, mixture-of-experts) -
over the Google AI Studio free-tier OpenAI-compatible API with tool calling;
temperature 0.2; tool results truncated, pacing plus backoff on rate limits
and transient errors. Zero cost. The client is provider-agnostic (base URL,
model and key are environment config), so any OpenAI-compatible open-weight
model can be swapped in without code changes. Retrieval is SQLite FTS +
structured SQL - no embedding infrastructure to drift between sample and
test data.

## How I QA'd it: what broke, and how I fixed it

The whole suite - all 18 example scenarios, including the multi-turn
memory, correction and conflict chains - runs as an automated script
against a freshly ingested database, and I read every answer against the
expected answers by hand. Five scored runs so far. What actually broke:

- **Stale server code, not bad answers.** One run showed six HTTP 500s
  across the suite. The failures were the server process still running
  pre-fix code, not the pipeline. Fix: the suite now always runs against a
  clean re-ingest and a freshly started server, because the correction and
  claim scenarios deliberately mutate the database.
- **Cross-session memory was not triggered by phrasing.** "For the three
  wells we discussed yesterday" came back with "I don't have access to
  yesterday's conversation" - the model never called the recall tool. Fix:
  a deterministic guard detects references to earlier conversation and
  injects this user's own history into the prompt. Re-run: exact expected
  figures (WELL-0138 $46,942; WELL-0121 $25,794; WELL-0107 $5,176), and a
  different user asking the identical question is correctly told no such
  conversation exists with her.
- **A conflict slipped through the wrong door.** "WELL-0001 is back online
  since 14 Oct" was recorded as a shared note without being checked,
  because the conflict assessment only lived in the claims path. Fix: the
  shared-note path now runs the same deterministic assessment and the tool
  result instructs the reply to surface the conflict and keep both
  statements on record. Verified live: the copilot now answers with the
  15 Oct inspection and the ~20 Oct expected return, and marks the claim
  unconfirmed.
- **Overfitting check.** I re-labelled the entire dataset - every well,
  inspection, repair, regulation, note and user ID shifted to new values -
  ingested it, and ran seven deterministic probes (production verdicts,
  spill totals, user mapping, parsed rules). 7/7 passed, because the rules
  come from the manuals and the data, not from the sample IDs.

The harness itself ships in the repo: the deterministic core checks, the
18-scenario suite with expected-answer scoring, and the ID-shift probe,
all behind one command (`qa/run_all.sh`). QA is part of the product, not a
side activity.

## What I would do next

Confidence-gated second reads for borderline producing readings (within
~1 °C of threshold), extraction of more report fields (parts, soil TPH)
into queryable columns, per-team digest views ("what changed in my area
this week"), and an eval harness that replays the feedback scenarios
against new datasets automatically.
