from _credentials import TEST_PASSWORD
import json
from pathlib import Path
import pytest
from test_cafe import cafe_db, result_for
from test_cafe_ui import app, label, page
from store import Store
from staff_stats import employee_statistics


def test_dismissal_reason_events_and_restore(cafe_db):
    db,u=cafe_db; e=db.employees()[0]
    e['dismissed']='2026-10-31'
    with pytest.raises(ValueError,match='причину увольнения'): db.save_employee(e,u,e['id'])
    e['dismissal_reason']='По собственному желанию'
    db.save_employee(e,u,e['id'])
    e=db.employees()[0]; e['dismissal_reason']='По соглашению сторон'
    db.save_employee(e,u,e['id'])
    e=db.employees()[0]; e['dismissed']=None
    db.save_employee(e,u,e['id'])
    events=db.query('SELECT * FROM EmploymentEvents ORDER BY id')
    assert [r['event'] for r in events]==['Увольнение','Изменение увольнения','Восстановление']
    assert events[0]['reason']=='По собственному желанию'
    assert events[1]['reason']=='По соглашению сторон'
    assert db.employees()[0]['dismissal_reason']==''
    assert len(db.query('SELECT * FROM Timesheets'))==10


def test_only_admin_can_dismiss_or_restore(cafe_db):
    db,u=cafe_db; db.create_user('book',TEST_PASSWORD,'accountant',u)
    accountant=db.login('book',TEST_PASSWORD)['id']; e=db.employees()[0]
    changed=dict(e,dismissed='2026-10-31',dismissal_reason='Окончание договора')
    with pytest.raises(ValueError,match='прав'): db.save_employee(changed,accountant,e['id'])
    db.save_employee(changed,u,e['id']); e=db.employees()[0]
    with pytest.raises(ValueError,match='прав'): db.save_employee(dict(e,dismissed=None),accountant,e['id'])
    db.save_employee(dict(e,name='Исправленное имя'),accountant,e['id'])
    assert db.employees()[0]['name']=='Исправленное имя'


def test_stats_revisions_void_payments_and_future_shifts(cafe_db):
    db,u=cafe_db; e=db.employees()[0]; rule,r=result_for(db,e)
    db.save_rule('2026-01-01','2026-12-31',rule,u)
    pid=db.save_payroll(r,u)
    first=db.register_payment(pid,'100','OLD','2026-10-01','Наличные',u)
    db.void_payment(first,'Ошибочная запись',u)
    pid=db.save_payroll(r,u,True)
    db.register_payment(pid,'200','NEW','2026-10-02','Перевод',u)
    stats=employee_statistics(db,e['id'],today='2026-10-02')
    assert len(stats['history'])==2 and len(stats['current'])==1
    assert stats['totals']['gross']=='6000.00'
    assert stats['totals']['paid']=='200.00'
    assert stats['totals']['remaining']=='5102.00'
    assert stats['time'][0]['Обычных часов']=='16'
    assert stats['time'][0]['Явок']==2
    assert len(stats['payments'])==2


def test_full_delete_includes_financial_records_and_recoverable_backup(cafe_db):
    db,u=cafe_db; e=db.employees()[0]; rule,r=result_for(db,e)
    db.save_rule('2026-01-01','2026-12-31',rule,u); pid=db.save_payroll(r,u)
    db.register_payment(pid,'200','PAY','2026-10-22','Наличные',u)
    for confirmation,reason,version in [('wrong','Учебные данные',e['version']),(e['number'],'',e['version']),(e['number'],'Учебные данные',999)]:
        with pytest.raises(ValueError): db.purge_employee(e['id'],u,confirmation,reason,version)
    backup=db.purge_employee(e['id'],u,e['number'],'Удаление учебного сотрудника',e['version'])
    assert Path(backup).exists()
    assert len(db.employees())==9
    for table in ('Timesheets','PayrollDrafts','Payroll','EmploymentEvents'):
        assert not db.query(f'SELECT * FROM {table} WHERE employee_id=?',(e['id'],))
    assert not db.query('SELECT * FROM Payments') and not db.query('SELECT * FROM PayrollItems')
    assert not db.query('PRAGMA foreign_key_check')
    restored=Store(backup)
    assert len(restored.employees())==10
    assert len(restored.query('SELECT * FROM Payments'))==1
    assert restored.query('PRAGMA integrity_check')[0]['integrity_check']=='ok'
    audit=db.query('SELECT details FROM AuditLog WHERE action=?',('Сотрудник удалён со всей историей',))[0]
    assert json.loads(audit['details'])['reason']=='Удаление учебного сотрудника'


def test_full_delete_permissions_and_backup_failure(cafe_db,monkeypatch):
    db,u=cafe_db; e=db.employees()[0]
    db.create_user('book',TEST_PASSWORD,'accountant',u); acc=db.login('book',TEST_PASSWORD)['id']
    with pytest.raises(ValueError,match='прав'): db.purge_employee(e['id'],acc,e['number'],'Удаление примера',e['version'])
    original=Path.mkdir
    def blocked(path,*args,**kwargs):
        if path.name=='deletion-backups': raise PermissionError('disk read only')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'mkdir',blocked)
    with pytest.raises(ValueError,match='Удаление отменено'): db.purge_employee(e['id'],u,e['number'],'Удаление примера',e['version'])
    assert len(db.employees())==10 and len(db.query('SELECT * FROM Timesheets'))==10


def test_archive_ui_reason_stats_and_restore(app):
    at,db,u=app
    e=dict(db.employees()[0],number='ARCH-001',hired='2026-01-01',dismissed='2026-10-01',dismissal_reason='По собственному желанию')
    eid=db.save_employee(e,u['id'])
    page(at,'Архив сотрудников')
    assert not at.exception and not at.error
    assert any('По собственному желанию' in i.value for i in at.info)
    assert any(m.label=='Начислено за всё время' for m in at.metric)
    label(at.button,'Открыть карточку для изменения или восстановления').click().run()
    assert at.selectbox(key='employee_choice').value==eid
    label(at.checkbox,'Увольнение / архив').uncheck().run()
    label(at.form_submit_button,'Сохранить изменения').click().run()
    assert not at.exception and not at.error
    page(at,'Архив сотрудников')
    assert any('нет сотрудников' in i.value for i in at.info)
    events=db.query('SELECT * FROM EmploymentEvents WHERE employee_id=?',(eid,))
    assert len(events)==2


def test_admin_purge_ui(app):
    at,db,u=app; page(at,'Сотрудники')
    e=db.employees()[0]
    at.selectbox(key='employee_choice').set_value(e['id']).run()
    label(at.text_input,'Введите точный табельный номер для удаления').set_value(e['number'])
    label(at.text_area,'Причина полного удаления').set_value('Очистка учебного примера')
    label(at.checkbox,'Понимаю, что удаляю сотрудника и всю его историю').check().run()
    label(at.button,'Удалить сотрудника и всю историю').click().run()
    assert not at.exception and not at.error
    assert len(db.employees())==9
    assert any('Резервная копия' in i.value for i in at.success)


def test_statistics_decimal_comma_and_employment_bounds(cafe_db):
    from engine import scheduled_timesheet
    db,u=cafe_db
    template=dict(db.employees()[0],number='MID-MONTH',hired='2026-10-15')
    eid=db.save_employee(template,u); e=next(e for e in db.employees() if e['id']==eid)
    rows=scheduled_timesheet('2026-10',e['hired'])
    rows[14]['hours']='7,5'
    db.save_timesheet(e,'2026-10',rows,u)
    stats=employee_statistics(db,eid,today='2026-10-15')
    assert stats['time'][0]['Обычных часов']=='7.5'
    assert stats['time'][0]['Отсутствий']==0


def test_accountant_ui_cannot_dismiss_or_delete(app):
    at,db,u=app
    db.create_user('accountant',TEST_PASSWORD,'accountant',u['id'])
    at.session_state['user']=db.login('accountant',TEST_PASSWORD)
    page(at,'Сотрудники')
    at.selectbox(key='employee_choice').set_value(db.employees()[0]['id']).run()
    assert label(at.checkbox,'Увольнение / архив').disabled
    assert not any(b.label in ('Удалить карточку','Удалить сотрудника и всю историю','Уволить и перенести в архив') for b in at.button)
