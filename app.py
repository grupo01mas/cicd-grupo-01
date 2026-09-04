# ABOUTME: Flask todolist app with SQLite backend, session-based authentication,
# ABOUTME: and a /pods route that queries the Kubernetes API via ServiceAccount.
import logging
import os
from datetime import datetime
from functools import wraps

import requests as http
from flask import Flask, redirect, render_template_string, request, session
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
app.secret_key = os.environ.get('SESSION_KEY', 'dev-only-insecure-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI', 'sqlite:////data/todos.db')
db = SQLAlchemy(app)

ADMIN_USER      = os.environ.get('ADMIN_USER', 'admin')
ADMIN_PASSWORD  = os.environ.get('ADMIN_PASSWORD', 'admin')
CLEANUP_TOKEN   = os.environ.get('CLEANUP_TOKEN', '')
CLEANUP_JOB_PREFIX = os.environ.get('CLEANUP_JOB_PREFIX', 'todolist-cleanup')

def _parse_image_tags(raw):
    tags = [tag.strip() for tag in raw.replace(',', '\n').splitlines() if tag.strip()]
    return [tag.rsplit(':', 1)[-1] for tag in tags]

# Docker image tags this build was published under, injected by CI. Empty for local builds.
IMAGE_TAGS = _parse_image_tags(os.environ.get('IMAGE_TAGS', ''))

COLORS = {
    'purple': ('#7c3aed', '#6d28d9'),
    'green':  ('#16a34a', '#15803d'),
    'blue':   ('#2563eb', '#1d4ed8'),
    'cyan':   ('#0891b2', '#0e7490'),
    'pink':   ('#db2777', '#be185d'),
    'red':    ('#dc2626', '#b91c1c'),
    'orange': ('#ea580c', '#c2410c'),
    'brown':  ('#92400e', '#78350f'),
    'yellow': ('#ca8a04', '#a16207'),
}
ACCENT, ACCENT_HOVER = COLORS.get(os.environ.get('APP_COLOR', '').lower(), ('#64748b', '#475569'))

K8S_TOKEN_PATH = '/var/run/secrets/kubernetes.io/serviceaccount/token'
K8S_NS_PATH    = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'
K8S_CA_PATH    = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'

class Todo(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    task = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, default=False)

def _k8s_namespace():
    return open(K8S_NS_PATH).read()

def _k8s_get(path):
    token = open(K8S_TOKEN_PATH).read()
    headers = {'Authorization': f'Bearer {token}'}
    resp = http.get(f'https://kubernetes.default.svc{path}', headers=headers, verify=K8S_CA_PATH, timeout=3)
    resp.raise_for_status()
    return resp

def _k8s_patch(path, body):
    token = open(K8S_TOKEN_PATH).read()
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/merge-patch+json',
    }
    resp = http.patch(f'https://kubernetes.default.svc{path}', headers=headers, json=body, verify=K8S_CA_PATH, timeout=3)
    resp.raise_for_status()
    return resp

def get_pods():
    try:
        namespace = _k8s_namespace()
        items = _k8s_get(f'/api/v1/namespaces/{namespace}/pods').json().get('items', [])
        return [
            {
                'name':   p['metadata']['name'],
                'node':   p['spec'].get('nodeName', 'unknown'),
                'status': p['status'].get('phase', 'unknown'),
                'ip':     p['status'].get('podIP', 'unknown'),
            }
            for p in items
        ]
    except Exception:
        app.logger.exception('failed to list pods from the Kubernetes API')
        return None

def get_cleanup_history():
    try:
        namespace = _k8s_namespace()

        pods_resp = _k8s_get(f'/api/v1/namespaces/{namespace}/pods')
        pods = [
            p for p in pods_resp.json().get('items', [])
            if p.get('metadata', {}).get('labels', {}).get('job-name', '').startswith(CLEANUP_JOB_PREFIX)
        ]

        history = []
        for pod in pods:
            name     = pod['metadata']['name']
            job_name = pod['metadata']['labels']['job-name']
            ts       = pod['metadata']['creationTimestamp']
            started  = datetime.fromisoformat(ts.replace('Z', '+00:00')).strftime('%d/%b %H:%M')

            try:
                result = _k8s_get(f'/api/v1/namespaces/{namespace}/pods/{name}/log').text.strip()
            except Exception:
                app.logger.exception('failed to fetch logs for cleanup pod %s', name)
                result = '—'

            history.append({'job_name': job_name, 'started': started, 'result': result or '—'})

        history.sort(key=lambda x: x['started'], reverse=True)
        return history
    except Exception:
        app.logger.exception('failed to fetch cleanup job history from the Kubernetes API')
        return None

def get_cronjob_suspended():
    try:
        namespace = _k8s_namespace()
        cronjob = _k8s_get(f'/apis/batch/v1/namespaces/{namespace}/cronjobs/{CLEANUP_JOB_PREFIX}').json()
        return cronjob['spec']['suspend']
    except Exception:
        app.logger.exception('failed to read cleanup CronJob state from the Kubernetes API')
        return None

def set_cronjob_suspended(value):
    namespace = _k8s_namespace()
    _k8s_patch(f'/apis/batch/v1/namespaces/{namespace}/cronjobs/{CLEANUP_JOB_PREFIX}', {'spec': {'suspend': value}})

THEME_SCRIPT = '''
  <script>
    (function() {
      if (localStorage.getItem('theme') === 'dark') {
        document.documentElement.classList.add('dark');
      }
    })();
    function toggleTheme() {
      const dark = document.documentElement.classList.toggle('dark');
      localStorage.setItem('theme', dark ? 'dark' : 'light');
      document.getElementById('theme-btn').textContent = dark ? '☀' : '☾';
    }
  </script>
'''

BASE_CSS = '''
    :root {
      --bg:           #f0f2f5;
      --card-bg:      #ffffff;
      --text:         #1e293b;
      --text-muted:   #94a3b8;
      --border:       #e2e8f0;
      --border-light: #f1f5f9;
      --th-bg:        #f8fafc;
      --th-color:     #64748b;
      --hover-bg:     #f1f5f9;
      --current-row:  #ede9fe;
      --input-bg:     #ffffff;
      --label-color:  #475569;
      --error-bg:     #fef2f2;
      --error-color:  #dc2626;
      --error-border: #fecaca;
    }
    .dark {
      --bg:           #0f172a;
      --card-bg:      #1e293b;
      --text:         #e2e8f0;
      --text-muted:   #64748b;
      --border:       #334155;
      --border-light: #273344;
      --th-bg:        #162032;
      --th-color:     #94a3b8;
      --hover-bg:     #273344;
      --current-row:  #2d1f4e;
      --input-bg:     #0f172a;
      --label-color:  #94a3b8;
      --error-bg:     #2d1215;
      --error-color:  #f87171;
      --error-border: #7f1d1d;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      transition: background 0.2s, color 0.2s;
    }
'''

LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <title>Login — {{ app_name }}</title>
  ''' + THEME_SCRIPT + '''
  <style>
    ''' + BASE_CSS + '''
    body {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .card {
      background: var(--card-bg);
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      width: 100%;
      max-width: 360px;
      overflow: hidden;
    }
    .card-header {
      background: ''' + ACCENT + ''';
      padding: 24px 28px;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
    }
    .card-header h1 { color: #fff; font-size: 1.3rem; font-weight: 600; }
    .card-header p  { color: rgba(255,255,255,0.75); font-size: 0.82rem; margin-top: 4px; }
    .theme-btn {
      background: rgba(255,255,255,0.15);
      border: 1px solid rgba(255,255,255,0.3);
      color: #fff;
      border-radius: 6px;
      padding: 4px 8px;
      cursor: pointer;
      font-size: 0.85rem;
      align-self: center;
    }
    .card-body { padding: 28px; }
    .field { margin-bottom: 16px; }
    .field label {
      display: block;
      font-size: 0.82rem;
      font-weight: 500;
      color: var(--label-color);
      margin-bottom: 6px;
    }
    .field input {
      width: 100%;
      padding: 10px 14px;
      border: 1.5px solid var(--border);
      border-radius: 8px;
      font-size: 0.95rem;
      background: var(--input-bg);
      color: var(--text);
      outline: none;
      transition: border-color 0.15s;
    }
    .field input:focus { border-color: ''' + ACCENT + '''; }
    .error {
      background: var(--error-bg);
      color: var(--error-color);
      border: 1px solid var(--error-border);
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 0.85rem;
      margin-bottom: 16px;
    }
    button[type=submit] {
      width: 100%;
      padding: 11px;
      background: ''' + ACCENT + ''';
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 0.95rem;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s;
    }
    button[type=submit]:hover { background: ''' + ACCENT_HOVER + '''; }
  </style>
</head>
<body>
  <div class="card">
    <div class="card-header">
      <div>
        <h1>{{ app_name }}</h1>
        <p>Sign in to continue</p>
      </div>
      <button id="theme-btn" class="theme-btn" onclick="toggleTheme()">☾</button>
    </div>
    <div class="card-body">
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
      <form method="POST" action="/login">
        <div class="field">
          <label>Username</label>
          <input name="username" type="text" autocomplete="username" autofocus>
        </div>
        <div class="field">
          <label>Password</label>
          <input name="password" type="password" autocomplete="current-password">
        </div>
        <button type="submit">Sign in</button>
      </form>
    </div>
  </div>
  <script>
    document.getElementById('theme-btn').textContent =
      document.documentElement.classList.contains('dark') ? '☀' : '☾';
  </script>
</body>
</html>
'''

MAIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <title>{{ app_name }}</title>
  ''' + THEME_SCRIPT + '''
  <style>
    ''' + BASE_CSS + '''
    body {
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 48px 16px;
    }
    .card {
      background: var(--card-bg);
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      width: 100%;
      max-width: 520px;
      overflow: hidden;
    }
    .card-header {
      background: ''' + ACCENT + ''';
      padding: 24px 28px;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .card-header h1 { color: #fff; font-size: 1.4rem; font-weight: 600; }
    .pod-badge {
      display: inline-block;
      margin-top: 6px;
      background: rgba(255,255,255,0.2);
      color: rgba(255,255,255,0.9);
      font-size: 0.72rem;
      font-family: monospace;
      padding: 2px 8px;
      border-radius: 99px;
    }
    .header-actions { display: flex; gap: 8px; align-self: center; }
    .btn-header {
      background: rgba(255,255,255,0.15);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px;
      padding: 5px 12px;
      font-size: 0.8rem;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.15s;
      text-decoration: none;
    }
    .btn-header:hover { background: rgba(255,255,255,0.25); }
    .card-body { padding: 24px 28px; }
    .error {
      background: var(--error-bg);
      color: var(--error-color);
      border: 1px solid var(--error-border);
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 0.85rem;
      margin-bottom: 16px;
    }
    .add-form { display: flex; gap: 8px; margin-bottom: 24px; }
    .add-form input {
      flex: 1;
      padding: 10px 14px;
      border: 1.5px solid var(--border);
      border-radius: 8px;
      font-size: 0.95rem;
      background: var(--input-bg);
      color: var(--text);
      outline: none;
      transition: border-color 0.15s;
    }
    .add-form input:focus { border-color: ''' + ACCENT + '''; }
    .add-form button {
      padding: 10px 18px;
      background: ''' + ACCENT + ''';
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 0.95rem;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s;
    }
    .add-form button:hover { background: ''' + ACCENT_HOVER + '''; }
    .todo-list { list-style: none; }
    .todo-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 0;
      border-bottom: 1px solid var(--border-light);
    }
    .todo-item:last-child { border-bottom: none; }
    .btn-icon {
      background: none;
      border: none;
      cursor: pointer;
      font-size: 1.1rem;
      padding: 2px 4px;
      border-radius: 4px;
      line-height: 1;
      transition: background 0.1s;
    }
    .btn-icon:hover { background: var(--hover-bg); }
    .btn-delete { color: var(--text-muted); font-size: 0.9rem; margin-left: auto; }
    .btn-delete:hover { color: #ef4444; background: var(--error-bg); }
    .todo-text { flex: 1; font-size: 0.95rem; color: var(--text); }
    .todo-text.done { text-decoration: line-through; color: var(--text-muted); }
    .empty { text-align: center; color: var(--text-muted); font-size: 0.9rem; padding: 32px 0; }
    .card-footer {
      padding: 12px 28px;
      border-top: 1px solid var(--border-light);
      color: var(--text-muted);
      font-size: 0.75rem;
      font-family: monospace;
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="card-header">
      <div>
        <h1>{{ app_name }}</h1>
        <span class="pod-badge">pod: {{ hostname }}</span>
      </div>
      <div class="header-actions">
        <button id="theme-btn" class="btn-header" onclick="toggleTheme()">☾</button>
        <a href="/pods" class="btn-header">Pods</a>
        <a href="/cleanup/status" class="btn-header">Cleanup</a>
        <a href="/logout" class="btn-header">Sign out</a>
      </div>
    </div>
    <div class="card-body">
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
      <form class="add-form" method="POST" action="/add">
        <input name="task" placeholder="New task..." autocomplete="off" autofocus>
        <button type="submit">Add</button>
      </form>
      {% if todos %}
      <ul class="todo-list">
        {% for t in todos %}
        <li class="todo-item">
          <form method="POST" action="/toggle/{{ t.id }}">
            <button class="btn-icon">{% if t.done %}✅{% else %}⬜{% endif %}</button>
          </form>
          <span class="todo-text {% if t.done %}done{% endif %}">{{ t.task }}</span>
          <form method="POST" action="/delete/{{ t.id }}">
            <button class="btn-icon btn-delete">✕</button>
          </form>
        </li>
        {% endfor %}
      </ul>
      {% else %}
      <p class="empty">No tasks yet. Add one above.</p>
      {% endif %}
    </div>
    {% if image_tags %}
    <div class="card-footer">
      version:
      {% for tag in image_tags %}<span>{{ tag }}</span>{% if not loop.last %} · {% endif %}{% endfor %}
    </div>
    {% endif %}
  </div>
  <script>
    document.getElementById('theme-btn').textContent =
      document.documentElement.classList.contains('dark') ? '☀' : '☾';
  </script>
</body>
</html>
'''

PODS_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <title>Pods — {{ app_name }}</title>
  ''' + THEME_SCRIPT + '''
  <style>
    ''' + BASE_CSS + '''
    body {
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 48px 16px;
    }
    .card {
      background: var(--card-bg);
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      width: 100%;
      max-width: 620px;
      overflow: hidden;
    }
    .card-header {
      background: ''' + ACCENT + ''';
      padding: 24px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .card-header h1 { color: #fff; font-size: 1.4rem; font-weight: 600; }
    .header-actions { display: flex; gap: 8px; }
    .btn-header {
      background: rgba(255,255,255,0.15);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px;
      padding: 5px 12px;
      font-size: 0.8rem;
      cursor: pointer;
      text-decoration: none;
      transition: background 0.15s;
    }
    .btn-header:hover { background: rgba(255,255,255,0.25); }
    .card-body { padding: 24px 28px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th {
      text-align: left;
      padding: 8px 12px;
      background: var(--th-bg);
      color: var(--th-color);
      font-weight: 600;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid var(--border);
    }
    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border-light);
      color: var(--text);
      font-family: monospace;
    }
    tr:last-child td { border-bottom: none; }
    tr.current td { background: var(--current-row); }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 99px;
      font-size: 0.75rem;
      font-weight: 500;
    }
    .badge-running  { background: #dcfce7; color: #16a34a; }
    .badge-pending  { background: #fef9c3; color: #ca8a04; }
    .badge-unknown  { background: var(--th-bg); color: var(--th-color); }
    .unavailable { text-align: center; color: var(--text-muted); font-size: 0.9rem; padding: 32px 0; }
  </style>
</head>
<body>
  <div class="card">
    <div class="card-header">
      <h1>Pods</h1>
      <div class="header-actions">
        <button id="theme-btn" class="btn-header" onclick="toggleTheme()">☾</button>
        <a href="/" class="btn-header">Back</a>
      </div>
    </div>
    <div class="card-body">
      {% if pods is none %}
      <p class="unavailable">Unable to query the Kubernetes API. Check that the ServiceAccount has the required permissions.</p>
      {% elif pods %}
      <table>
        <thead>
          <tr>
            <th>Pod</th>
            <th>Node</th>
            <th>IP</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {% for pod in pods %}
          <tr {% if pod.name == hostname %}class="current"{% endif %}>
            <td>{{ pod.name }}{% if pod.name == hostname %} ★{% endif %}</td>
            <td>{{ pod.node }}</td>
            <td>{{ pod.ip }}</td>
            <td>
              <span class="badge badge-{{ pod.status | lower }}">{{ pod.status }}</span>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <p class="unavailable">No pods found in the namespace.</p>
      {% endif %}
    </div>
  </div>
  <script>
    document.getElementById('theme-btn').textContent =
      document.documentElement.classList.contains('dark') ? '☀' : '☾';
  </script>
</body>
</html>
'''

CLEANUP_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <title>Cleanup — {{ app_name }}</title>
  ''' + THEME_SCRIPT + '''
  <style>
    ''' + BASE_CSS + '''
    body { display: flex; align-items: flex-start; justify-content: center; padding: 48px 16px; }
    .card {
      background: var(--card-bg);
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      width: 100%;
      max-width: 620px;
      overflow: hidden;
    }
    .card-header {
      background: ''' + ACCENT + ''';
      padding: 24px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .card-header h1 { color: #fff; font-size: 1.4rem; font-weight: 600; }
    .header-actions { display: flex; gap: 8px; }
    .btn-header {
      background: rgba(255,255,255,0.15);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.3);
      border-radius: 6px;
      padding: 5px 12px;
      font-size: 0.8rem;
      cursor: pointer;
      text-decoration: none;
      transition: background 0.15s;
    }
    .btn-header:hover { background: rgba(255,255,255,0.25); }
    .card-body { padding: 24px 28px; }
    .error {
      background: var(--error-bg);
      color: var(--error-color);
      border: 1px solid var(--error-border);
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 0.85rem;
      margin-bottom: 16px;
    }
    .cronjob-status {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--th-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 20px;
      font-size: 0.88rem;
    }
    .cronjob-status form { margin: 0; }
    .btn-toggle {
      padding: 6px 14px;
      background: ''' + ACCENT + ''';
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s;
    }
    .btn-toggle:hover { background: ''' + ACCENT_HOVER + '''; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th {
      text-align: left;
      padding: 8px 12px;
      background: var(--th-bg);
      color: var(--th-color);
      font-weight: 600;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border-bottom: 1px solid var(--border);
    }
    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border-light);
      color: var(--text);
      font-family: monospace;
    }
    tr:last-child td { border-bottom: none; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 99px;
      font-size: 0.75rem;
      font-weight: 500;
    }
    .badge-ok      { background: #dcfce7; color: #16a34a; }
    .badge-empty   { background: var(--th-bg); color: var(--th-color); }
    .badge-error   { background: #fef2f2; color: #dc2626; }
    .unavailable { text-align: center; color: var(--text-muted); font-size: 0.9rem; padding: 32px 0; }
  </style>
</head>
<body>
  <div class="card">
    <div class="card-header">
      <h1>Cleanup History</h1>
      <div class="header-actions">
        <button id="theme-btn" class="btn-header" onclick="toggleTheme()">☾</button>
        <a href="/" class="btn-header">Back</a>
      </div>
    </div>
    <div class="card-body">
      {% if error %}
      <div class="error">{{ error }}</div>
      {% endif %}
      {% if suspended is not none %}
      <div class="cronjob-status">
        <span>CronJob: {% if suspended %}Suspended{% else %}Active{% endif %}</span>
        <form method="POST" action="/cleanup/status">
          <input type="hidden" name="action" value="{% if suspended %}resume{% else %}suspend{% endif %}">
          <button type="submit" class="btn-toggle">{% if suspended %}Resume{% else %}Suspend{% endif %}</button>
        </form>
      </div>
      {% else %}
      <div class="cronjob-status">
        <span>CronJob: unknown state</span>
      </div>
      {% endif %}
      {% if history is none %}
      <p class="unavailable">Unable to query the Kubernetes API. Check that the ServiceAccount has the required permissions.</p>
      {% elif history %}
      <table>
        <thead>
          <tr>
            <th>Job</th>
            <th>Started at</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {% for h in history %}
          <tr>
            <td>{{ h.job_name }}</td>
            <td>{{ h.started }}</td>
            <td>
              {% if h.result.startswith("deleted 0") %}
              <span class="badge badge-empty">{{ h.result }}</span>
              {% elif h.result.startswith("deleted") %}
              <span class="badge badge-ok">{{ h.result }}</span>
              {% else %}
              <span class="badge badge-error">{{ h.result }}</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
      <p class="unavailable">No cleanup jobs found. Wait for the CronJob to run.</p>
      {% endif %}
    </div>
  </div>
  <script>
    document.getElementById('theme-btn').textContent =
      document.documentElement.classList.contains('dark') ? '☀' : '☾';
  </script>
</body>
</html>
'''

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username') == ADMIN_USER and
                request.form.get('password') == ADMIN_PASSWORD):
            session['logged_in'] = True
            return redirect('/')
        error = 'Invalid username or password.'
    return render_template_string(LOGIN_HTML,
        app_name=os.environ.get('APP_NAME', 'TodoList'),
        error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/')
@login_required
def index():
    todos = Todo.query.all()
    return render_template_string(MAIN_HTML,
        todos=todos,
        hostname=os.environ.get('HOSTNAME', 'unknown'),
        app_name=os.environ.get('APP_NAME', 'TodoList'),
        image_tags=IMAGE_TAGS)

@app.route('/pods')
@login_required
def pods():
    return render_template_string(PODS_HTML,
        pods=get_pods(),
        hostname=os.environ.get('HOSTNAME', 'unknown'),
        app_name=os.environ.get('APP_NAME', 'TodoList'))

@app.route('/cleanup/status', methods=['GET', 'POST'])
@login_required
def cleanup_status():
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            set_cronjob_suspended(action == 'suspend')
        except Exception:
            app.logger.exception('failed to update cleanup CronJob suspend state')
            error = 'Unable to update the CronJob. Check that the ServiceAccount has the required permissions.'
    return render_template_string(CLEANUP_HTML,
        history=get_cleanup_history(),
        suspended=get_cronjob_suspended(),
        app_name=os.environ.get('APP_NAME', 'TodoList'),
        error=error)

@app.route('/add', methods=['POST'])
@login_required
def add():
    task = request.form.get('task', '').strip()
    if task:
        duplicate = Todo.query.filter(
            Todo.done.is_(False),
            db.func.lower(Todo.task) == task.lower()
        ).first()
        if duplicate:
            return render_template_string(MAIN_HTML,
                todos=Todo.query.all(),
                hostname=os.environ.get('HOSTNAME', 'unknown'),
                app_name=os.environ.get('APP_NAME', 'TodoList'),
                image_tags=IMAGE_TAGS,
                error='This task already exists.')
        db.session.add(Todo(task=task))
        db.session.commit()
    return redirect('/')

@app.route('/toggle/<int:todo_id>', methods=['POST'])
@login_required
def toggle(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    todo.done = not todo.done
    db.session.commit()
    return redirect('/')

@app.route('/delete/<int:todo_id>', methods=['POST'])
@login_required
def delete(todo_id):
    todo = Todo.query.get_or_404(todo_id)
    db.session.delete(todo)
    db.session.commit()
    return redirect('/')

@app.route('/healthz')
def health():
    try:
        db.session.execute(db.text('SELECT 1'))
        return 'ok', 200
    except Exception:
        return 'database unavailable', 503

@app.route('/cleanup', methods=['POST'])
def cleanup():
    if request.headers.get('X-Cleanup-Token', '') != CLEANUP_TOKEN or not CLEANUP_TOKEN:
        return 'Unauthorized', 401
    deleted = Todo.query.filter_by(done=True).delete()
    db.session.commit()
    return f'deleted {deleted}', 200

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('APP_PORT', '5000'))
    app.run(host='0.0.0.0', port=port)
