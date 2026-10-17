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

The agent returns the answer plus a visualisation spec: status card for one
well, table for lists, line chart for change over time (with not-producing
markers), bar chart for comparisons, map for locations, heatmap for two
dimensions. A user-named visual wins. Rendered inline in the chat, built
only from tool data.

## Models and cost

Inference: one hosted open-weight model - Gemma 4 (26B, mixture-of-experts) -
over the Google AI Studio free-tier OpenAI-compatible API with tool calling;
temperature 0.2; tool results truncated, pacing plus backoff on rate limits
and transient errors. Zero cost. The client is provider-agnostic (base URL,
model and key are environment config), so any OpenAI-compatible open-weight
model can be swapped in without code changes. Retrieval is SQLite FTS +
structured SQL - no embedding infrastructure to drift between sample and
test data.

## What I would do next

Confidence-gated second reads for borderline producing readings (within
~1 °C of threshold), extraction of more report fields (parts, soil TPH)
into queryable columns, per-team digest views ("what changed in my area
this week"), and an eval harness that replays the feedback scenarios
against new datasets automatically.
