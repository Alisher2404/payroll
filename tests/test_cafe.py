from _credentials import TEST_PASSWORD
import json
from datetime import date
from decimal import Decimal
import pytest
from store import Store
from cafe import seed_cafe
from engine import scheduled_timesheet, earnings_for, calculate
from reports import records


@pytest.fixture
def cafe_db(tmp_path):
    db=Store(tmp_path/'cafe.sqlite3'); db.create_user('owner',TEST_PASSWORD,'admin')
    uid=db.login('owner',TEST_PASSWORD)['id']
    seed_cafe(db,uid,'2026-10')
    return db,uid


def result_for(db,e):
    rule=dict(income='10',worker='2',employer='20',deduction='100',threshold='0',upper_rate='0',overtime_factor='2',deduct_worker=True,source='Синтетическая математическая фикстура, не ставки РТ',verified=True)
    rows=json.loads(db.query('SELECT data FROM Timesheets WHERE employee_id=?',(e['id'],))[0]['data'])
    a=json.loads(db.query('SELECT data FROM PayrollDrafts WHERE employee_id=?',(e['id'],))[0]['data'])
    return rule,calculate(e,'2026-10',rows,rule,a)


def test_seed_idempotent_and_user_preserved(cafe_db):
    db,u=cafe_db
    assert len(db.employees())==10
    old=db.employees()[0]; old['name']='Изменённое имя'
    db.save_employee(old,u,old['id'])
    assert seed_cafe(db,u,'2026-10')==0
    assert db.employees()[0]['name']=='Изменённое имя'
    assert db.query('SELECT count(*) n FROM Users')[0]['n']==1
    assert not db.query('SELECT * FROM TaxSettings')


def test_duplicate_friendly_and_auto_number(cafe_db):
    db,u=cafe_db
    e=db.employees()[0]
    with pytest.raises(ValueError,match='уже занят'): db.save_employee(e,u)
    assert len(db.employees())==10
    assert db.next_number()=='EMP-0001'
    e=dict(e,number=db.next_number()); db.save_employee(e,u)
    assert db.next_number()=='EMP-0002'


def test_safe_delete_and_permissions(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    with pytest.raises(ValueError,match='история'): db.delete_employee(e['id'],u)
    new=db.save_employee(dict(e,number='NEW-1'),u)
    db.delete_employee(new,u)
    assert all(e['id']!=new for e in db.employees())
    db.create_user('acc',TEST_PASSWORD,'accountant',u); acc=db.login('acc',TEST_PASSWORD)['id']
    with pytest.raises(ValueError,match='прав'): db.delete_employee(e['id'],acc)


def test_archive_restore_preserves_time(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    e['dismissed']='2026-10-31'; e['dismissal_reason']='По собственному желанию'; db.save_employee(e,u,e['id'])
    e=db.employees()[0]; e['dismissed']=None; db.save_employee(e,u,e['id'])
    assert len(db.query('SELECT * FROM Timesheets'))==10
    assert db.employees()[0]['dismissed'] is None


def test_edit_concurrency(cafe_db):
    db,u=cafe_db; old=db.employees()[0]
    db.save_employee(dict(old,rate='6200'),u,old['id'])
    with pytest.raises(ValueError,match='другом окне'): db.save_employee(dict(old,name='Потерянное изменение'),u,old['id'])
    assert db.employees()[0]['name']==old['name']
    assert db.employees()[0]['rate']=='6200.00'


def test_timesheet_and_draft_concurrency(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    row=db.query('SELECT * FROM Timesheets WHERE employee_id=?',(e['id'],))[0]
    rows=json.loads(row['data'])
    db.save_timesheet(e,'2026-10',rows,u,row['version'])
    with pytest.raises(ValueError,match='другом окне'): db.save_timesheet(e,'2026-10',rows,u,row['version'])
    draft=db.query('SELECT * FROM PayrollDrafts WHERE employee_id=?',(e['id'],))[0]
    db.save_draft(e['id'],'2026-10',json.loads(draft['data']),u,draft['version'])
    with pytest.raises(ValueError,match='другом окне'): db.save_draft(e['id'],'2026-10',json.loads(draft['data']),u,draft['version'])


def test_shift_schedule_leap_year_and_anchor():
    rows=scheduled_timesheet('2028-02','2028-02-01',schedule={'pattern':'2/2','hours':'12','anchor':'2028-02-01'})
    assert len(rows)==29
    assert [r['code'] for r in rows[:8]]==['Я','Я','В','В','Я','Я','В','В']
    assert rows[-1]['date']=='2028-02-29'


def test_hourly_shift_pay_and_partial_salaried(cafe_db):
    db,u=cafe_db
    e=db.employees()[1]; _,r=result_for(db,e)
    assert r['hours']=='192'
    assert r['gross']=='5826.00'  # 192*28 + 300 премии + 150 чаевых
    e=db.employees()[0]; rule,r=result_for(db,e)
    rows=r['timesheet']; rows[0]['hours']='4'
    result=calculate(e,'2026-10',rows,rule,r['adjustments'])
    assert result['earnings']['Основная зарплата']=='5863.64'


def test_drafts_survive_reopen(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    db.save_draft(e['id'],'2026-10',{'bonus':'400','norm_days':'22','norm_hours':'176'},u)
    reopened=Store(db.path)
    assert json.loads(reopened.query('SELECT data FROM PayrollDrafts WHERE employee_id=?',(e['id'],))[0]['data'])['bonus']=='400'


def test_payments_partial_duplicate_overpay_and_recalc(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    rule,r=result_for(db,e); db.save_rule('2026-01-01','2026-12-31',rule,u)
    pid=db.save_payroll(r,u)
    payment=db.register_payment(pid,'1000','DOC-1','2026-10-22','Наличные',u)
    with pytest.raises(ValueError,match='зарегистрирована'): db.register_payment(pid,'1000','DOC-1','2026-10-22','Наличные',u)
    with pytest.raises(ValueError,match='остаток'): db.register_payment(pid,'99999','DOC-2','2026-10-22','Наличные',u)
    with pytest.raises(ValueError,match='есть выплаты'): db.save_payroll(r,u,True)
    db.register_payment(pid,str(Decimal(r['net'])-1000),'DOC-2','2026-10-22','Перевод',u)
    assert sum((Decimal(p['amount']) for p in db.query('SELECT * FROM Payments')),Decimal(0))==Decimal(r['net'])
    for p in db.query('SELECT * FROM Payments'): db.void_payment(p['id'],'Ошибочная выплата',u)
    db.save_payroll(r,u,True)
    assert len(records(db,history=True))==2
    assert len(db.query('SELECT * FROM Payments WHERE void=1'))==2


def test_catalog_edit_and_delete_protection(cafe_db):
    db,u=cafe_db
    row=db.query('SELECT * FROM Departments')[0]
    with pytest.raises(ValueError,match='используется'): db.update_catalog('Departments',row['id'],'',u,True)
    db.update_catalog('Departments',row['id'],'Новое подразделение',u)
    db.catalog('Departments','Пустое подразделение',u)
    free=db.query('SELECT id FROM Departments WHERE name=?',('Пустое подразделение',))[0]['id']
    db.update_catalog('Departments',free,'',u,True)
    assert not db.query('SELECT id FROM Departments WHERE id=?',(free,))


def test_changed_draft_blocks_old_preview(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    rule,r=result_for(db,e); db.save_rule('2026-01-01','2026-12-31',rule,u)
    adjustments=dict(r['adjustments'],bonus='500')
    db.save_draft(e['id'],'2026-10',adjustments,u)
    with pytest.raises(ValueError,match='Доплаты или удержания изменились'): db.save_payroll(r,u)
    assert not records(db)


def test_legacy_database_migrates_without_data_loss(tmp_path):
    import sqlite3
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE Employees(id INTEGER PRIMARY KEY,number TEXT,name TEXT,department_id INTEGER,position_id INTEGER,hired TEXT,dismissed TEXT,pay_type TEXT,rate TEXT,notes TEXT)')
        c.execute("INSERT INTO Employees VALUES(1,'001','Прежний сотрудник',1,1,'2026-01-01',NULL,'salary','3000','')")
    db=Store(path)
    row=db.query('SELECT * FROM Employees')[0]
    assert row['name']=='Прежний сотрудник' and row['version']==1 and row['schedule']=='{}'
    assert db.query('PRAGMA integrity_check')[0]['integrity_check']=='ok'
