# Asset Intelligence Copilot

A chat copilot that answers operators' plain-English questions about an oil
field - "Which wells in my area were down the longest this summer, and why?" -
correctly and with evidence, across structured records, sensor readings,
manuals, repair reports and human notes.

Built for the FlytBase x AI Hackers Collective Hacktoberfest Hack Day challenge.

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
export LLM_BASE_URL=https://api.groq.com/openai/v1   # default
export LLM_MODEL=openai/gpt-oss-120b                  # default
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
