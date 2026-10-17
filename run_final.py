"""Final-phase runner: load a dataset folder fresh, run final questions from a text file
(one question per line, optional '<user name> | question' prefix), save answers to JSON."""
import json, os, sys, time, urllib.request

BASE = os.environ.get('BASE', 'http://localhost:8000')

def uid_map():
    r = json.loads(urllib.request.urlopen(BASE + '/api/users').read())
    return {u['name'].split()[0].lower(): u['user_id'] for u in r['users']}, r['users']

def ask(user_id, msg, session):
    body = json.dumps({'user_id': user_id, 'session_id': session, 'message': msg}).encode()
    req = urllib.request.Request(BASE + '/api/chat', data=body, headers={'Content-Type': 'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except Exception as e:
            print('  retry', attempt, type(e).__name__, flush=True)
            time.sleep(15)
    return {'error': 'unreachable'}

def main(qfile, outfile):
    names, users = uid_map()
    first = users[0]['user_id']
    results = []
    for i, line in enumerate(open(qfile)):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '|' in line:
            who, q = [p.strip() for p in line.split('|', 1)]
            u = names.get(who.split()[0].lower(), first)
        else:
            u, q = first, line
        print(f'[{i+1}] {q[:80]}', flush=True)
        r = ask(u, q, f'final-{i+1}')
        results.append({'question': q, 'user_id': u, 'response': r})
        print('  ->', (r.get('answer') or r.get('error') or '')[:140].replace('\n', ' '), flush=True)
        json.dump(results, open(outfile, 'w'), indent=1)
    print('DONE ->', outfile, flush=True)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
