# Asset Intelligence Copilot

A chat copilot that answers operators' plain-English questions about an oil
field - "Which wells in my area were down the longest this summer, and why?" -
correctly and with evidence, across structured records, sensor readings,
manuals, repair reports and human notes.

Built for the FlytBase x AI Hackers Collective Hacktoberfest Hack Day challenge.

## What is unusual here

- **A deterministic rules engine over rules parsed from the manuals.** The
  15 C / 20 C producing thresholds, downtime counting, spill classes,
  SR-01/02/03 and RC-01-05 deadlines, and RCA triggers are applied in code
  with their manual sections cited - not left to the model's judgement.
- **Conflict-aware memory.** User corrections re-run their consequences
  (a 4.5 -> 5.4 bbl fix reclassifies the spill and surfaces the missed
  24 h notice); claims that contradict the data or another person are
  stored, marked *unconfirmed*, and shown with the disagreeing evidence.
  Both sides stay on record.
- **QA is shipped, not claimed.** The 18-scenario suite, an
  expected-answer checker, and an ID-shifted generalization probe run with
  one command (`qa/run_all.sh`).

## How this meets each judging criterion

| Criterion | Where it is met | Proof |
| --- | --- | --- |
| Full pipeline, end to end | Loader -> rules engine -> agent -> cited answer -> generative UI | `app/ingest.py`, `app/core.py`, `app/agent.py`, `app/static/chat.html` |
| Part A: all 18 example questions | Automated suite plays every scenario, including the multi-turn chains | `scenario_suite.py`; run log in `qa/` output; expected-answer scoring in `qa/check_answers.py` |
| Part B: memory, feedback, conflicts | Shared corrections with scope + consequence re-run, shared notes, per-user history, conflict detection | `app/core.py` (corrections/claims/notes), scenario Q12-Q18 in the suite |
| Data quality and rules | Containment times template-parsed from 616 free-text repair reports (100% coverage); downtime per Dataset Guide, `downtime_hours` never used | `app/ingest.py`, "Rules in code" in `docs/writeup-page1.md` |
| Generalization to unseen data | Entire dataset re-labelled with shifted IDs, ingested, probed: 7/7 pass - rules come from manuals, not sample IDs | `qa/generalization.py` |
| Generative UI | Answers carry a validated viz spec rendered as card/table/line/bar/map/heatmap; user-named visual wins; tool-data-only rendering | `app/static/chat.html`, generative-UI section of `docs/writeup-page1.md` |
| Verification / QA approach | Deterministic checks + expected-answer scoring + generalization probes behind one command | `qa/run_all.sh`, "How I QA'd it" in `docs/writeup-page1.md` |
| Honest engineering | Open source (MIT), free-tier inference only, no sample-specific tuning | `LICENSE`, `README.md` run section |

## How it works

```
chat UI  ->  agent loop (LLM plans tool calls)
                 |
        deterministic core (Python + SQLite)
        - one-command loader: dataset folder -> typed tables + FTS index
        - rules from the manuals/SOPs applied in code, not in the prompt
        - memory: corrections, shared notes, claims, per-user chat history
```

The design principle: **the model orchestrates, the data layer decides.**
Every fact in an answer comes from a tool result that carries record IDs, so
answers are grounded and cite their evidence.

### Data layer (`app/ingest.py`, `app/core.py`)

- Loads any dataset in the challenge format (fleet + per-well folders) into
  SQLite: wells, weekly inspections, maintenance, regulator events, human
  notes, users/areas/teams, plus FTS5 indexes over the manuals, SOPs and the
  free-text repair reports. Loading the test dataset is the same command.
- Producing status is derived per the well-type manuals: wellhead at least
  15 C (T200) / 20 C (T350) above ambient. Downtime counts 7 days per
  non-producing weekly inspection; missed inspections add none.
  `maintenance.downtime_hours` is never used for downtime.
- Spill detection corrections ("that was rainwater") remove a detection from
  every spill statistic; the correction note is cited.
- Containment times exist only inside free-text repair reports; they are
  extracted at ingest and stored with the report ID for citation.
- Compliance engine: SR-01 (24 h written notice), SR-02 (4 h containment),
  SR-03 (60-day agency verification), RC-04 (30-day NOV response), RCA
  escalation (3 corrective repairs on one equipment kind in 12 months), each
  breach returned with the records that prove it.

### Memory (`app/core.py`, tools in `app/tools.py`)

- **Corrections** (raw data or AI analysis): original value kept, author and
  reason recorded, applied to every later answer for every user. Scope is
  exact: one inspection, one well, or every well of a type.
- **Shared notes**: field facts one user shares (planned shut-in) are visible
  to all users and attributed.
- **Claims**: statements that contradict the data or another person stay on
  record; the copilot shows both sides and asks for confirmation instead of
  silently picking one.
- **Private memory**: each user's conversation history is theirs alone;
  "the wells we discussed yesterday" resolves per user, never across users.

### Generative UI (`app/static/index.html`)

The agent returns an answer plus a visualisation spec - status card, table,
line chart, bar chart, map, or heatmap - chosen by the question (or the
visual the user named), rendered inline in the chat.

## Run it

```
pip install -r requirements.txt
export LLM_API_KEY=...        # any OpenAI-compatible chat API with tool calling
# primary: Gemma 4 via Google AI Studio free tier
export LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
export LLM_MODEL=gemma-4-26b-a4b-it
# alternative: Groq free tier
# export LLM_BASE_URL=https://api.groq.com/openai/v1
# export LLM_MODEL=openai/gpt-oss-120b
export DATA_DIR=/path/to/sample-data
python app/server.py           # http://localhost:8000
```

`app/server.py` ingests `DATA_DIR` into SQLite on first start. To load a new
dataset (e.g. the test set), point `DATA_DIR` at it and delete the old DB.

## Checks

`python verify.py` recomputes the challenge's example scenarios from the
records and asserts the expected answers (18/18 on the sample dataset).
`python scenario_suite.py` drives the same scenarios through the running
server, including the memory and feedback sequences.

## QA harness

Everything used to test this copilot ships in the repo:

- `verify.py` - deterministic checks of the data layer (production verdicts,
  spill totals, downtime math, compliance windows), no model needed.
- `scenario_suite.py` - drives all 18 example scenarios, including the
  multi-turn memory, correction and conflict chains, through the running
  server and saves every answer.
- `qa/check_answers.py` - scores the suite's answers against the expected
  key facts (well IDs, figures, required and forbidden content, expected
  visual form).
- `qa/generalization.py` - copies the dataset with every well, inspection,
  repair, regulation, note and user ID shifted to new values, ingests it,
  and checks the pipeline produces the same verdicts under the new IDs.
  This is the overfitting probe: the rules come from the manuals and the
  data, not from the sample IDs.
- `qa/run_all.sh` - all of the above, one command:

  ```bash
  LLM_BASE_URL=... LLM_MODEL=... LLM_API_KEY=... ./qa/run_all.sh
  ```

The correction and claim scenarios deliberately mutate the database, so the
runner always re-ingests clean before the suite.
