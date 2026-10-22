from _credentials import TEST_PASSWORD
from pathlib import Path
from datetime import date
import json
import pytest
from streamlit.testing.v1 import AppTest
import store
from store import Store
from cafe import seed_cafe


@pytest.fixture
def app(tmp_path,monkeypatch):
    source=Path(store.__file__).parent
    (tmp_path/'schema.sql').write_text((source/'schema.sql').read_text(encoding='utf-8'),encoding='utf-8')
    monkeypatch.setattr(store,'ROOT',tmp_path)
    db=Store(); db.create_user('owner',TEST_PASSWORD,'admin'); user=db.login('owner',TEST_PASSWORD)
    seed_cafe(db,user['id'],'2026-10')
    at=AppTest.from_file(str(source/'app.py'),default_timeout=30)
    at.session_state['user']=user
    at.run(); at.sidebar.date_input[0].set_value(date(2026,10,1)).run()
    return at,db,user


def label(elements,text):
    return next(e for e in elements if e.label==text)


def page(at,name):
    at.sidebar.radio[0].set_value(name).run()
    assert not at.exception


def test_create_edit_duplicate_delete_card(app):
    at,db,u=app; page(at,'Сотрудники')
    label(at.text_input,'ФИО').set_value('Тестовый бариста')
    label(at.text_input,'Оклад / часовая ставка, сомони').set_value('30')
    label(at.form_submit_button,'Добавить сотрудника').click().run()
    assert not at.exception and not at.error
    employee=next(e for e in db.employees() if e['name']=='Тестовый бариста')
    assert at.selectbox(key='employee_choice').value==employee['id']
    label(at.text_input,'ФИО').set_value('Бариста после редактирования')
    label(at.form_submit_button,'Сохранить изменения').click().run()
    assert not at.error
    assert next(e for e in db.employees() if e['id']==employee['id'])['name']=='Бариста после редактирования'
    at.button(key='staff_new').click().run()
    label(at.text_input,'Табельный номер').set_value(employee['number'])
    label(at.text_input,'ФИО').set_value('Попытка дублирования')
    label(at.text_input,'Оклад / часовая ставка, сомони').set_value('30')
    label(at.form_submit_button,'Добавить сотрудника').click().run()
    assert not at.exception and 'уже занят' in at.error[0].value
    assert 'UNIQUE' not in at.error[0].value
    at.selectbox(key='employee_choice').set_value(employee['id']).run()
    next(c for c in at.checkbox if c.label.startswith('Подтверждаю удаление')).check().run()
    label(at.button,'Удалить карточку').click().run()
    assert not at.exception and not at.error
    assert len(db.employees())==10


def test_switch_cards_keeps_right_values(app):
    at,db,u=app; page(at,'Сотрудники')
    first,second=db.employees()[:2]
    at.selectbox(key='employee_choice').set_value(first['id']).run()
    assert label(at.text_input,'ФИО').value==first['name']
    at.selectbox(key='employee_choice').set_value(second['id']).run()
    assert label(at.text_input,'ФИО').value==second['name']
    assert label(at.text_input,'Оклад / часовая ставка, сомони').value==second['rate']
    assert not at.exception


def test_archive_and_restore_ui(app):
    at,db,u=app; page(at,'Сотрудники'); first=db.employees()[0]
    at.selectbox(key='employee_choice').set_value(first['id']).run()
    label(at.checkbox,'Увольнение / архив').check().run()
    label(at.text_area,'Причина увольнения / основание').set_value('По собственному желанию')
    label(at.date_input,'Дата увольнения').set_value(date(2026,10,31))
    label(at.form_submit_button,'Сохранить изменения').click().run()
    assert not at.error and not at.exception
    assert db.employees()[0]['dismissed']=='2026-10-31'
    label(at.checkbox,'Увольнение / архив').uncheck().run()
    label(at.form_submit_button,'Сохранить изменения').click().run()
    assert db.employees()[0]['dismissed'] is None


def test_gross_preview_without_fake_tax_and_persisted_bonus(app):
    at,db,u=app; page(at,'Начисление заработной платы')
    label(at.text_input,'Премия').set_value('400')
    label(at.form_submit_button,'Рассчитать заработную плату').click().run()
    assert not at.exception and not at.error
    assert any(m.label=='Всего начислено до налогов' and m.value=='6400.00' for m in at.metric)
    assert not any(b.label=='Сохранить проверенный расчёт' for b in at.button)
    assert not db.query('SELECT * FROM Payroll')
    assert not db.query('SELECT * FROM TaxSettings')
    page(at,'Главная панель'); page(at,'Начисление заработной платы')
    assert label(at.text_input,'Премия').value=='400'


def test_full_payroll_and_payment_ui(app):
    at,db,u=app
    rule=dict(income='10',worker='2',employer='20',deduction='100',threshold='0',upper_rate='0',overtime_factor='2',deduct_worker=True,source='Синтетические тестовые параметры',verified=True)
    db.save_rule('2026-01-01','2026-12-31',rule,u['id'])
    page(at,'Начисление заработной платы')
    label(at.form_submit_button,'Рассчитать заработную плату').click().run()
    assert not at.error and not at.exception
    label(at.button,'Сохранить проверенный расчёт').click().run()
    assert len(db.query('SELECT * FROM Payroll'))==1
    page(at,'Выплаты')
    label(at.text_input,'Сумма выплаты, сомони').set_value('1000')
    label(at.text_input,'Номер платёжного документа / уникальная отметка').set_value('TEST-CASH-001')
    label(at.checkbox,'Подтверждаю, что деньги действительно выплачены').check()
    label(at.form_submit_button,'Зарегистрировать выплату').click().run()
    assert not at.error and not at.exception
    assert db.query('SELECT amount FROM Payments')[0]['amount']=='1000.00'
    page(at,'Отчёты')
    for option in at.selectbox[0].options:
        at.selectbox[0].set_value(option).run()
        assert not at.error and not at.exception
