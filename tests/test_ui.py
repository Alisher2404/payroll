from _credentials import TEST_PASSWORD
"""Проверка всех разделов настоящим Streamlit AppTest без браузера."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest
import store
from store import Store
from demo import seed
from engine import generate_timesheet, calculate


def test_first_run(tmp_path,monkeypatch):
    source=Path(store.__file__).parent
    (tmp_path/'schema.sql').write_text((source/'schema.sql').read_text(encoding='utf-8'),encoding='utf-8')
    monkeypatch.setattr(store,'ROOT',tmp_path)
    at=AppTest.from_file(str(source/'app.py')).run(timeout=30)
    assert not at.exception
    assert at.title[0].value=='Первый запуск'
    at.text_input[0].set_value('administrator')
    at.text_input[1].set_value(TEST_PASSWORD)
    at.text_input[2].set_value(TEST_PASSWORD)
    at.button[0].click().run(timeout=30)
    assert not at.exception
    assert at.title[0].value=='Вход в систему расчёта зарплаты'


def test_all_pages(tmp_path,monkeypatch):
    source=Path(store.__file__).parent
    (tmp_path/'schema.sql').write_text((source/'schema.sql').read_text(encoding='utf-8'),encoding='utf-8')
    monkeypatch.setattr(store,'ROOT',tmp_path)
    db=Store(); db.create_user('admin',TEST_PASSWORD,'admin'); user=db.login('admin',TEST_PASSWORD)
    seed(db,user['id'])
    rule=dict(income='10',worker='2',employer='20',deduction='100',threshold='0',upper_rate='0',overtime_factor='2',deduct_worker=True,source='Синтетические параметры теста',verified=True)
    db.save_rule('2026-01-01','2026-12-31',rule,user['id'])
    e=db.employees()[0]
    r=calculate(e,'2026-10',generate_timesheet('2026-10',e['hired']),rule,dict(norm_days='22',norm_hours='176'))
    db.save_payroll(r,user['id'])
    at=AppTest.from_file(str(source/'app.py'))
    at.session_state['user']=user
    at.run(timeout=30)
    from datetime import date
    at.sidebar.date_input[0].set_value(date(2026,10,1)).run(timeout=30)
    for page in at.sidebar.radio[0].options:
        at.sidebar.radio[0].set_value(page).run(timeout=30)
        assert not at.exception, (page,[e.message for e in at.exception])
        assert not at.error, (page,[e.value for e in at.error])
