"""Fail-closed cloud bootstrap. Credentials come exclusively from st.secrets."""
import os
import threading
from store import password_hash
from cafe import seed_cafe

_lock = threading.RLock()


def cloud_mode():
    # Local Windows launch keeps the existing first-run wizard. Linux defaults
    # to cloud, so a missing Secrets configuration cannot expose that wizard.
    return os.environ.get('PAYROLL_MODE', 'local' if os.name == 'nt' else 'cloud') == 'cloud'


def initialize(db, config):
    accounts = []
    for section, role in [('admin', 'admin'), ('accountant', 'accountant')]:
        account = config.get(section, {})
        if not account and role == 'accountant':
            continue
        login = str(account.get('login', '')).strip()
        password = str(account.get('password', ''))
        if not login or len(password) < 12 or password.startswith('REPLACE_'):
            raise ValueError('Заполните admin.login и admin.password в Streamlit Secrets. Пароль — от 12 символов. Для accountant действуют те же требования.')
        accounts.append((login, password, role))
    if len({a[0] for a in accounts}) != len(accounts):
        raise ValueError('Логины администратора и бухгалтера должны различаться.')
    if len(accounts)>1 and accounts[0][1]==accounts[1][1]:
        raise ValueError('Используйте разные пароли для администратора и бухгалтера.')
    with _lock:
        if db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='AppState'"):
            if db.query("SELECT 1 FROM AppState WHERE key='cloud_initialized'"):
                finish_demo(db, config)
                return
        with db.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('CREATE TABLE IF NOT EXISTS AppState(key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            if c.execute("SELECT 1 FROM AppState WHERE key='cloud_initialized'").fetchone():
                return
            # Never adopt an existing working database as an online demo.
            if c.execute('SELECT 1 FROM Users LIMIT 1').fetchone():
                raise ValueError('Для облачной демонстрации нужна новая база без рабочих данных.')
            for login, password, role in accounts:
                c.execute('INSERT INTO Users(login,password,role) VALUES(?,?,?)', (login,password_hash(password),role))
            uid=c.execute("SELECT id FROM Users WHERE role='admin'").fetchone()[0]
            c.execute("INSERT INTO AppState VALUES('cloud_initialized','accounts')")
        finish_demo(db, config, uid)


def finish_demo(db, config, uid=None):
    # Retry an interrupted seed; never recreate employees deleted after setup.
    with _lock:
        state=db.query("SELECT value FROM AppState WHERE key='cloud_initialized'")[0]['value']
        if state == 'ready':
            return
        uid=uid or db.query("SELECT id FROM Users WHERE role='admin' ORDER BY id LIMIT 1")[0]['id']
        if config.get('demo', {}).get('enabled', True):
            seed_cafe(db, uid)
        with db.connection() as c:
            c.execute("UPDATE AppState SET value='ready' WHERE key='cloud_initialized'")
