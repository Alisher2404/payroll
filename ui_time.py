import json
from decimal import Decimal
import pandas as pd
import streamlit as st
from engine import scheduled_timesheet
from ui_staff import flash


def timesheet_page(db,employees,period,user):
    if not employees: st.info('Сначала добавьте сотрудников'); return
    mapping={e['id']:e for e in employees}
    eid=st.selectbox('Сотрудник',list(mapping),format_func=lambda x:mapping[x]['number']+' · '+mapping[x]['name'],key='timesheet_employee')
    employee=mapping[eid]
    schedule=json.loads(employee['schedule'])
    st.caption(f"График из карточки: {schedule.get('pattern','5/2')}, обычных часов в смене: {schedule.get('hours','8')}. Шаблон графика нужно проверить по фактической работе.")
    saved=db.query('SELECT * FROM Timesheets WHERE employee_id=? AND period=?',(eid,period))
    version=saved[0]['version'] if saved else 0
    base=f'ts_{eid}_{period}'
    holidays=st.text_input('Нерабочие праздничные даты через запятую (ГГГГ-ММ-ДД)',key=base+'_holidays',help='Для сменного графика внесите фактическую явку в праздник вручную и рассчитанную отдельно доплату в начислениях.')
    regenerate=st.checkbox('Заменить сохранённый табель новым шаблоном',key=base+'_confirm') if saved else True
    if st.button('Сформировать по графику',disabled=not regenerate,key=base+'_generate'):
        st.session_state[base+'_template']=scheduled_timesheet(period,employee['hired'],employee['dismissed'],schedule,[x.strip() for x in holidays.split(',') if x.strip()])
        st.session_state[base+'_generation']=st.session_state.get(base+'_generation',0)+1
        st.session_state[base+'_expected']=version
        st.rerun()
    data=st.session_state.get(base+'_template',json.loads(saved[0]['data']) if saved else scheduled_timesheet(period,employee['hired'],employee['dismissed'],schedule))
    st.caption('Я — явка · В — выходной · П — праздник · О — отпуск · Б — больничный · Н — отсутствие · ПР — прогул. Сверхурочные вводятся отдельно от обычных часов.')
    frame=st.data_editor(pd.DataFrame(data),disabled=['date'],hide_index=True,width='stretch',key=f"{base}_editor_{version}_{st.session_state.get(base+'_generation',0)}",column_config={'date':st.column_config.TextColumn('Дата'),'code':st.column_config.SelectboxColumn('Код',options=['Я','В','П','О','Б','Н','ПР'],required=True),'hours':st.column_config.TextColumn('Обычные часы'),'overtime':st.column_config.TextColumn('Сверхурочные')})
    # Подсчёт допускает незавершённый ввод; окончательная проверка — перед записью.
    try:
        ordinary=sum((Decimal(str(v).replace(',','.')) for v in frame['hours']),Decimal(0))
        overtime=sum((Decimal(str(v).replace(',','.')) for v in frame['overtime']),Decimal(0))
        a,b,c=st.columns(3); a.metric('Явок',sum(frame['code']=='Я')); b.metric('Обычных часов',str(ordinary)); c.metric('Сверхурочных часов',str(overtime))
    except Exception:
        st.caption('Проверьте введённые часы')
    if st.button('Сохранить табель',type='primary',key=base+'_save'):
        expected=st.session_state.get(base+'_expected',version)
        db.save_timesheet(employee,period,frame.to_dict('records'),user['id'],expected_version=expected)
        st.session_state.pop(base+'_template',None); st.session_state.pop(base+'_expected',None)
        flash('Табель сохранён в базе данных'); st.rerun()
    st.caption('Изменения в таблице сохраняются только после нажатия «Сохранить табель».')
