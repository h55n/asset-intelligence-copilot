# Demo video - script and shot list (max 5:00, your own voice)

Record in one take if you can; cuts between sections are fine. Screen-record
the copilot in the browser; talk over it. Target ~4:30.

## 0:00-0:25 - What this is
Shot: the chat UI, fresh session.

Say: "This is my Asset Intelligence Copilot for the FlytBase hack day. An
operator asks plain-English questions about 200 oil wells - downtime,
spills, repairs, compliance - and gets answers in seconds, with the exact
records each answer used. The design rule I followed: the model
orchestrates, the data layer decides. No number in any answer comes from
the model's memory; everything is computed from the records."

## 0:25-1:50 - How it's built
Shot: the repo README / this diagram on screen (or the docs page).

Say: "Three layers. One: a loader that turns the dataset folder - fleet
files plus one folder per well - into typed SQLite tables, with full-text
indexes over the manuals, SOPs and all fifteen hundred repair reports. The
rules that decide answers are applied in code, each with its source: a well
is producing when its wellhead runs at least 15 degrees above air for a
T200, 20 for a T350 - from the manuals. Downtime is seven days per
non-producing weekly inspection - from the dataset guide. Spill classes and
reporting deadlines come from the SOPs. Two: an agent that plans tool calls
against eighteen grounded tools. Three: memory at two levels. Corrections
keep the original value, who corrected it and why, and apply at exactly the
scope given - one inspection, one well, or a whole well type. Shared notes
reach every user; chat history stays private per user; and when people
contradict the data or each other, the copilot shows the conflict instead
of picking a side."

## 1:50-3:30 - Live use case (end to end)
Shot: the UI. Pick Northeast Block 8's supervisor (Michael Turner) in the
user picker.

Ask live: "Which wells in Northeast Block 8 are not producing oil right
now, and why? Show them in a table."

Say over the answer: "Watch the answer come back as a table, generated for
the question. Each well's delta against its type's threshold, the recorded
status flagged out of date where the system of record is stale, and the
reason where one exists - an open repair, or nothing, in which case it says
so instead of inventing a cause. Every claim cites its inspection or note."

Then the follow-up (shows memory + honesty): "The 15 Oct reading for
WELL-0164 is wrong. The thermal gun was faulty; the crew re-measured at
41.0."

Say: "Now I correct raw data. It keeps the original 24 degrees, records who
corrected it and why, recomputes - 21 degrees above air, so the well is
producing - and notice: it flags that the inspector's own note says 'pump
jack not moving', which disagrees with my correction, and asks me to
confirm. It does not silently pick a side."

Re-ask the first question; WELL-0164 drops off the table. "Same question,
one correction later - the answer changed everywhere, for every user."

## 3:30-4:20 - The generative UI, then one harder query
Ask: "Show a map of all wells that are down."
Say: "The same pipeline answers two problems - the data problem and the
interface problem. Every answer carries a visual spec built only from tool
data, so the visuals can never invent a number. Ask for a map, you get a
map - each down well pinned from its recorded coordinates."

Ask: "Show a heatmap of 2026 spills by area and month."
Say: "A two-dimensional question becomes a heatmap. A comparison becomes a
bar chart, a trend becomes a line chart with the down days marked. The user
names the visual, the system picks a sane one when they don't."

Then, if time allows: "Which rules has WELL-0001 broken in the last 12
months, and what is still open?" (compliance: 41-hour late report, the
$5,000 open notice, containment time found only inside the repair report)

## 4:20-4:50 - Close
Say: "Everything runs on free tiers: SQLite, one open model for
orchestration, no training. The same loader takes the test dataset
unchanged, which is the point - the system reads the rules from the data
and the manuals, not from the sample questions. Repo link is in the
submission. Thanks."

## Recording checklist
- [ ] User picker visible; mention users switch and memory is per-user
- [ ] Zoom browser to ~125% so text reads on small screens
- [ ] Have the two questions pre-typed in a notes window to paste
- [ ] If a live answer is slow, keep talking - do not edit out the wait;
      judges want a real run
