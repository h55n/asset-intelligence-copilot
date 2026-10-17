"""Run the 18 example scenarios against the live server and log answers."""
import json, time, urllib.request

BASE = 'http://localhost:8000'
U = {'michael': 'U-201', 'jessica': 'U-202', 'tyler': 'U-204', 'jake': 'U-102', 'laura': None}
# laura id resolved at runtime
def uid(name):
    r = json.loads(urllib.request.urlopen(BASE + '/api/users').read())
    for u in r['users']:
        if u['name'].lower().startswith(name):
            return u['user_id']
    raise KeyError(name)

def ask(user_id, msg, session):
    body = json.dumps({'user_id': user_id, 'session_id': session, 'message': msg}).encode()
    req = urllib.request.Request(BASE + '/api/chat', data=body, headers={'Content-Type': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == 2: return {'error': str(e)}
            time.sleep(10)

def main():
    laura = uid('laura')
    out = []
    def run(tag, user_id, msg, session):
        print(f'[{tag}] {msg[:70]}', flush=True)
        r = ask(user_id, msg, session)
        out.append({'tag': tag, 'q': msg, 'r': r})
        a = (r.get('answer') or r.get('error') or '')[:160].replace('\n', ' ')
        print(f'  -> {a}', flush=True)
        return r

    M, J, T, K, L = uid('michael'), uid('jessica'), uid('tyler'), uid('jake'), laura
    run('Q1', M, 'Is WELL-0001 producing oil right now? When was it last inspected, and by whom?', 'q1')
    run('Q2', M, 'Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table.', 'q2')
    run('Q3', M, "Show a line chart of WELL-0001's wellhead temperature against air temperature for the last 13 weeks, and mark when it was not producing oil.", 'q3')
    run('Q4', M, 'How many oil spills has WELL-0001 had in the last 4 years, and how much oil in total? List them in a table.', 'q4')
    run('Q5', M, 'How many days was WELL-0001 down in 2025?', 'q5')
    run('Q6', M, 'Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart.', 'q6')
    run('Q7', M, 'Show on a map every well in Northeast Block 8 with a real spill in the last 90 days.', 'q7')
    run('Q8', M, 'Show a heatmap of 2026 spills by geographic area and month.', 'q8')
    run('Q9', M, 'Which rules has WELL-0001 broken in the last 12 months, and what is still open?', 'q9')
    run('Q10', M, 'In Southwest Block 24, which spills in the last 90 days were not contained within the SOP time limit?', 'q10')
    run('Q11a', M, 'Which 3 wells in Northeast Block 7 had the most downtime in the last 4 months? Show a bar chart.', 'q11-day1')
    run('Q11b', M, 'For the three wells we discussed yesterday, what have repairs cost this year?', 'q11-day2')
    run('Q12a', M, 'The 15 Oct reading for WELL-0164 is wrong. The handheld thermal gun used in that inspection was faulty; the field crew re-measured the wellhead at 41.0 C.', 'q12')
    run('Q12b', M, 'Which wells in Northeast Block 8 are not producing oil right now, and why? Show them in a table.', 'q12')
    run('Q13', M, 'The AI estimated the 24 Sep spill at WELL-0151 as 4.5 bbl. The field crew measured 5.4 bbl.', 'q13')
    run('Q14a', M, 'Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?', 'q14')
    run('Q14b', M, 'Note for all T350 wells: our team now wants a pump jack root-cause analysis after 2 repairs, not 3.', 'q14')
    run('Q14c', M, 'Which wells in Northeast Block 7 need a root-cause analysis on their pump jack?', 'q14b')
    run('Q15a', J, 'Is WELL-0164 producing oil right now?', 'q15j')
    run('Q15b', L, 'Which spills in Northeast Block 8 in the last 90 days needed a report to the regulator?', 'q15l')
    run('Q16a', K, 'FYI for everyone: WELL-0007 will be shut in from 17 Oct for a 10-day planned workover.', 'q16k')
    run('Q16b', M, 'Is any downtime planned for WELL-0007?', 'q16m')
    run('Q16c', J, 'For the three wells we discussed yesterday, what have repairs cost this year?', 'q16j')
    run('Q17a', M, 'WELL-0175 has been shut in for planned work since 14 Oct.', 'q17m')
    run('Q17b', T, 'WELL-0175 is running fine.', 'q17t')
    run('Q17c', K, 'WELL-0001 is back online since 14 Oct.', 'q17k')
    run('Q18', M, 'Was the 20 Aug spill at WELL-0101 real oil?', 'q18')
    json.dump(out, open('/tmp/suite_results.json', 'w'), indent=1)
    print('DONE', flush=True)

if __name__ == '__main__':
    main()
