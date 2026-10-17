"""Agent loop: an LLM plans tool calls, the deterministic core computes, the model phrases."""
import json, os, re, urllib.request, urllib.error

SYSTEM = """You are the Asset Intelligence Copilot for an oil field operator. You answer operators' plain-English questions about their wells, correctly and with evidence, using the tools provided. Today is {today}.

DOMAIN RULES (apply through tools, never from memory alone):
- A well is producing oil when its wellhead temperature is at least the threshold for its type above ambient air (T200: 15 C, T350: 20 C), from the well-type manuals. Absolute temperature means nothing on a hot day.
- Downtime: each weekly inspection where the well is not producing counts 7 days. Missed inspections add none. Never use maintenance downtime_hours for downtime.
- A detected spill later corrected by a formal correction note (e.g. rainwater) is not a spill. Spills of 5 bbl or more are reportable (SR-01: written notice within 24 h). Containment must happen within 4 h (SR-02, time is only in repair reports). Reportable spills need agency verification of clean-up within 60 days (SR-03). Notices of violation need a response within 30 days (RC-04).
- recorded_status can be out of date; inspections are the truth.
- People, teams and areas are referred to by name; wells by ID (WELL-0007).

HOW TO ANSWER:
1. Resolve names with resolve if unsure. Use tools for every fact. Never invent a cause or a number; when nothing in the records explains something, say so and suggest a check.
2. Every answer cites the records and documents it used: inspection IDs, maintenance IDs, report IDs, note IDs, event IDs, manual/SOP sections. Put them in the citations list.
3. Relative periods ("last 4 months", "this year", "in 2025") end today and are compared by date. A repair belongs to a period by its start date. Pass months=/days=/year= or explicit dates to tools.
4. "Right now" means each well's latest inspection.

MEMORY AND FEEDBACK:
- Shared knowledge: when a user states a field fact meant for everyone (a planned shut-in, a status update), record it with record_shared_note or record_claim so every user gets it. Statements that contradict the data or another person must be recorded with record_claim, kept on record, and the conflict surfaced - never silently pick one side.
- Corrections: when a user corrects raw data (a wrong reading) or your analysis (a wrong estimate), record it with record_correction. The original stays on record with who corrected it and why; the corrected value is used in every later answer for every user. A correction can apply to one inspection, one well, or every well of a type (scope "type:T350") - apply it at exactly that scope and say whose rule it is when it differs from the manual.
- If the tool result contains conflicts_to_surface or must_do, you MUST include that conflict in your answer and ask the user to confirm.
- Private memory: recall_conversation returns only the current user's own past conversations. "The wells we discussed" refers to that user's history only. If they have no such history, say so - never use another user's conversation.

ANSWER FORMAT - write the final answer as your plain message text, ONLY this JSON object (never call a tool to produce it, never wrap it in anything):
{{
  "answer": "markdown answer for the operator, concise, with the key numbers and reasons inline",
  "viz": {{"type": "card|table|line|bar|map|heatmap|none", "title": "...", "data": ...}},
  "citations": ["INS-0001-0203", "MNT-0001-032", "Spill Response SOP SR-01", ...],
  "follow_up": "optional short question back to the user, e.g. asking to confirm a conflict"
}}
VIZ RULES: if the user names a visual, use it. Otherwise: one well status -> card; a list -> table (data: {{"columns": [...], "rows": [[...]]}}); change over time -> line (data: {{"x": [dates], "series": [{{"label": "...", "y": [...]}}], "markers": [{{"x": "date", "label": "..."}}]}}); comparing wells/areas -> bar (data: {{"labels": [...], "values": [...]}}); locations -> map (data: {{"pins": [{{"well": "WELL-0001", "lat": 31.8, "lon": -102.5, "label": "..."}}]}}); two dimensions like area x month -> heatmap (data: {{"rows": [area names], "cols": [months], "values": [[...]]}}); a short answer needs none. Build viz data from tool results only."""

TOOL_SCHEMAS = [
    ("resolve", "Find a user, area or well by name", {"name": ("string", "name to resolve")}, ["name"]),
    ("get_well_status", "Full current status of one well: producing calculation, latest inspection, recorded status mismatch, active notes, open repairs, claims", {"well_id": ("string", "e.g. WELL-0001")}, ["well_id"]),
    ("list_area_wells", "Status of every well in an area, optionally only non-producing ones", {"area": ("string", "area name or id"), "only_not_producing": ("boolean", "")}, ["area"]),
    ("get_temperature_series", "Wellhead vs ambient temperature readings over time for one well, each marked producing or not", {"well_id": ("string", ""), "start": ("string", "YYYY-MM-DD"), "end": ("string", "YYYY-MM-DD"), "last_weeks": ("integer", "last N weekly readings")}, ["well_id"]),
    ("get_downtime", "Downtime days (7 per non-producing weekly inspection) for one well or every well in an area over a window", {"well_id": ("string", ""), "area": ("string", ""), "start": ("string", "YYYY-MM-DD"), "end": ("string", "YYYY-MM-DD"), "months": ("integer", "last N months ending today"), "year": ("integer", "calendar year")}, []),
    ("get_spills", "Real spills (formal corrections removed, runtime corrections applied) with volumes, dates, locations, reportable flag", {"well_id": ("string", ""), "area": ("string", ""), "start": ("string", ""), "end": ("string", ""), "months": ("integer", ""), "days": ("integer", "last N days"), "year": ("integer", ""), "include_corrected": ("boolean", "also list detections corrected as not-a-spill")}, []),
    ("get_repairs", "Maintenance jobs with costs, issues, downtime hours, linked reports and containment times", {"well_id": ("string", ""), "area": ("string", ""), "start": ("string", ""), "end": ("string", ""), "months": ("integer", ""), "year": ("integer", ""), "maintenance_type": ("string", "scheduled|corrective"), "equipment_kind": ("string", "wellhead|pump_jack|rod_string|downhole_pump|flowline|separator")}, []),
    ("get_regulatory_events", "Regulator events: spill reports, notices of violation, site inspections, responses, fines", {"well_id": ("string", ""), "area": ("string", ""), "start": ("string", ""), "end": ("string", ""), "months": ("integer", "")}, []),
    ("get_notes", "All human notes for a well including corrections and shared notes", {"well_id": ("string", "")}, ["well_id"]),
    ("search_documents", "Full-text search over the well-type manuals, SOPs and free-text repair reports", {"query": ("string", "FTS query"), "limit": ("integer", "")}, ["query"]),
    ("get_rules", "The operating rules with their exact manual/SOP sources: producing thresholds, spill classes, SR-01..04, RC-01..05, RCA", {}, []),
    ("compliance_check", "Rule breaches and pending obligations for a well or area over the last N months (SR-01/02/03, RC-04)", {"well_id": ("string", ""), "area": ("string", ""), "months": ("integer", "")}, []),
    ("rca_check", "Wells needing a root-cause analysis: corrective repairs on an equipment kind at/above the threshold in 12 months; honours per-type user rules", {"area": ("string", ""), "equipment_kind": ("string", ""), "months": ("integer", "")}, []),
    ("record_correction", "Record a user correction to raw data or AI analysis; recomputes affected answers and downstream obligations", {"author_user_id": ("string", "user name"), "scope": ("string", "INS-... | WELL-... | type:T350"), "field": ("string", "wellhead_temp_c|ambient_temp_c|spill_est_volume_bbl|spill_detected|rca_corrective_count|producing_threshold_c"), "corrected_value": ("string", "new value"), "reason": ("string", "why"), "original_value": ("string", "old value if known")}, ["author_user_id", "scope", "field", "corrected_value", "reason"]),
    ("record_shared_note", "Record a fact a user shares for everyone (planned shut-in, status update) tied to a well", {"author_user_id": ("string", ""), "well_id": ("string", ""), "text": ("string", ""), "valid_from": ("string", "YYYY-MM-DD"), "valid_to": ("string", "YYYY-MM-DD")}, ["author_user_id", "well_id", "text"]),
    ("record_claim", "Record a user's statement about a well and assess it against the data; contradictions stay on record", {"author_user_id": ("string", ""), "well_id": ("string", ""), "text": ("string", "")}, ["author_user_id", "well_id", "text"]),
    ("recall_conversation", "Recall the current user's own past conversations (wells discussed, recent messages) - never another user's", {"user_id": ("string", "user name or id")}, ["user_id"]),
    ("get_spill_matrix", "Spill counts per area per month as a compact matrix - use for heatmaps instead of pulling every spill", {"year": ("integer", ""), "start": ("string", ""), "end": ("string", "")}, []),
    ("get_containment_breaches", "Spills whose containment time (from repair reports) exceeded the 4 h SOP limit - use for 'not contained in time' questions", {"area": ("string", ""), "well_id": ("string", ""), "days": ("integer", ""), "months": ("integer", "")}, []),
    ("list_users", "List the people who use the copilot", {}, []),
]

def build_tools_json():
    out = []
    for name, desc, props, req in TOOL_SCHEMAS:
        p = {k: {"type": t, "description": d} for k, (t, d) in props.items()}
        out.append({"type": "function", "function": {"name": name, "description": desc,
                    "parameters": {"type": "object", "properties": p, "required": req}}})
    return out

WELL_RE = re.compile(r'WELL-\d{4}', re.I)

class LLMError(Exception):
    pass

def chat_completion(base_url, api_key, model, messages, tools=None, max_tokens=4000, temperature=0.2, _attempt=0):
    import time
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(base_url.rstrip('/') + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "curl/8.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors='replace')
        try:
            err = json.loads(body).get('error', {})
        except json.JSONDecodeError:
            err = {}
        if err.get('code') == 'tool_use_failed' and err.get('failed_generation'):
            # model emitted the final JSON as a raw tool call; treat it as the message
            return {"choices": [{"message": {"role": "assistant", "content": err['failed_generation']}}]}
        if e.code == 429 and _attempt < 14:
            import time
            m = re.search(r'try again in ([\d.]+)s', body)
            wait = float(m.group(1)) + 1 if m else min(2 ** _attempt * 5, 60)
            time.sleep(wait)
            return chat_completion(base_url, api_key, model, messages, tools, max_tokens, temperature, _attempt + 1)
        raise LLMError(f"{e.code}: {body[:400]}")

class Agent:
    def __init__(self, tools_obj, base_url, api_key, model, today):
        self.t = tools_obj
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.today = today
        self.tools_json = build_tools_json()

    def run_tool(self, name, args):
        fn = getattr(self.t, name, None)
        if not fn:
            return {"error": f"unknown tool {name}"}
        clean = {k: v for k, v in (args or {}).items() if v not in (None, "", [])}
        try:
            return fn(**clean)
        except TypeError as e:
            return {"error": f"bad arguments: {e}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def answer(self, user_name, user_id, session_id, message, history, max_rounds=10):
        msgs = [{"role": "system", "content": SYSTEM.format(today=self.today)}]
        msgs.append({"role": "system", "content": f"The current user is {user_name} ({user_id}). Attribute everything they tell you to them."})
        for h in history[-8:]:
            msgs.append({"role": h["role"], "content": h["text"]})
        msgs.append({"role": "user", "content": message})
        wells_seen = set(WELL_RE.findall(message.upper()))
        calls_made = []
        for _ in range(max_rounds):
            resp = chat_completion(self.base_url, self.api_key, self.model, msgs, self.tools_json)
            ch = resp["choices"][0]["message"]
            if ch.get("tool_calls"):
                msgs.append({"role": "assistant", "content": ch.get("content") or "", "tool_calls": ch["tool_calls"]})
                for tc in ch["tool_calls"]:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = self.run_tool(name, args)
                    calls_made.append({"tool": name, "args": args})
                    blob = json.dumps(result)
                    wells_seen.update(WELL_RE.findall(blob.upper()))
                    if len(blob) > 24000:
                        blob = blob[:24000] + "...[truncated]"
                    msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": blob})
                continue
            content = ch.get("content") or ""
            return self._parse_final(content, wells_seen, calls_made)
        return {"answer": "I could not finish checking the records in time - please rephrase or narrow the question.",
                "viz": {"type": "none"}, "citations": [], "calls": calls_made}

    def _parse_final(self, content, wells_seen, calls_made):
        m = re.search(r'\{.*\}', content, re.S)
        if m:
            try:
                out = json.loads(m.group(0))
                if isinstance(out, dict) and "arguments" in out and isinstance(out["arguments"], dict):
                    out = out["arguments"]  # harmony-style JSON tool wrapper
                out.setdefault("viz", {"type": "none"})
                out.setdefault("citations", [])
                out["calls"] = calls_made
                out["wells"] = sorted(wells_seen)
                return out
            except json.JSONDecodeError:
                pass
        return {"answer": content, "viz": {"type": "none"}, "citations": [], "calls": calls_made,
                "wells": sorted(wells_seen)}
