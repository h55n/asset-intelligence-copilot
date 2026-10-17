import json, os, uuid
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from core import Copilot
from tools import Tools
from agent import Agent

DATA_DIR = os.environ.get('DATA_DIR', 'sample-data')
DB_PATH = os.environ.get('DB_PATH', '/tmp/copilot.db')
TODAY = os.environ.get('COPILOT_TODAY', '2026-10-17')
BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.groq.com/openai/v1')
API_KEY = os.environ.get('LLM_API_KEY', '')
MODEL = os.environ.get('LLM_MODEL', 'openai/gpt-oss-120b')

if not os.path.exists(DB_PATH):
    from ingest import ingest
    print('ingesting', DATA_DIR, ingest(DATA_DIR, DB_PATH))

cp = Copilot(DB_PATH, today=TODAY)
tools = Tools(cp)
agent = Agent(tools, BASE_URL, API_KEY, MODEL, TODAY)
app = FastAPI(title='Asset Intelligence Copilot')

class ChatIn(BaseModel):
    user_id: str
    session_id: str | None = None
    message: str

@app.get('/')
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), 'static', 'index.html'))

@app.get('/api/users')
def users():
    return {'users': cp.q("SELECT u.user_id, u.name, u.role, t.name AS team FROM users u LEFT JOIN teams t ON t.team_id=u.team_id ORDER BY u.user_id")}

@app.post('/api/chat')
def chat(body: ChatIn):
    user = cp.q("SELECT * FROM users WHERE user_id=?", (body.user_id,))
    if not user:
        return JSONResponse({'error': 'unknown user'}, status_code=400)
    user = user[0]
    session = body.session_id or uuid.uuid4().hex[:12]
    history = cp.chat_history(user['user_id'], limit=4)
    try:
        r = agent.answer(user['name'], user['user_id'], session, body.message, history)
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({'error': f'{type(e).__name__}: {e}', 'session_id': session}, status_code=500)
    cp.log_chat(user['user_id'], session, 'user', body.message, r.get('wells', []))
    cp.log_chat(user['user_id'], session, 'assistant', r.get('answer', ''), r.get('wells', []))
    r['session_id'] = session
    return r

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
