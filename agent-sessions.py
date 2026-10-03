#!/usr/bin/env python3
"""agent-sessions -- phone-friendly dashboard for launching coding-agent sessions.

Lists the project folders in ~/code, creates new ones, and starts/resumes/kills
a headless Claude Code Remote Control session inside any folder (steer it from
the Claude app or claude.ai/code). Stateless: the folders on disk are the only
state. Self-contained: no shared modules, reachable only over your tailnet.

Run:  python3 agent-sessions.py [BASE_DIR] [PORT]   (defaults: ~/code, 8485)
"""
import json, os, re, shlex, shutil, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Base dir to list and port are both optional:  agent-sessions.py [BASE_DIR] [PORT]
ROOT = os.path.abspath(os.path.expanduser(sys.argv[1])) if len(sys.argv) > 1 else os.path.expanduser("~/code")
# ponytail: dedicated socket so the tmux server is spawned by this LaunchAgent's
# GUI login session -- an ssh-born "main" tmux server can't read the claude OAuth
# keychain item, which breaks `claude remote-control`.
TMUX = [shutil.which("tmux") or "/opt/homebrew/bin/tmux", "-L", "agent-sessions"]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8485
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,60}$")
# ponytail: serve the page from this sibling file, re-read per request, so HTML
# edits go live without restarting the server. Materialized from PAGE on first run.
HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-sessions.html")
CLAUDE_JSON = os.path.expanduser("~/.claude.json")

def safe_abs(name):
    """Resolve a top-level folder name under ROOT; refuse anything escaping it."""
    full = os.path.realpath(os.path.join(ROOT, name))
    if full != ROOT and not full.startswith(ROOT + os.sep):
        raise ValueError("path escapes root")
    return full

def tmux_name(name):
    """tmux session name for a folder (tmux forbids . and : in names)."""
    return "as-" + re.sub(r"[^A-Za-z0-9_-]", "-", name or "root")

def tmux_sessions():
    try:
        r = subprocess.run(TMUX + ["ls", "-F", "#S"], capture_output=True, text=True, timeout=5)
        return set(r.stdout.split())
    except Exception:
        return set()

def trust_dir(absdir):
    """Mark a workspace trusted in ~/.claude.json so headless `claude remote-control`
    won't refuse it with the trust dialog it can't display (it would exit rc=1 and the
    session would die silently). Clicking a folder in your own dashboard is the trust
    decision. No-op if already trusted, to avoid rewriting a large shared config.
    ponytail: read-modify-atomic-replace, no lock -- claude doesn't flock this file, so
    a lock is false safety; worst case a concurrent claude write is lost (a metrics
    field), never corruption, and only in the rare overlap window."""
    try:
        with open(CLAUDE_JSON, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return  # no/unreadable config: let claude handle trust itself
    proj = data.setdefault("projects", {})
    entry = proj.get(absdir)
    if isinstance(entry, dict) and entry.get("hasTrustDialogAccepted"):
        return  # already trusted
    if isinstance(entry, dict):
        entry["hasTrustDialogAccepted"] = True
    else:
        proj[absdir] = {"hasTrustDialogAccepted": True}
    tmp = CLAUDE_JSON + ".agent-sessions.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, CLAUDE_JSON)
    except OSError:
        try: os.remove(tmp)
        except OSError: pass

def open_claude(name, absdir):
    """Start a detached tmux session running claude with Remote Control in absdir."""
    # -c resumes the folder's last conversation, falls back to fresh; zsh -lc
    # restores the launchd GUI-session env claude and the keychain need.
    trust_dir(absdir)
    rc = shlex.quote(name)
    # --spawn=same-dir on the fresh-start fallback: a project's first remote-control
    # otherwise prompts for spawn mode and blocks, since nobody can answer it headless.
    # (-c resume path left bare: an existing session already has its spawn mode set.)
    cmd = (f"cd {shlex.quote(absdir)}; claude remote-control -c --name {rc}"
           f" || claude remote-control --spawn=same-dir --name {rc}")
    subprocess.run(TMUX + ["new-session", "-d", "-s", tmux_name(name),
                    f"/bin/zsh -lc {shlex.quote(cmd)}"],
                   capture_output=True, timeout=10)

def watch_self():
    """Exit when this source file changes so a KeepAlive LaunchAgent relaunches
    it with the new code -- real auto-reload (WatchPaths+KeepAlive can't, since
    launchd won't restart an always-running job). HTML is already live per request;
    this only covers .py edits. Guarded to launchd runs so a foreground dev run
    isn't killed on every save."""
    path = os.path.abspath(__file__)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return
    while True:
        threading.Event().wait(1)
        try:
            if os.path.getmtime(path) != mtime:
                os._exit(3)  # KeepAlive relaunches; crash-loops (throttled) on syntax error
        except OSError:
            pass

def list_dirs():
    """Top-level folders in ROOT, newest first, with live-session flag."""
    live = tmux_sessions()
    out = []
    with os.scandir(ROOT) as it:
        for e in it:
            if e.name.startswith(".") or not e.is_dir():
                continue
            try:
                mtime = e.stat().st_mtime
            except OSError:
                continue
            out.append({"name": e.name, "mtime": mtime,
                        "claude": tmux_name(e.name) in live})
    out.sort(key=lambda d: -d["mtime"])
    return out

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>agent-sessions</title><style>
:root{color-scheme:dark}
body{margin:0;font-family:-apple-system,system-ui,sans-serif;background:#111;color:#ddd}
header{position:sticky;top:0;background:#111;padding:12px 16px;border-bottom:1px solid #2a2a2a}
h1{font-size:17px;margin:0 0 8px}
.count{font-size:13px;color:#999}
.chips{display:flex;gap:8px}
.chip{border:1px solid #444;border-radius:14px;padding:4px 12px;font-size:13px;cursor:pointer;background:none;color:#bbb}
#newform{padding-top:10px}
#nf-name{background:#1a1a1a;border:1px solid #444;border-radius:8px;padding:5px 10px;color:#ddd;width:180px}
.dbtn{border:1px solid #444;background:none;color:#bbb;border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer}
.row{display:flex;align-items:center;gap:10px;padding:11px 14px;margin:8px 12px;border:1px solid #2a2a2a;border-radius:10px;background:#15151d}
.name{flex:1;font-size:14px;font-weight:600;word-break:break-all}
.date{font-size:11px;color:#666;white-space:nowrap}
.mk{border:1px solid #444;background:none;color:#888;border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer}
.mk.live{border-color:#6c6;color:#6c6}
</style></head><body>
<header><h1>agent-sessions <span class="count" id="count"></span></h1>
<div class="chips">
<button class="chip" id="newbtn">+ new folder</button>
<input id="q" placeholder="search" autocapitalize="none" autocorrect="off" spellcheck="false"
 style="width:110px;background:none;border:1px solid #444;border-radius:14px;padding:4px 12px;font-size:13px;color:#ddd">
</div>
<div id="newform" style="display:none">
<input id="nf-name" placeholder="new folder name" autocapitalize="none" autocorrect="off" spellcheck="false">
<button class="dbtn" onclick="mkdirGo()">create</button>
</div>
</header><div id="list"></div><script>
let DATA=[],Q="";
function fdate(t){const d=new Date(t*1000),now=new Date();
  return d.toLocaleDateString("en-US",{month:"short",day:"numeric",
    year:d.getFullYear()==now.getFullYear()?undefined:"numeric"})}
async function post(u,body){await fetch(u,{method:"POST",body:JSON.stringify(body)});refresh()}
function render(){
  const el=document.getElementById("list");el.innerHTML="";
  const rows=DATA.filter(d=>!Q||d.name.toLowerCase().includes(Q));
  document.getElementById("count").textContent=rows.length+" folders";
  rows.forEach(d=>{
    const el2=document.createElement("div");el2.className="row";
    el2.innerHTML=`<div class="name">${d.name}</div><div class="date">${fdate(d.mtime)}</div>`+
      (d.claude
        ?`<button class="mk live" title="kill the remote claude session" onclick='post("/api/claude-stop",{name:${JSON.stringify(d.name)}})'>end claude ●</button>`
        :`<button class="mk" title="start remote-control claude session" onclick='post("/api/claude",{name:${JSON.stringify(d.name)}})'>claude</button>`);
    el.appendChild(el2);
  });
}
async function mkdirGo(){
  const name=document.getElementById("nf-name").value.trim();
  if(!name)return;
  const j=await(await fetch("/api/mkdir",{method:"POST",body:JSON.stringify({name})})).json();
  if(j.err){alert(j.err);return}
  document.getElementById("nf-name").value="";
  document.getElementById("newform").style.display="none";refresh();
}
async function refresh(){
  DATA=(await(await fetch("/api/state")).json()).dirs;render();
}
document.getElementById("newbtn").onclick=()=>{
  const f=document.getElementById("newform");
  f.style.display=f.style.display=="none"?"":"none";
  document.getElementById("nf-name").focus();
};
document.getElementById("q").oninput=e=>{Q=e.target.value.trim().toLowerCase();render()};
refresh();
setInterval(()=>{if(!document.hidden)refresh()},15000);
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            self._json({"dirs": list_dirs()})
        else:
            try:
                body = open(HTML_FILE, encoding="utf-8").read().encode()
            except OSError:
                body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n))
        except Exception:
            return self._json({"err": "bad json"}, 400)
        try:
            self._handle_post(req)
        except ValueError:
            self._json({"err": "bad path"}, 400)

    def _handle_post(self, req):
        if self.path == "/api/mkdir":
            name = (req.get("name") or "").strip()
            if not SAFE_NAME.match(name):
                return self._json({"err": "bad name"}, 400)
            os.makedirs(safe_abs(name), exist_ok=True)
        elif self.path == "/api/claude":
            name = (req.get("name") or "").strip()
            full = safe_abs(name)
            if not os.path.isdir(full):
                return self._json({"err": "no such dir"}, 400)
            open_claude(name, full)
        elif self.path == "/api/claude-stop":
            sess = tmux_name(req.get("name", ""))
            r = subprocess.run(TMUX + ["kill-session", "-t", sess],
                               capture_output=True, text=True, timeout=5)
            # returncode!=0 means the session was already gone -- report it either way
            return self._json({"ok": r.returncode == 0, "session": sess,
                               "detail": (r.stderr or r.stdout).strip()})
        else:
            return self._json({"err": "bad request"}, 400)
        self._json({"ok": True})

if __name__ == "__main__":
    if not os.path.exists(HTML_FILE):
        open(HTML_FILE, "w", encoding="utf-8").write(PAGE)
    print(f"agent-sessions on http://0.0.0.0:{PORT}  (root: {ROOT}, page: {HTML_FILE})")
    # only self-restart under launchd, so a foreground `python3 agent-sessions.py`
    # dev run isn't killed on every save
    if os.environ.get("XPC_SERVICE_NAME", "0") not in ("", "0"):
        threading.Thread(target=watch_self, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
