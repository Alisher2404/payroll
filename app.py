from app_time import today as dushanbe_today, now as dushanbe_now
import json
import sqlite3
import time
from datetime import date
from decimal import Decimal
import pandas as pd
import streamlit as st
from store import Store
from engine import calculate, generate_timesheet, month_days
from reports import records, table, aggregate, excel, pdf, payslip

from ui_staff import staff_page, catalog_page
from ui_time import timesheet_page
from ui_pay import payroll_page, payments_page
from ui_archive import archive_page
from cloud_setup import cloud_mode, initialize

st.set_page_config(page_title='Зарплата кофейни',page_icon=':material/coffee:',layout='wide')
db=Store()


def export(frame,label):
    if frame.empty:
        st.info('Нет сохранённых данных'); return
    st.dataframe(frame,hide_index=True,width='stretch')
    a,b=st.columns(2)
    a.download_button('Скачать Excel',excel(frame),label+'.xlsx',key=label+'xlsx')
    b.download_button('Скачать PDF / печать',pdf(frame,label),label+'.pdf',mime='application/pdf',key=label+'pdf')


def employee_picker(employees,key):
    if not employees:
        st.info('Сначала добавьте сотрудника'); st.stop()
    mapping={e['id']:e for e in employees}
    selected=st.selectbox('Сотрудник',list(mapping),format_func=lambda x:f"{mapping[x]['number']} · {mapping[x]['name']}",key=key)
    return mapping[selected]


def main():
    if cloud_mode():
        st.warning('Облачная демонстрация: база общая для всех посетителей. Диск временный; данные могут исчезнуть после перезапуска. Используйте только вымышленные сведения.')
        try:
            initialize(db, st.secrets)
        except (ValueError, FileNotFoundError):
            st.error('Облачный вход не настроен. Владелец должен заполнить Secrets по файлу .streamlit/secrets.example.toml. Создание администратора через публичную страницу отключено.')
            st.stop()
    if not db.query('SELECT id FROM Users LIMIT 1'):
        st.title('Первый запуск')
        st.write('Создайте администратора. Данные будут храниться в локальной базе SQLite.')
        with st.form('setup'):
            login=st.text_input('Логин'); password=st.text_input('Пароль (от 10 символов)',type='password')
            repeat=st.text_input('Повтор пароля',type='password')
            if st.form_submit_button('Создать администратора'):
                if password!=repeat: raise ValueError('Пароли не совпадают')
                db.create_user(login,password,'admin'); st.rerun()
        return
    if 'user' not in st.session_state:
        st.title('Вход в систему расчёта зарплаты')
        with st.form('login'):
            login=st.text_input('Логин'); password=st.text_input('Пароль',type='password')
            if st.form_submit_button('Войти'):
                if time.time()<st.session_state.get('retry_after',0):
                    st.error('Повторите попытку через несколько секунд'); return
                user=db.login(login,password)
                if user:
                    st.session_state.user=user; st.rerun()
                else:
                    st.session_state.retry_after=time.time()+3; st.error('Неверный логин или пароль')
        return
    user=st.session_state.user; uid=user['id']; admin=user['role']=='admin'
    if time.time()-st.session_state.get('activity',time.time())>1800:
        st.session_state.clear(); st.rerun()
    st.session_state.activity=time.time()
    st.sidebar.title('Зарплата кофейни')
    st.sidebar.caption('Локальный учёт · TJS')
    if 'next_page' in st.session_state: st.session_state.menu=st.session_state.pop('next_page')
    menu=st.sidebar.radio('Раздел',['Главная панель','Сотрудники','Архив сотрудников','Подразделения','Табель рабочего времени','Начисление заработной платы','Налоги и удержания','Расчётные листки','Выплаты','Отчёты','Настройки'],key='menu')
    selected=st.sidebar.date_input('Расчётный месяц',dushanbe_today().replace(day=1),format='DD.MM.YYYY',key='period_date')
    period=selected.strftime('%Y-%m')
    st.sidebar.caption(f"{user['login']} · {'Администратор' if admin else 'Бухгалтер'}")
    if st.sidebar.button('Выйти'):
        st.session_state.clear(); st.rerun()
    st.title(menu); st.caption('Команда · смены · начисления · выплаты')
    if 'notice' in st.session_state: st.success(st.session_state.pop('notice'))
    employees=db.employees(); saved=records(db,period)
    if menu=='Главная панель':
        cols=st.columns(5)
        cols[0].metric('Сотрудники',sum(e['hired']<=month_days(period)[-1].isoformat() and (not e['dismissed'] or e['dismissed']>=period+'-01') for e in employees))
        for c,label,key in zip(cols[1:],['Фонд оплаты труда','Удержания','К выплате','Взносы работодателя'],['gross','withheld','net','employer']):
            c.metric(label,f"{sum((Decimal(r[key]) for r in saved),Decimal(0)):,.2f}")
        st.subheader('Начисления по подразделениям')
        frame=aggregate(saved,'Подразделение')
        st.dataframe(frame,hide_index=True,width='stretch')
        st.info('Порядок работы: сотрудники → налоговые правила → табель → расчёт → сохранение → отчёты.')
        if not db.query('SELECT id FROM TaxSettings LIMIT 1'):
            st.warning('Налоговые правила ещё не заполнены. Доступны карточки, табели и предварительные начисления до налогов.')
        paid=db.query('SELECT p.amount FROM Payments p JOIN Payroll r ON r.id=p.payroll_id WHERE r.current=1 AND r.period=? AND p.void=0',(period,))
        outstanding=sum((Decimal(r['net']) for r in saved),Decimal(0))-sum((Decimal(p['amount']) for p in paid),Decimal(0))
        st.metric('Осталось фактически выплатить, сомони',str(outstanding))
        st.caption('Сохранённый расчёт и выдача денег учитываются отдельно. Фактические выплаты отмечайте в разделе «Выплаты».')
    elif menu=='Подразделения':
        catalog_page(db,user)
    elif menu=='Сотрудники':
        staff_page(db,user)
    elif menu=='Архив сотрудников':
        archive_page(db,user)
    elif menu=='Табель рабочего времени':
        timesheet_page(db,employees,period,user)
    elif menu=='Налоги и удержания':
        st.warning('Правила не предустановлены. Для реального расчёта проверьте ставки, вычеты, пороги, налоговую базу и сверхурочные по официальным источникам.')
        st.link_button('Налоговый кодекс · Налоговый комитет РТ','https://www.andoz.tj/Legislation/TaxCode')
        st.dataframe(pd.DataFrame(db.query('SELECT * FROM TaxSettings')),hide_index=True)
        if not admin:
            st.info('Изменять правила может администратор'); return
        existing=st.selectbox('Запись справочника',[None]+db.query('SELECT * FROM TaxSettings'),format_func=lambda x:'Новые правила' if x is None else f"{x['starts']} — {x['ends']}")
        current=json.loads(existing['data']) if existing else {}
        with st.form('rule'):
            starts=st.date_input('Начало действия',date.fromisoformat(existing['starts']) if existing else date(selected.year,1,1))
            ends=st.date_input('Окончание действия',date.fromisoformat(existing['ends']) if existing else date(selected.year,12,31))
            rule={}
            for k,label in [('income','Подоходный налог, %'),('worker','Взнос работника, %'),('employer','Взнос работодателя, %'),('deduction','Вычет из базы подоходного налога, TJS'),('threshold','Порог первой ступени, TJS (0 — одна ставка)'),('upper_rate','Ставка сверх порога, %'),('overtime_factor','Множитель оплаты сверхурочных')]:
                rule[k]=st.text_input(label,value=current.get(k,''),key='rule_'+k+'_'+str(existing['id'] if existing else 'new'))
            rule['deduct_worker']=st.checkbox('Вычитать взнос работника из базы подоходного налога',value=current.get('deduct_worker',False))
            rule['source']=st.text_area('Источник, статья, категория работников, дата проверки',value=current.get('source',''))
            rule['verified']=st.checkbox('Параметры и применимость проверены',value=current.get('verified',False))
            if st.form_submit_button('Сохранить правила'):
                db.save_rule(starts.isoformat(),ends.isoformat(),rule,uid,existing['id'] if existing else None); st.rerun()
        st.caption('Авансы, алименты и прочие удержания вводятся в форме расчёта. Взносы работодателя учитываются отдельно.')
    elif menu=='Начисление заработной платы':
        payroll_page(db,employees,period,user)
    elif menu=='Выплаты':
        payments_page(db,period,user)
    elif menu=='Расчётные листки':
        if not saved: st.info('Нет сохранённых расчётов'); return
        result=st.selectbox('Расчёт',saved,format_func=lambda r:r['employee']['name'])
        export(payslip(result),'Расчётный листок '+period)
        st.caption('Для печати откройте скачанный PDF и нажмите Ctrl+P.')
    elif menu=='Отчёты':
        kind=st.selectbox('Отчёт',['Ведомость начислений','Ведомость удержаний','Свод по подразделениям','Фонд оплаты труда','История сотрудника','Сравнение месяцев'])
        frame=table(saved)
        if kind=='Ведомость удержаний':
            frame=pd.DataFrame([{'ФИО':r['employee']['name'],**r['deductions'],'Итого':r['withheld']} for r in saved])
        elif kind=='Свод по подразделениям': frame=aggregate(saved,'Подразделение')
        elif kind=='Фонд оплаты труда': frame=aggregate(saved,'Период')
        elif kind=='История сотрудника':
            e=employee_picker(employees,'history_employee')
            frame=table([r for r in records(db,history=True) if r['employee']['id']==e['id']])
        elif kind=='Сравнение месяцев': frame=aggregate(records(db),'Период')
        export(frame,kind+' '+period)
    elif menu=='Настройки':
        if not admin: st.info('Раздел доступен администратору'); return
        with st.expander('Новый пользователь'):
            with st.form('new_user'):
                login=st.text_input('Логин пользователя'); password=st.text_input('Пароль',type='password')
                role=st.selectbox('Роль',['accountant','admin'])
                if st.form_submit_button('Создать пользователя'):
                    db.create_user(login,password,role,uid); st.success('Пользователь создан')
        with st.expander('Демонстрационные данные'):
            st.caption('10 вымышленных сотрудников кофейни: управляющий, бариста, кассиры, кондитер, уборщик и бухгалтер. Графики, табели и примеры доплат; налоговые ставки не добавляются. Повторная загрузка не меняет ваши карточки.')
            if st.button('Добавить примеры кофейни'):
                from cafe import seed_cafe
                added=seed_cafe(db,uid,period); st.success(f'Добавлено сотрудников: {added}. Ваши прежние записи сохранены.')
        if st.button('Подготовить резервную копию'):
            st.session_state.backup=db.backup(uid)
        if st.session_state.get('backup'):
            st.download_button('Скачать резервную копию SQLite',st.session_state.backup,'payroll-backup.sqlite3')
        st.caption('Восстановление: завершите приложение, сохраните текущую БД, замените data/payroll.sqlite3 копией и запустите программу. Копия содержит персональные данные и хеши паролей.')
        st.subheader('Хранение данных')
        st.code(str(db.path),language=None)
        st.caption('SQLite хранит сотрудников, табели, доплаты, расчёты, выплаты и журнал. Обновление файлов программы не удаляет базу. Резервные копии и data содержат персональные данные.')
        st.caption('Запуск без консоли: «Запустить.vbs». Завершение фонового сервера: «Остановить.vbs». Закрытие вкладки браузера не останавливает сервер.')
        st.subheader('Журнал изменений')
        st.dataframe(pd.DataFrame(db.query('SELECT * FROM AuditLog ORDER BY id DESC LIMIT 300')),hide_index=True)


try:
    main()
except (ValueError,sqlite3.IntegrityError) as exc:
    st.error('Такая запись уже существует. Проверьте номер сотрудника или название.' if isinstance(exc,sqlite3.IntegrityError) and 'UNIQUE' in str(exc) else 'Запись используется другими данными. Сначала измените связанные записи.' if isinstance(exc,sqlite3.IntegrityError) else str(exc))
