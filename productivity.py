"""Ultron v10.7 local Daily Computer Assistant Pack.
Local SQLite productivity, reminders/timers, smarter file discovery, quick calculations,
and safe workspace helpers. No cloud credentials are required for these features.
"""
import os, re, sqlite3, threading, time, subprocess, math, ast, operator
from datetime import datetime, timedelta
from pathlib import Path

DB_DIR = Path.home()/'.ultron'
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR/'assistant.db'
_NOTIFY = None

def _conn():
    c=sqlite3.connect(DB_PATH, timeout=5)
    c.execute('CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, text TEXT, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, text TEXT, done INTEGER DEFAULT 0, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY, text TEXT, due REAL, fired INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS prefs(key TEXT PRIMARY KEY, value TEXT)')
    c.commit(); return c

def add_note(text):
    with _conn() as c: c.execute('INSERT INTO notes(text,created_at) VALUES(?,?)',(text,datetime.now().isoformat()))
    return True, 'Note saved.'
def list_notes(limit=5):
    with _conn() as c: rows=c.execute('SELECT text FROM notes ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
    return True, ('Your recent notes are: '+ '; '.join(x[0] for x in rows)) if rows else 'You have no saved notes.'
def add_task(text):
    with _conn() as c: c.execute('INSERT INTO tasks(text,created_at) VALUES(?,?)',(text,datetime.now().isoformat()))
    return True, f'Added {text} to your tasks.'
def list_tasks():
    with _conn() as c: rows=c.execute('SELECT id,text FROM tasks WHERE done=0 ORDER BY id').fetchall()
    return True, ('Your tasks are: '+ '; '.join(f'{i}. {t}' for i,t in rows)) if rows else 'Your task list is clear.'
def complete_task(query):
    q='%'+query.lower()+'%'
    with _conn() as c:
        row=c.execute('SELECT id,text FROM tasks WHERE done=0 AND lower(text) LIKE ? ORDER BY id LIMIT 1',(q,)).fetchone()
        if not row: return True, f"I couldn't find an open task matching {query}."
        c.execute('UPDATE tasks SET done=1 WHERE id=?',(row[0],))
    return True, f'Marked {row[1]} complete.'
def set_pref(spec):
    key,val=spec.split('|||',1)
    with _conn() as c: c.execute('INSERT OR REPLACE INTO prefs(key,value) VALUES(?,?)',(key.strip().lower(),val.strip()))
    return True, f"I'll use {val.strip()} when you say {key.strip()}."
def get_pref(key):
    with _conn() as c: row=c.execute('SELECT value FROM prefs WHERE key=?',(key.strip().lower(),)).fetchone()
    return row[0] if row else None

def _parse_when(text):
    s=text.lower().strip(); now=datetime.now()
    m=re.search(r'in\s+(\d+)\s*(second|seconds|minute|minutes|hour|hours)',s)
    if m:
        n=int(m.group(1)); unit=m.group(2)
        return now + (timedelta(seconds=n) if 'second' in unit else timedelta(minutes=n) if 'minute' in unit else timedelta(hours=n))
    m=re.search(r'(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?',s)
    if m:
        h=int(m.group(1)); minute=int(m.group(2) or 0); ap=m.group(3)
        if ap=='pm' and h<12: h+=12
        if ap=='am' and h==12: h=0
        due=now.replace(hour=h,minute=minute,second=0,microsecond=0)
        if due<=now: due+=timedelta(days=1)
        return due
    return None

def add_reminder(spec):
    # spec: when|||text
    when,text=spec.split('|||',1); due=_parse_when(when)
    if not due: return False, "I couldn't understand the reminder time."
    with _conn() as c: c.execute('INSERT INTO reminders(text,due) VALUES(?,?)',(text,due.timestamp()))
    return True, f"Reminder set for {due.strftime('%I:%M %p')} to {text}."
def add_timer(spec):
    m=re.search(r'(\d+)\s*(second|seconds|minute|minutes|hour|hours)',spec.lower())
    if not m: return False,"I couldn't understand the timer duration."
    n=int(m.group(1)); unit=m.group(2)
    seconds=n*(1 if 'second' in unit else 60 if 'minute' in unit else 3600)
    due=time.time()+seconds
    text=f'{n} {unit} timer finished'
    with _conn() as c:
        cur=c.execute('INSERT INTO reminders(text,due) VALUES(?,?)',(text,due))
        reminder_id=cur.lastrowid

    # Fire timers directly instead of waiting for the polling loop.
    # The database row remains as a persistence/fallback record.
    def fire():
        try:
            with _conn() as c:
                row=c.execute('SELECT fired FROM reminders WHERE id=?',(reminder_id,)).fetchone()
                if not row or row[0]:
                    return
                c.execute('UPDATE reminders SET fired=1 WHERE id=?',(reminder_id,))
            print(f'TIMER FIRED> {text}')
            if _NOTIFY:
                _NOTIFY('Timer finished.')
        except Exception as e:
            print('TIMER ERROR>',e)

    timer=threading.Timer(seconds, fire)
    timer.daemon=True
    timer.start()
    print(f'TIMER> {n} {unit} | fires in {seconds}s')
    return True, f'Timer set for {n} {unit}.'
def due_reminders():
    with _conn() as c:
        rows=c.execute('SELECT id,text FROM reminders WHERE fired=0 AND due<=? ORDER BY due',(time.time(),)).fetchall()
        if rows: c.executemany('UPDATE reminders SET fired=1 WHERE id=?',[(r[0],) for r in rows])
    return [r[1] for r in rows]

def start_reminder_worker(callback):
    global _NOTIFY
    _NOTIFY = callback
    def loop():
        while True:
            try:
                for text in due_reminders(): callback('Reminder: '+text)
            except Exception as e: print('REMINDER ERROR>',e)
            time.sleep(2)
    threading.Thread(target=loop,daemon=True).start()

def _known_roots():
    roots=[]
    for env in ('USERPROFILE','OneDrive','OneDriveConsumer'):
        b=os.environ.get(env)
        if b:
            for n in ('Desktop','Documents','Downloads','Pictures','Videos','Music'):
                p=Path(b)/n
                if p.exists() and p not in roots: roots.append(p)
    return roots

def smart_find(query, limit=8):
    q=query.lower(); words=[w for w in re.findall(r'[a-z0-9]+',q) if w not in {'my','the','a','an','file','folder','recent','recently','downloaded','find','open'}]
    want_pdf='pdf' in q; candidates=[]; now=time.time()
    for root in _known_roots():
        try:
            for cur,dirs,files in os.walk(root):
                dirs[:]=[d for d in dirs if not d.startswith('.')][:50]
                depth=len(Path(cur).relative_to(root).parts)
                if depth>4: dirs[:]=[]; continue
                for name in files:
                    p=Path(cur)/name; low=name.lower()
                    if want_pdf and p.suffix.lower()!='.pdf': continue
                    score=sum(2 for w in words if w in low)
                    try: age=(now-p.stat().st_mtime)/86400
                    except: age=9999
                    if 'recent' in q or 'downloaded' in q: score += max(0,3-age/7)
                    if score>0 or (not words and want_pdf): candidates.append((score,-age,p))
        except Exception: pass
    candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return [str(x[2]) for x in candidates[:limit]]
def smart_open(query):
    hits=smart_find(query,5)
    if not hits:return False,f"I couldn't find a matching file for {query}."
    p=Path(hits[0]); os.startfile(str(p)) if os.name=='nt' else subprocess.Popen([str(p)])
    return True,f'Opening {p.name}.'

def open_in_vscode(query):
    hits=smart_find(query,5)
    target=Path(hits[0]).parent if hits and Path(hits[0]).is_file() else (Path(hits[0]) if hits else None)
    if target is None:
        # folder-name search
        for root in _known_roots():
            for cur,dirs,_ in os.walk(root):
                for d in dirs:
                    if query.lower() in d.lower(): target=Path(cur)/d; break
                if target: break
            if target: break
    if not target:return False,f"I couldn't find {query}."
    try: subprocess.Popen(['code',str(target)]); return True,f'Opening {target.name} in VS Code.'
    except Exception:return False,'I found it, but the VS Code command is unavailable.'

def close_except(app_name):
    # Safe workspace helper: minimize all, then activate requested app through Start search.
    import pyautogui
    pyautogui.hotkey('win','d'); time.sleep(.4); pyautogui.press('win'); pyautogui.write(app_name,interval=.03); time.sleep(.5); pyautogui.press('enter')
    return True,f'Focused the workspace on {app_name}. Other windows were minimized, not destroyed.'

_ALLOWED_BIN={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow,ast.Mod:operator.mod}
def _eval(n):
    if isinstance(n,ast.Expression):return _eval(n.body)
    if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)):return n.value
    if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.USub,ast.UAdd)):return -_eval(n.operand) if isinstance(n.op,ast.USub) else _eval(n.operand)
    if isinstance(n,ast.BinOp) and type(n.op) in _ALLOWED_BIN:return _ALLOWED_BIN[type(n.op)](_eval(n.left),_eval(n.right))
    raise ValueError

def calculate(text):
    s=text.lower().replace(',','').strip()
    m=re.search(r'([0-9.]+)\s*%\s*(?:of)\s*([0-9.]+)',s)
    try:
        if m: val=float(m.group(1))*float(m.group(2))/100
        else:
            expr=re.sub(r'[^0-9+\-*/().% ]','',s).replace('%','/100')
            val=_eval(ast.parse(expr,mode='eval'))
        val=round(val,6); return True,f'The answer is {val:g}.'
    except Exception:return False,"I couldn't parse that calculation."
