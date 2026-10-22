from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import secrets
import tomllib
import pytest
import app_time
from cloud_setup import initialize, cloud_mode
from store import Store


def config():
    return {'admin': {'login': 'owner', 'password': secrets.token_urlsafe(24)},
            'accountant': {'login': 'teacher', 'password': secrets.token_urlsafe(24)}}


def test_new_cloud_db_accounts_demo_and_no_reseed(tmp_path):
    db=Store(tmp_path/'new'/'cloud.sqlite3'); cfg=config()
    initialize(db,cfg)
    assert len(db.employees()) == 10
    assert db.login('owner',cfg['admin']['password'])['role']=='admin'
    assert db.login('teacher',cfg['accountant']['password'])['role']=='accountant'
    with db.connection() as c:
        c.execute('DELETE FROM PayrollDrafts'); c.execute('DELETE FROM Timesheets'); c.execute('DELETE FROM Employees')
    initialize(db,cfg)
    assert db.employees()==[]
    assert cfg['admin']['password'] not in db.path.read_bytes().decode('utf-8',errors='ignore')


def test_missing_secrets_fail_closed(tmp_path):
    db=Store(tmp_path/'cloud.sqlite3')
    with pytest.raises(ValueError): initialize(db,{})
    assert not db.query('SELECT * FROM Users')


def test_missing_database_is_recreated_with_demo(tmp_path):
    path=tmp_path/'cloud.sqlite3'; cfg=config()
    initialize(Store(path),cfg)
    path.unlink()
    recreated=Store(path); initialize(recreated,cfg)
    assert len(recreated.employees())==10
    assert recreated.login('owner',cfg['admin']['password'])


def test_reject_existing_working_database(tmp_path):
    db=Store(tmp_path/'working.sqlite3'); cfg=config()
    db.create_user('local',secrets.token_urlsafe(20),'admin')
    with pytest.raises(ValueError): initialize(db,cfg)
    assert len(db.query('SELECT * FROM Users'))==1


def test_do_not_share_admin_password_with_accountant(tmp_path):
    cfg=config(); cfg['accountant']['password']=cfg['admin']['password']
    with pytest.raises(ValueError): initialize(Store(tmp_path/'cloud.sqlite3'),cfg)


def test_simultaneous_first_visitors(tmp_path):
    db=Store(tmp_path/'cloud.sqlite3'); cfg=config()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: initialize(db,cfg),range(4)))
    assert len(db.employees())==10
    assert len(db.query('SELECT * FROM Users'))==2


def test_interrupted_seed_is_completed(tmp_path,monkeypatch):
    import cloud_setup
    db=Store(tmp_path/'cloud.sqlite3'); cfg=config()
    real=cloud_setup.seed_cafe
    def fail(*args): raise RuntimeError('interrupted')
    monkeypatch.setattr(cloud_setup,'seed_cafe',fail)
    with pytest.raises(RuntimeError): initialize(db,cfg)
    monkeypatch.setattr(cloud_setup,'seed_cafe',real)
    initialize(db,cfg)
    assert len(db.employees())==10


def test_dushanbe_date_after_utc_midnight_boundary(monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls,tz=None):
            return datetime(2026,10,22,20,30,tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(app_time,'datetime',Frozen)
    assert str(app_time.today())=='2026-10-23'
    assert app_time.now().isoformat().endswith('+05:00')


def test_audit_timezone(tmp_path):
    db=Store(tmp_path/'cloud.sqlite3'); cfg=config(); initialize(db,cfg)
    assert db.query('SELECT created FROM AuditLog')[0]['created'].endswith('+05:00')


def test_host_config_and_secrets_template():
    root=Path(__file__).resolve().parents[1]
    cfg=tomllib.loads((root/'.streamlit/config.toml').read_text(encoding='utf-8'))
    assert not {'address','port'} & cfg['server'].keys()
    assert 'serverAddress' not in cfg['browser']
    template=tomllib.loads((root/'.streamlit/secrets.example.toml').read_text(encoding='utf-8'))
    assert template['admin']['password'].startswith('REPLACE_')
    assert (root/'assets/DejaVuSans.ttf').is_file()
    assert b'\n' not in (root/'start.bat').read_bytes().replace(b'\r\n',b'')


def test_cloud_ui_without_secrets_has_no_setup_form(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    import store
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'schema.sql').write_bytes((root/'schema.sql').read_bytes())
    monkeypatch.setattr(store,'ROOT',tmp_path)
    monkeypatch.setenv('PAYROLL_MODE','cloud')
    at=AppTest.from_file(str(root/'app.py')).run(timeout=30)
    assert not at.exception
    assert at.error
    assert not at.text_input


def test_cloud_ui_bootstrap_and_login(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    import store
    root=Path(__file__).resolve().parents[1]
    (tmp_path/'schema.sql').write_bytes((root/'schema.sql').read_bytes())
    monkeypatch.setattr(store,'ROOT',tmp_path)
    monkeypatch.setenv('PAYROLL_MODE','cloud')
    cfg=config(); at=AppTest.from_file(str(root/'app.py'))
    at.secrets.update(cfg); at.run(timeout=30)
    assert not at.exception
    at.text_input[0].set_value('teacher'); at.text_input[1].set_value(cfg['accountant']['password'])
    at.button[0].click().run(timeout=30)
    assert not at.exception
    assert at.sidebar.radio
    assert len(Store().employees())==10
