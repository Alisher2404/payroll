from app_time import today as dushanbe_today, now as dushanbe_now
"""Карточки сотрудников и справочники с безопасными действиями."""
import json
from datetime import date
import pandas as pd
import streamlit as st


def flash(message):
    st.session_state['notice']=message


def staff_page(db,user):
    employees=db.employees()
    st.caption('Карточки, ставки и графики сохраняются в SQLite. После сохранения новая карточка автоматически открывается для редактирования.')
    a,b,c=st.columns([2,1,1])
    search=a.text_input('Поиск по ФИО или номеру')
    department=b.selectbox('Подразделение',['Все']+sorted({e['department'] for e in employees}),key='staff_department')
    status=c.selectbox('Статус',['Все','Работает','Уволен'],key='staff_status')
    filtered=[e for e in employees if search.casefold() in (e['name']+' '+e['number']).casefold() and (department=='Все' or e['department']==department) and (status=='Все' or bool(e['dismissed'] and e['dismissed']<=dushanbe_today().isoformat())==(status=='Уволен'))]
    frame=pd.DataFrame([{'Таб. №':e['number'],'ФИО':e['name'],'Должность':e['position'],'Подразделение':e['department'],'Оплата':'Оклад' if e['pay_type']=='salary' else 'В час','Ставка, сомони':e['rate'],'График':json.loads(e['schedule']).get('pattern','5/2'),'Статус':'Уволен' if e['dismissed'] and e['dismissed']<=dushanbe_today().isoformat() else 'Работает'} for e in filtered])
    st.dataframe(frame,hide_index=True,width='stretch')
    mapping={e['id']:e for e in employees}; choices=[0]+list(mapping)
    if 'open_employee' in st.session_state:
        st.session_state.employee_choice=st.session_state.pop('open_employee')
    if st.session_state.get('employee_choice',0) not in choices: st.session_state.employee_choice=0
    eid=st.selectbox('Карточка сотрудника',choices,key='employee_choice',format_func=lambda x:'＋ Новый сотрудник' if x==0 else mapping[x]['number']+' · '+mapping[x]['name'])
    if st.button('Создать ещё одну карточку',key='staff_new'):
        st.session_state.open_employee=0; st.rerun()
    e=mapping.get(eid)
    ds=db.query('SELECT * FROM Departments ORDER BY name'); ps=db.query('SELECT * FROM Positions ORDER BY name')
    if not ds or not ps:
        st.info('Сначала добавьте подразделение и должность или загрузите команду кофейни в настройках.'); return
    prefix=f"employee_{eid}_{e['version'] if e else 0}"
    schedule=json.loads(e['schedule']) if e else {}
    st.subheader('Редактирование карточки' if e else 'Новая карточка')
    admin=user['role']=='admin'
    st.caption('Чтобы изменить данные, выберите карточку выше и сохраните изменения. Увольнение, восстановление и удаление доступны администратору.')
    archived=st.checkbox('Увольнение / архив',value=bool(e and e['dismissed']),key=prefix+'_archived',disabled=not admin)
    with st.form(prefix):
        l,r=st.columns(2)
        values={}
        values['number']=l.text_input('Табельный номер',e['number'] if e else db.next_number(),key=prefix+'_number',help='Номер уникален. Для изменения сотрудника выбирайте существующую карточку выше.')
        values['name']=r.text_input('ФИО',e['name'] if e else '',key=prefix+'_name')
        for col,field,label,options in [(l,'department_id','Подразделение сотрудника',ds),(r,'position_id','Должность',ps)]:
            ids=[o['id'] for o in options]; labels={o['id']:o['name'] for o in options}
            values[field]=col.selectbox(label,ids,index=ids.index(e[field]) if e else 0,key=prefix+'_'+field,format_func=lambda x,labels=labels:labels[x])
        values['hired']=l.date_input('Дата приёма',date.fromisoformat(e['hired']) if e else dushanbe_today(),format='DD.MM.YYYY',key=prefix+'_hired').isoformat()
        dismissal=r.date_input('Дата увольнения',date.fromisoformat(e['dismissed']) if e and e['dismissed'] else dushanbe_today(),format='DD.MM.YYYY',disabled=not archived or not admin,key=prefix+'_dismissal')
        values['dismissed']=dismissal.isoformat() if archived else None
        reason=st.text_area('Причина увольнения / основание',e['dismissal_reason'] if e else '',disabled=not archived or not admin,key=prefix+'_dismissal_reason',help='Укажите фактическое основание, например: по собственному желанию, соглашение сторон, окончание договора. Причина сохраняется в архиве и кадровой истории.')
        values['dismissal_reason']=reason if archived else ''
        values['pay_type']=l.selectbox('Вид оплаты',['salary','hourly'],index=1 if e and e['pay_type']=='hourly' else 0,format_func=lambda x:'Оклад за месяц' if x=='salary' else 'Почасовая оплата',key=prefix+'_pay_type')
        values['rate']=r.text_input('Оклад / часовая ставка, сомони',e['rate'] if e else '',key=prefix+'_rate')
        pattern=l.selectbox('График работы',['5/2','2/2','manual'],index=['5/2','2/2','manual'].index(schedule.get('pattern','5/2')),format_func=lambda x:'Вручную' if x=='manual' else x,key=prefix+'_pattern')
        hours=r.text_input('Обычных часов в смене',schedule.get('hours','8'),key=prefix+'_hours')
        anchor=l.date_input('Первый рабочий день цикла 2/2',date.fromisoformat(schedule.get('anchor',e['hired'] if e else dushanbe_today().isoformat())),format='DD.MM.YYYY',key=prefix+'_anchor')
        basis=r.selectbox('Пересчёт оклада при неполном месяце',['hours','days'],index=1 if schedule.get('salary_basis','days')=='days' else 0,format_func=lambda x:'По обычным часам' if x=='hours' else 'По отработанным дням',key=prefix+'_basis')
        values['schedule']={'pattern':pattern,'hours':hours,'anchor':anchor.isoformat(),'salary_basis':basis}
        values['notes']=st.text_area('Дополнительные сведения',e['notes'] if e else '',key=prefix+'_notes')
        values['version']=e['version'] if e else None
        st.caption('Изменение ставки и графика не переписывает уже сохранённые табели и расчёты. Для нового месяца проверьте применимость ставки.')
        save=st.form_submit_button('Сохранить изменения' if e else 'Добавить сотрудника',type='primary')
        dismiss=st.form_submit_button('Уволить и перенести в архив') if admin and e and archived and not e['dismissed'] else False
        if save or dismiss:
            saved_id=db.save_employee(values,user['id'],eid or None)
            st.session_state.open_employee=saved_id
            flash('Карточка сохранена. Для следующего сотрудника нажмите «Создать ещё одну карточку».'); st.rerun()
    if e and user['role']=='admin':
        with st.expander('Удаление ошибочной карточки'):
            st.caption('Удалить можно только карточку без табелей и расчётов. Для остальных используйте «Увольнение / архив».')
            confirm=st.checkbox(f"Подтверждаю удаление {e['number']} — {e['name']}",key=prefix+'_delete_confirm')
            if st.button('Удалить карточку',disabled=not confirm,key=prefix+'_delete'):
                db.delete_employee(eid,user['id']); st.session_state.open_employee=0; flash('Ошибочная карточка удалена'); st.rerun()
        with st.expander('Администратор: удалить сотрудника со всей историей'):
            st.warning('Будут удалены карточка, все табели, доплаты, версии расчётов и выплаты этого сотрудника. Он исчезнет и из архива, и из итогов отчётов. Перед удалением автоматически сохраняется полная копия базы; журнал удаления остаётся.')
            confirmation=st.text_input('Введите точный табельный номер для удаления',key=prefix+'_purge_number')
            reason=st.text_area('Причина полного удаления',key=prefix+'_purge_reason')
            confirmed=st.checkbox('Понимаю, что удаляю сотрудника и всю его историю',key=prefix+'_purge_confirm')
            if st.button('Удалить сотрудника и всю историю',disabled=not confirmed,key=prefix+'_purge'):
                backup=db.purge_employee(eid,user['id'],confirmation,reason,e['version'])
                st.session_state.open_employee=0
                st.session_state.pop('preview',None); st.session_state.pop('gross_preview',None)
                flash('Сотрудник и его история удалены. Резервная копия: '+backup); st.rerun()
    if e:
        from ui_archive import profile
        st.divider(); profile(db,e)


def catalog_page(db,user):
    for table,title in [('Departments','Подразделения'),('Positions','Должности')]:
        st.subheader(title)
        rows=db.query(f'SELECT * FROM {table} ORDER BY name')
        mapping={r['id']:r['name'] for r in rows}
        selected=st.selectbox('Запись: '+title,[0]+list(mapping),format_func=lambda x,mapping=mapping:'＋ Новая запись' if not x else mapping[x],key=table+'_choice')
        with st.form(table+'_'+str(selected)):
            name=st.text_input('Название',mapping.get(selected,''),key=table+'_name_'+str(selected))
            if st.form_submit_button('Сохранить название' if selected else 'Добавить'):
                if selected: db.update_catalog(table,selected,name,user['id'])
                else: db.catalog(table,name,user['id'])
                flash('Справочник сохранён'); st.rerun()
        if selected and user['role']=='admin':
            confirmed=st.checkbox('Подтверждаю удаление: '+mapping[selected],key=table+'_delete_confirm_'+str(selected))
            if st.button('Удалить запись',key=table+'_delete_'+str(selected),disabled=not confirmed):
                db.update_catalog(table,selected,'',user['id'],delete=True); flash('Запись удалена'); st.rerun()
