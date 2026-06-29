
# app.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os
import subprocess
import random
import string
import uuid
from datetime import datetime, timedelta
import sys
import shutil
import threading
import time
import zipfile
import psutil
import hashlib
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = 'jubayer-super-secret-key-2026'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# ============================================
# CONFIGURATION
# ============================================
DATA_DIR = 'data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
BOT_DIR = 'bot'

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BOT_DIR, exist_ok=True)

# ============================================
# SECURE CONFIG
# ============================================

MASTER_USERNAME = 'master'
MASTER_PASSWORD_HASH = hashlib.sha256('JubayerMasterKey2026'.encode()).hexdigest()

CPU_HISTORY = {}
CRASH_COUNT = {}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        default = {
            'username': 'admin',
            'password_hash': hashlib.sha256('admin123'.encode()).hexdigest(),
            'server': {
                'status': 'stopped',
                'pid': None,
                'started_at': None,
                'main_file': 'main.py',
                'requirements_file': 'requirements.txt',
                'cpu_limit': 80,
                'rate_limit_exceeded': False,
                'stopped_by_user': False
            }
        }
        save_config(default)
        return default
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.chmod(CONFIG_FILE, 0o600)

def verify_user_login(username, password):
    config = load_config()
    return username == config.get('username') and hashlib.sha256(password.encode()).hexdigest() == config.get('password_hash')

def verify_master_login(username, password):
    return username == MASTER_USERNAME and hashlib.sha256(password.encode()).hexdigest() == MASTER_PASSWORD_HASH

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# RATE LIMITER & AUTO RESTART
# ============================================

class RateLimiter:
    def check_rate(self, server_id, limit_percent):
        if server_id not in CPU_HISTORY:
            CPU_HISTORY[server_id] = []
        
        config = load_config()
        server = config.get('server', {})
        
        if server.get('status') != 'running':
            return False, 0
        
        pid = server.get('pid')
        if not pid:
            return False, 0
        
        try:
            proc = psutil.Process(pid)
            cpu = proc.cpu_percent(interval=1)
            now = time.time()
            CPU_HISTORY[server_id].append({'time': now, 'cpu': cpu})
            CPU_HISTORY[server_id] = [h for h in CPU_HISTORY[server_id] if now - h['time'] < 30]
            recent = [h['cpu'] for h in CPU_HISTORY[server_id] if now - h['time'] < 10]
            if recent:
                avg_cpu = sum(recent) / len(recent)
                if avg_cpu > limit_percent:
                    return True, avg_cpu
        except:
            pass
        return False, 0

rate_limiter = RateLimiter()

def should_auto_restart(server_id):
    if server_id not in CRASH_COUNT:
        CRASH_COUNT[server_id] = {'count': 0, 'last_crash': time.time()}
    crash_info = CRASH_COUNT[server_id]
    if time.time() - crash_info['last_crash'] < 60:
        if crash_info['count'] >= 3:
            return False
    else:
        crash_info['count'] = 0
    crash_info['count'] += 1
    crash_info['last_crash'] = time.time()
    return True

# ============================================
# BOT MANAGEMENT
# ============================================

def create_default_files():
    """Create default bot files if not exist"""
    main_py = os.path.join(BOT_DIR, 'main.py')
    if not os.path.exists(main_py):
        with open(main_py, 'w', encoding='utf-8') as f:
            f.write('''# JUBAYER HOSTING - Default Bot
import time

print("=" * 40)
print("Bot is running on JUBAYER HOSTING")
print("Server is ready!")
print("=" * 40)

counter = 0
while True:
    counter += 1
    print(f"[{time.strftime('%H:%M:%S')}] Heartbeat #{counter} | Server active")
    time.sleep(10)
''')
    
    req_file = os.path.join(BOT_DIR, 'requirements.txt')
    if not os.path.exists(req_file):
        with open(req_file, 'w', encoding='utf-8') as f:
            f.write('# Add your pip packages here\n')

def run_bot():
    config = load_config()
    server = config.get('server', {})
    main_file = server.get('main_file', 'main.py')
    requirements_file = server.get('requirements_file', 'requirements.txt')
    
    main_path = os.path.join(BOT_DIR, main_file)
    log_file = os.path.join(BOT_DIR, 'output.log')
    python_exe = sys.executable
    
    # SECURITY: Check if file is trying to access parent directories
    def is_safe_path(path):
        real_path = os.path.realpath(path)
        bot_real = os.path.realpath(BOT_DIR)
        return real_path.startswith(bot_real)
    
    if not is_safe_path(main_path):
        return None, "Security violation: Invalid file path"
    
    def log(msg):
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"{msg}\n")
                f.flush()
        except:
            pass
    
    if not os.path.exists(main_path):
        return None, f"ERROR: {main_file} not found!"
    
    if os.path.exists(log_file):
        try:
            os.remove(log_file)
        except:
            open(log_file, 'w').close()
    
    ts = lambda: datetime.now().strftime('%I:%M:%S %p')
    cpu_limit = server.get('cpu_limit', 80)
    
    log(f"[{ts()}] Checking rate limit...")
    log(f"[{ts()}] Rate limit: {cpu_limit}%")
    log("")
    
    # Install requirements (auto-install on start)
    if requirements_file and requirements_file.strip():
        req_path = os.path.join(BOT_DIR, requirements_file.strip())
        log(f"[{ts()}] Run: pip install -r {requirements_file}")
        log("")
        
        if os.path.exists(req_path):
            with open(req_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]
            
            if lines:
                try:
                    proc = subprocess.Popen(
                        [python_exe, '-m', 'pip', 'install', '-r', os.path.abspath(req_path), '--disable-pip-version-check'],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1, universal_newlines=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                    )
                    
                    for line in iter(proc.stdout.readline, ''):
                        if line.strip():
                            log(f"[{ts()}] {line.rstrip()}")
                    
                    proc.wait()
                    log("")
                    
                    if proc.returncode != 0:
                        log(f"[{ts()}] Some packages failed to install")
                    else:
                        log(f"[{ts()}] Requirements installation complete!")
                except Exception as e:
                    log(f"[{ts()}] pip error: {str(e)}")
            else:
                log(f"[{ts()}] {requirements_file} is empty, skipping...")
        else:
            log(f"[{ts()}] {requirements_file} not found, skipping...")
    else:
        log(f"[{ts()}] No requirements file set, skipping...")
    
    log("")
    log(f"[{ts()}] Run: python {main_file}")
    log(f"[{ts()}] Python {sys.version.split()[0]}")
    log("")
    
    try:
        main_path_abs = os.path.abspath(main_path)
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUNBUFFERED'] = '1'
        # SECURITY: Remove dangerous environment variables
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        
        proc = subprocess.Popen(
            [python_exe, main_path_abs],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=BOT_DIR,
            text=True, encoding='utf-8', errors='replace',
            bufsize=1, env=env, universal_newlines=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        log(f"[{ts()}] Server started (PID: {proc.pid})")
        
        def rate_monitor():
            server_id = 'bot'
            while proc.poll() is None:
                time.sleep(5)
                exceeded, avg_cpu = rate_limiter.check_rate(server_id, cpu_limit)
                if exceeded:
                    log(f"[{datetime.now().strftime('%I:%M:%S %p')}] CPU Limit! {avg_cpu:.1f}% > {cpu_limit}%")
                    proc.terminate()
                    time.sleep(2)
                    if proc.poll() is None:
                        proc.kill()
                    
                    config = load_config()
                    config['server']['status'] = 'stopped'
                    config['server']['pid'] = None
                    config['server']['rate_limit_exceeded'] = True
                    config['server']['stopped_by_user'] = False
                    save_config(config)
                    break
        
        threading.Thread(target=rate_monitor, daemon=True).start()
        
        def stream_output():
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    for line in iter(proc.stdout.readline, ''):
                        if line:
                            line = line.rstrip('\n\r')
                            if line:
                                f.write(f"[{datetime.now().strftime('%I:%M:%S %p')}] {line}\n")
                                f.flush()
            except:
                pass
        
        threading.Thread(target=stream_output, daemon=True).start()
        
        return proc.pid, None
        
    except Exception as e:
        log(f"[{ts()}] Error: {str(e)}")
        return None, str(e)

def stop_bot_process(pid):
    try:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
        else:
            os.kill(pid, 15)
        return True
    except:
        return False

def monitor_bot(server_id, pid):
    while True:
        try:
            if sys.platform == 'win32':
                result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True)
                if str(pid) not in result.stdout:
                    break
            else:
                try:
                    os.kill(pid, 0)
                except:
                    break
        except:
            break
        time.sleep(5)
    
    config = load_config()
    server = config.get('server', {})
    
    if server.get('stopped_by_user'):
        return
    if server.get('rate_limit_exceeded'):
        return
    
    if should_auto_restart(server_id):
        time.sleep(3)
        new_pid, error = run_bot()
        if new_pid:
            config = load_config()
            config['server']['status'] = 'running'
            config['server']['pid'] = new_pid
            config['server']['started_at'] = str(datetime.now())
            config['server']['rate_limit_exceeded'] = False
            config['server']['stopped_by_user'] = False
            save_config(config)
            threading.Thread(target=monitor_bot, args=(server_id, new_pid), daemon=True).start()
    else:
        config = load_config()
        config['server']['status'] = 'stopped'
        config['server']['pid'] = None
        save_config(config)

def get_process_stats(pid):
    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=0.5)
        mem = proc.memory_info()
        ram = mem.rss / (1024 * 1024)
        return {
            'cpu_percent': round(cpu, 1),
            'ram_mb': round(ram, 1),
            'ram_display': f"{ram:.1f} MB" if ram < 1024 else f"{ram/1024:.1f} GB",
        }
    except:
        return {'cpu_percent': 0, 'ram_mb': 0, 'ram_display': '0 MB'}

def get_network_stats(pid):
    try:
        proc = psutil.Process(pid)
        io = proc.io_counters()
        if io:
            read_kb = io.read_bytes / 1024
            write_kb = io.write_bytes / 1024
            return format_bytes(read_kb), format_bytes(write_kb)
    except:
        pass
    return "0 KB", "0 KB"

def format_bytes(kb):
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.2f} GB"

# ============================================
# ROUTES
# ============================================

@app.route('/')
def index():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if verify_master_login(username, password):
            session['logged_in'] = True
            session['user_type'] = 'master'
            session['username'] = username
            return redirect(url_for('dashboard'))
        
        if verify_user_login(username, password):
            session['logged_in'] = True
            session['user_type'] = 'user'
            session['username'] = username
            return redirect(url_for('dashboard'))
        
        return render_template('login.html', error="Invalid credentials!")
    
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    config = load_config()
    server = config.get('server', {})
    return render_template('dashboard.html',
                         username=session.get('username'),
                         user_type=session.get('user_type'),
                         server=server)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_pass = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        new_username = request.form.get('new_username', '').strip()
        
        config = load_config()
        
        # Check current password
        if hashlib.sha256(current_pass.encode()).hexdigest() != config.get('password_hash'):
            return render_template('profile.html', error="Current password is incorrect!")
        
        # Update username if provided
        if new_username and new_username != config.get('username'):
            if len(new_username) < 3:
                return render_template('profile.html', error="Username must be at least 3 characters!")
            config['username'] = new_username
            session['username'] = new_username
        
        # Update password if provided
        if new_pass:
            if len(new_pass) < 4:
                return render_template('profile.html', error="Password must be at least 4 characters!")
            config['password_hash'] = hashlib.sha256(new_pass.encode()).hexdigest()
        
        save_config(config)
        return render_template('profile.html', success="Credentials updated successfully!")
    
    config = load_config()
    return render_template('profile.html', error=None, success=None, current_username=config.get('username'))

# ============================================
# API ROUTES
# ============================================

@app.route('/api/run', methods=['POST'])
@login_required
def api_run():
    config = load_config()
    server = config.get('server', {})
    
    if server.get('status') == 'running':
        return jsonify({'status': 'error', 'msg': 'Already running!'})
    
    server['rate_limit_exceeded'] = False
    server['stopped_by_user'] = False
    save_config(config)
    
    pid, error = run_bot()
    
    if pid:
        config = load_config()
        config['server']['status'] = 'running'
        config['server']['pid'] = pid
        config['server']['started_at'] = str(datetime.now())
        save_config(config)
        threading.Thread(target=monitor_bot, args=('bot', pid), daemon=True).start()
        return jsonify({'status': 'success', 'msg': 'Started!'})
    return jsonify({'status': 'error', 'msg': error or 'Failed'})

@app.route('/api/stop', methods=['POST'])
@login_required
def api_stop():
    config = load_config()
    server = config.get('server', {})
    
    if server.get('pid'):
        stop_bot_process(server['pid'])
    
    config['server']['status'] = 'stopped'
    config['server']['pid'] = None
    config['server']['stopped_by_user'] = True
    save_config(config)
    
    log_file = os.path.join(BOT_DIR, 'output.log')
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n[{datetime.now().strftime('%I:%M:%S %p')}] Server stopped by user\n")
    except:
        pass
    
    return jsonify({'status': 'success', 'msg': 'Stopped'})

@app.route('/api/logs')
@login_required
def api_logs():
    log_file = os.path.join(BOT_DIR, 'output.log')
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = f.read()
    else:
        logs = ""
    return jsonify({'logs': logs})

@app.route('/api/clear_logs', methods=['POST'])
@login_required
def api_clear_logs():
    log_file = os.path.join(BOT_DIR, 'output.log')
    try:
        if os.path.exists(log_file):
            os.remove(log_file)
        return jsonify({'status': 'success', 'msg': 'Cleared'})
    except:
        return jsonify({'status': 'error'}), 500

@app.route('/api/command', methods=['POST'])
@login_required
def api_command():
    data = request.get_json()
    cmd = data.get('cmd', '')
    
    # SECURITY: Block dangerous commands
    dangerous_cmds = ['rm -rf', 'sudo', 'chmod', 'chown', 'passwd', 'shutdown', 'reboot', 'kill']
    for dcmd in dangerous_cmds:
        if dcmd in cmd.lower():
            return jsonify({'status': 'error', 'msg': 'Command not allowed!'}), 403
    
    log_file = os.path.join(BOT_DIR, 'output.log')
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=BOT_DIR, timeout=30,
                              creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        output = (result.stdout + result.stderr)[:2000]
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%I:%M:%S %p')}] $ {cmd}\n{output}\n")
        return jsonify({'status': 'success', 'output': output})
    except:
        return jsonify({'status': 'error', 'msg': 'Timeout'})

@app.route('/api/stats')
@login_required
def api_stats():
    config = load_config()
    server = config.get('server', {})
    
    uptime, cpu, ram, net_in, net_out = "0h 0m", "0%", "0 MB", "0 KB", "0 KB"
    
    if server.get('status') == 'running' and server.get('pid'):
        stats = get_process_stats(server['pid'])
        cpu = f"{stats['cpu_percent']}%"
        ram = stats['ram_display']
        net_in, net_out = get_network_stats(server['pid'])
    
    if server.get('status') == 'running' and server.get('started_at'):
        try:
            start = datetime.strptime(server['started_at'], '%Y-%m-%d %H:%M:%S.%f')
            diff = datetime.now() - start
            if diff.days > 0:
                uptime = f"{diff.days}d {diff.seconds//3600}h"
            else:
                h, m, s = diff.seconds // 3600, (diff.seconds % 3600) // 60, diff.seconds % 60
                uptime = f"{h}h {m}m {s}s"
        except:
            pass
    
    return jsonify({
        'cpu': cpu,
        'ram': ram,
        'uptime': uptime,
        'net_in': net_in,
        'net_out': net_out,
        'cpu_limit': server.get('cpu_limit', 80),
        'status': server.get('status', 'stopped')
    })

@app.route('/api/get_startup')
@login_required
def api_get_startup():
    config = load_config()
    server = config.get('server', {})
    return jsonify({
        'main_file': server.get('main_file', 'main.py'),
        'requirements_file': server.get('requirements_file', 'requirements.txt')
    })

@app.route('/api/set_startup', methods=['POST'])
@login_required
def api_set_startup():
    data = request.get_json()
    config = load_config()
    config['server']['main_file'] = data.get('main_file', 'main.py')
    config['server']['requirements_file'] = data.get('requirements_file', 'requirements.txt')
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/files')
@login_required
def api_files():
    folder = request.args.get('folder', '')
    base_dir = os.path.abspath(BOT_DIR)
    
    if folder:
        target_dir = os.path.join(base_dir, folder)
        if not os.path.abspath(target_dir).startswith(base_dir):
            return jsonify({'files': []})
    else:
        target_dir = base_dir
    
    if not os.path.exists(target_dir):
        return jsonify({'files': []})
    
    files = []
    try:
        for item in os.listdir(target_dir):
            item_path = os.path.join(target_dir, item)
            # Skip hidden files
            if item.startswith('.'):
                continue
            files.append({
                'name': item,
                'is_dir': os.path.isdir(item_path),
                'size': os.path.getsize(item_path) if os.path.isfile(item_path) else 0,
                'modified': datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%Y-%m-%d %H:%M')
            })
    except:
        pass
    return jsonify({'files': files})

@app.route('/api/file', methods=['GET'])
@login_required
def api_get_file():
    filename = request.args.get('filename', '')
    filepath = os.path.join(BOT_DIR, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'error': 'Access denied'}), 403
    
    if os.path.exists(filepath) and os.path.isfile(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return jsonify({'content': f.read()})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/file', methods=['POST'])
@login_required
def api_save_file():
    data = request.get_json()
    filename = data.get('filename', '')
    filepath = os.path.join(BOT_DIR, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'error': 'Access denied'}), 403
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(data.get('content', ''))
    return jsonify({'success': True})

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    if 'files' not in request.files:
        return jsonify({'error': 'No files'}), 400
    
    folder = request.form.get('folder', '')
    base_dir = os.path.abspath(BOT_DIR)
    
    if folder:
        target_dir = os.path.join(base_dir, folder)
        if not os.path.abspath(target_dir).startswith(base_dir):
            return jsonify({'error': 'Access denied'}), 403
    else:
        target_dir = base_dir
    
    os.makedirs(target_dir, exist_ok=True)
    
    files = request.files.getlist('files')
    uploaded = []
    
    for file in files:
        if file.filename:
            filepath = os.path.join(target_dir, file.filename)
            file.save(filepath)
            uploaded.append(file.filename)
    
    return jsonify({'success': True, 'uploaded': uploaded})

@app.route('/api/delete_file', methods=['POST'])
@login_required
def api_delete_file():
    data = request.get_json()
    filename = data.get('filename', '')
    filepath = os.path.join(BOT_DIR, filename)
    
    if not os.path.abspath(filepath).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'error': 'Access denied'}), 403
    
    if os.path.exists(filepath):
        if os.path.isdir(filepath):
            shutil.rmtree(filepath)
        else:
            os.remove(filepath)
    return jsonify({'success': True})

@app.route('/api/rename', methods=['POST'])
@login_required
def api_rename():
    data = request.get_json()
    old_path = os.path.join(BOT_DIR, data.get('old_name', ''))
    new_path = os.path.join(BOT_DIR, data.get('new_name', ''))
    
    if not os.path.abspath(old_path).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.abspath(new_path).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'error': 'Access denied'}), 403
    
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/create_folder', methods=['POST'])
@login_required
def api_create_folder():
    data = request.get_json()
    foldername = data.get('foldername', '')
    folderpath = os.path.join(BOT_DIR, foldername)
    
    if not os.path.abspath(folderpath).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'error': 'Access denied'}), 403
    
    os.makedirs(folderpath, exist_ok=True)
    return jsonify({'success': True})

@app.route('/api/set_cpu_limit', methods=['POST'])
@login_required
def api_set_cpu_limit():
    data = request.get_json()
    cpu_limit = int(data.get('cpu_limit', 80))
    
    if cpu_limit < 10 or cpu_limit > 100:
        return jsonify({'error': 'CPU limit must be between 10 and 100!'}), 400
    
    config = load_config()
    config['server']['cpu_limit'] = cpu_limit
    save_config(config)
    return jsonify({'success': True, 'cpu_limit': cpu_limit})

@app.route('/api/unzip', methods=['POST'])
@login_required
def api_unzip():
    data = request.get_json()
    zip_path = os.path.join(BOT_DIR, data.get('filename', ''))
    
    if not os.path.abspath(zip_path).startswith(os.path.abspath(BOT_DIR)):
        return jsonify({'status': 'error', 'msg': 'Access denied'}), 403
    
    if os.path.exists(zip_path) and zip_path.endswith('.zip'):
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(os.path.dirname(zip_path))
            return jsonify({'status': 'success', 'msg': 'Extracted!'})
        except Exception as e:
            return jsonify({'status': 'error', 'msg': str(e)})
    return jsonify({'status': 'error', 'msg': 'Invalid zip'}), 400

# ============================================
# START
# ============================================

if __name__ == '__main__':
    # Create default files only if they don't exist
    create_default_files()
    
    print("\n" + "=" * 50)
    print("🚀 JUBAYER HOSTING - SECURE PANEL")
    print("=" * 50)
    print("📍 URL: http://localhost:5000")
    print("")
    print("🔐 MASTER LOGIN (FIXED - Never Changes):")
    print("   Username: master")
    print("   Password: JubayerMasterKey2026")
    print("")
    print("👤 USER LOGIN (Can Change):")
    print("   Username: admin")
    print("   Password: admin123")
    print("=" * 50 + "\n")
    app.run(debug=False, host='0.0.0.0', port=5000)
