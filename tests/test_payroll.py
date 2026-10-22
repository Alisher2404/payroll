from _credentials import TEST_PASSWORD
import sys
import json
from pathlib import Path
from decimal import Decimal
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from engine import calculate, generate_timesheet, money, dec
from demo import seed
from reports import table, excel, pdf, records, aggregate


@pytest.fixture
def setup(tmp_path):
    db=Store(tmp_path/'test.sqlite3')
    db.create_user('admin',TEST_PASSWORD,'admin')
    user=db.login('admin',TEST_PASSWORD)['id']
    seed(db,user)
    employee=db.employees()[0]
    rows=generate_timesheet('2026-10',employee['hired'])
    # Только математическая фикстура: эти ставки не являются законодательством РТ.
    rule=dict(income='10',worker='2',employer='20',deduction='100',threshold='0',upper_rate='0',overtime_factor='2',deduct_worker=True,source='Синтетические параметры для автоматического теста',verified=True)
    adj=dict(norm_days='22',norm_hours='176')
    db.save_rule('2026-01-01','2026-12-31',rule,user)
    return db,user,employee,rows,rule,adj


def test_full_month(setup):
    db,u,e,rows,rule,a=setup
    r=calculate(e,'2026-10',rows,rule,a)
    assert r['gross']=='3000.00'
    assert r['deductions']['Взнос работника']=='60.00'
    assert r['deductions']['Подоходный налог']=='284.00'
    assert r['net']=='2656.00'
    assert r['employer']=='600.00'


def test_partial_month(setup):
    _,_,e,rows,rule,a=setup
    work=[r for r in rows if r['code']=='Я']
    for r in work[11:]: r.update(code='О',hours='0')
    r=calculate(e,'2026-10',rows,rule,a)
    assert r['earnings']['Основная зарплата']=='1500.00'


def test_bonus_and_withholding(setup):
    _,_,e,rows,rule,a=setup
    a.update(bonus='500',allowance='200',advance='100',alimony='50')
    r=calculate(e,'2026-10',rows,rule,a)
    assert r['gross']=='3700.00'
    assert r['net']=='3123.40'


def test_hourly_overtime(setup):
    _,_,e,rows,rule,a=setup
    e.update(pay_type='hourly',rate='10.25'); rows[0]['overtime']='2'
    r=calculate(e,'2026-10',rows,rule,a)
    assert r['earnings']['Основная зарплата']=='1804.00'
    assert r['earnings']['Сверхурочные']=='41.00'


@pytest.mark.parametrize('value',['-1','NaN','Infinity','abc'])
def test_bad_money(value):
    with pytest.raises(ValueError): dec(value)


def test_rounding():
    assert money('1.005')==Decimal('1.01')
    assert money('0.004')==Decimal('0.00')
    assert money('999999999.995')==Decimal('1000000000.00')


def test_zero_norm(setup):
    _,_,e,rows,rule,a=setup; a['norm_days']='0'
    with pytest.raises(ValueError): calculate(e,'2026-10',rows,rule,a)


def test_excess_withholding(setup):
    _,_,e,rows,rule,a=setup; a['advance']='5000'
    with pytest.raises(ValueError): calculate(e,'2026-10',rows,rule,a)


def test_duplicate_and_revision(setup):
    db,u,e,rows,rule,a=setup
    r=calculate(e,'2026-10',rows,rule,a)
    db.save_payroll(r,u)
    with pytest.raises(ValueError): db.save_payroll(r,u)
    a['bonus']='100'; r=calculate(e,'2026-10',rows,rule,a)
    db.save_payroll(r,u,True)
    assert len(records(db))==1
    assert len(records(db,history=True))==2
    assert records(db)[0]['revision']==2
    assert records(db,history=True)[0]['gross']=='3000.00'
    assert db.query('PRAGMA integrity_check')[0]['integrity_check']=='ok'


def test_unverified(setup):
    _,_,e,rows,rule,a=setup; rule['verified']=False
    with pytest.raises(ValueError): calculate(e,'2026-10',rows,rule,a,final=True)


def test_stale_preview(setup):
    db,u,e,rows,rule,a=setup
    r=calculate(e,'2026-10',rows,rule,a)
    e['rate']='3500'; db.save_employee(e,u,e['id'])
    with pytest.raises(ValueError): db.save_payroll(r,u)
    assert not records(db)


def test_timesheet_validation(setup):
    db,u,e,rows,rule,a=setup
    rows[0]['hours']='25'
    with pytest.raises(ValueError): db.save_timesheet(e,'2026-10',rows,u)
    with pytest.raises(ValueError): db.save_timesheet(e,'2026-10',rows[1:],u)


def test_rule_overlap_and_permissions(setup):
    db,u,e,rows,rule,a=setup
    with pytest.raises(ValueError): db.save_rule('2026-06-01','2027-01-01',rule,u)
    db.create_user('accountant',TEST_PASSWORD,'accountant',u)
    acc=db.login('accountant',TEST_PASSWORD)['id']
    with pytest.raises(ValueError): db.save_rule('2027-01-01','2027-12-31',rule,acc)
    with pytest.raises(ValueError): db.backup(acc)
    assert db.login('admin','wrong') is None


def test_exports_and_backup(setup,tmp_path):
    from openpyxl import load_workbook
    from io import BytesIO
    db,u,e,rows,rule,a=setup
    db.save_payroll(calculate(e,'2026-10',rows,rule,a),u)
    frame=table(records(db))
    workbook=load_workbook(BytesIO(excel(frame)))
    assert workbook.active['E2'].value=='3000.00'
    assert pdf(frame,'Проверка кириллицы').startswith(b'%PDF')
    backup=tmp_path/'restored.sqlite3'; backup.write_bytes(db.backup(u))
    restored=Store(backup)
    assert len(restored.employees())==10
    assert len(records(restored))==1


def test_progressive_tax(setup):
    _,_,e,rows,rule,a=setup
    rule.update(threshold='1000',upper_rate='20')
    r=calculate(e,'2026-10',rows,rule,a)
    assert r['deductions']['Подоходный налог']=='468.00'


def test_no_work(setup):
    _,_,e,rows,rule,a=setup
    for r in rows: r.update(code='Н',hours='0')
    result=calculate(e,'2026-10',rows,rule,a)
    assert result['gross']=='0.00' and result['net']=='0.00'


def test_missing_rules_and_invalid_user(setup):
    db,u,e,rows,rule,a=setup
    with pytest.raises(ValueError): db.rule('2027-01')
    with pytest.raises(ValueError): db.save_employee(e,999)


def test_employment_bounds(setup):
    db,u,e,rows,rule,a=setup
    e['hired']='2026-10-15'
    with pytest.raises(ValueError): db.save_timesheet(e,'2026-10',rows,u)


def test_rule_edit_keeps_snapshots(setup):
    db,u,e,rows,rule,a=setup
    r=calculate(e,'2026-10',rows,rule,a)
    db.save_payroll(r,u)
    rule['income']='15'
    db.save_rule('2026-01-01','2026-12-31',rule,u,1)
    assert records(db)[0]['rule']['income']=='10'
    assert db.rule('2026-10')['income']=='15'


def test_overtime_on_absence(setup):
    db,u,e,rows,rule,a=setup
    rows[0].update(code='Б',hours='0',overtime='2')
    with pytest.raises(ValueError): db.save_timesheet(e,'2026-10',rows,u)
