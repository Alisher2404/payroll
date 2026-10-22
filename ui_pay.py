from app_time import today as dushanbe_today, now as dushanbe_now
import json
from datetime import date
from decimal import Decimal
import pandas as pd
import streamlit as st
from engine import calculate, earnings_for, scheduled_timesheet
from reports import payslip, records
from ui_staff import flash


def payroll_page(db,employees,period,user):
    if not employees: st.info('Добавьте сотрудников или загрузите примеры кофейни в настройках'); return
    mapping={e['id']:e for e in employees}
    eid=st.selectbox('Сотрудник',list(mapping),format_func=lambda x:mapping[x]['number']+' · '+mapping[x]['name'],key='calc_employee')
    e=mapping[eid]
    rows=db.query('SELECT * FROM Timesheets WHERE employee_id=? AND period=?',(eid,period))
    if not rows: st.info('Сначала сформируйте и сохраните табель за выбранный месяц'); return
    rows=json.loads(rows[0]['data'])
    try: rule=db.rule(period)
    except ValueError: rule=None
    if not rule:
        st.info('Налоговые правила ещё не заданы. Можно проверить начисления до налогов. Итог к выплате и сохранение расчёта появятся после настройки правил.')
    elif not rule.get('verified'):
        st.warning('Расчёт предварительный: налоговые параметры не подтверждены. Окончательное сохранение заблокировано.')
    drafts=db.query('SELECT * FROM PayrollDrafts WHERE employee_id=? AND period=?',(eid,period))
    draft=json.loads(drafts[0]['data']) if drafts else {}
    draft_version=drafts[0]['version'] if drafts else 0
    full=scheduled_timesheet(period,period+'-01',schedule=e['schedule'])
    defaults={'norm_days':str(sum(r['code']=='Я' for r in full)),'norm_hours':str(sum((Decimal(r['hours']) for r in full),Decimal(0)))}
    if defaults['norm_hours']=='0': defaults.update(norm_days='1',norm_hours='1')
    labels={'norm_days':'Норма рабочих дней','norm_hours':'Норма обычных часов','bonus':'Премия','allowance':'Надбавки и доплаты','tips':'Распределённые чаевые','extra':'Другие начисления','vacation':'Отпускные (готовая сумма)','sick':'Больничные (готовая сумма)','exempt':'Необлагаемая сумма для налогов и взносов','alimony':'Алименты','advance':'Ранее выплаченный аванс','other':'Прочие удержания'}
    with st.form(f'calculation_{eid}_{period}_{draft_version}'):
        st.caption('Нормы взяты из графика на полный месяц: проверьте их. Отпускные, больничные и особые доплаты рассчитываются отдельно. Чаевые здесь включаются в начисления; проверьте их налоговый режим.')
        cols=st.columns(3); adjustments={}
        for i,(key,label) in enumerate(labels.items()):
            adjustments[key]=cols[i%3].text_input(label,draft.get(key,defaults.get(key,'0')),key=f'adjust_{eid}_{period}_{draft_version}_{key}')
        a,b=st.columns(2)
        save_draft=a.form_submit_button('Сохранить доплаты и удержания')
        compute=b.form_submit_button('Рассчитать заработную плату',type='primary')
        if save_draft or compute:
            # Проверяем до записи черновика: ошибочные числа не попадут в БД.
            if compute:
                if rule:
                    result=calculate(e,period,rows,rule,adjustments)
                    st.session_state.preview=result
                    st.session_state.pop('gross_preview',None)
                else:
                    earnings,*_=earnings_for(e,period,rows,adjustments)
                    st.session_state.gross_preview={'employee_id':eid,'period':period,'earnings':{k:str(v) for k,v in earnings.items()}}
                    st.session_state.pop('preview',None)
            db.save_draft(eid,period,adjustments,user['id'],draft_version)
            if save_draft:
                st.session_state.pop('preview',None); st.session_state.pop('gross_preview',None)
                flash('Доплаты и удержания сохранены. Перед окончательным сохранением выполните расчёт заново.')
            st.rerun()
    preview=st.session_state.get('gross_preview')
    if preview and preview['employee_id']==eid and preview['period']==period:
        st.subheader('Начисления до налогов')
        st.dataframe(pd.DataFrame(preview['earnings'].items(),columns=['Вид начисления','Сумма, сомони']),hide_index=True,width='stretch')
        st.metric('Всего начислено до налогов',str(sum((Decimal(v) for v in preview['earnings'].values()),Decimal(0))))
        st.caption('Это не сумма к выплате: налоги и удержания ещё не рассчитаны.')
    result=st.session_state.get('preview')
    if result and result['period']==period and result['employee']['id']==eid:
        st.dataframe(payslip(result),hide_index=True,width='stretch')
        recalc=st.checkbox('Перерасчёт с сохранением предыдущей версии',key=f'recalc_{eid}_{period}')
        if st.button('Сохранить проверенный расчёт',type='primary',disabled=not bool(rule and rule.get('verified'))):
            db.save_payroll(result,user['id'],recalc)
            st.session_state.pop('preview',None); flash('Расчёт сохранён. Выплату можно зарегистрировать в разделе «Выплаты».'); st.rerun()


def payments_page(db,period,user):
    results=records(db,period)
    if not results: st.info('Сначала сохраните расчёты зарплаты за выбранный месяц'); return
    payments=db.query('SELECT p.*,r.employee_id,r.period FROM Payments p JOIN Payroll r ON r.id=p.payroll_id WHERE r.period=? ORDER BY p.id DESC',(period,))
    paid={}
    for payment in payments:
        if not payment['void']: paid[payment['payroll_id']]=paid.get(payment['payroll_id'],Decimal(0))+Decimal(payment['amount'])
    st.caption('Здесь регистрируется фактическая выдача остатка зарплаты, без повторного учёта аванса. Сохранение расчёта само по себе не означает выплату денег.')
    frame=pd.DataFrame([{'ФИО':r['employee']['name'],'К выплате после аванса':r['net'],'Уже выдано':str(paid.get(r['id'],Decimal(0))),'Остаток':str(Decimal(r['net'])-paid.get(r['id'],Decimal(0)))} for r in results])
    st.dataframe(frame,hide_index=True,width='stretch')
    mapping={r['id']:r for r in results}
    pid=st.selectbox('Расчёт для выплаты',list(mapping),format_func=lambda x:mapping[x]['employee']['name'],key='payment_payroll')
    remaining=Decimal(mapping[pid]['net'])-paid.get(pid,Decimal(0))
    with st.form(f'payment_{pid}_{len(payments)}'):
        amount=st.text_input('Сумма выплаты, сомони',str(remaining))
        reference=st.text_input('Номер платёжного документа / уникальная отметка',help='Например: КАССА-2026-10-001. Повторный номер для этого расчёта не допускается.')
        paid_on=st.date_input('Дата выплаты',dushanbe_today(),format='DD.MM.YYYY')
        method=st.selectbox('Способ выплаты',['Наличные','Перевод'])
        confirmed=st.checkbox('Подтверждаю, что деньги действительно выплачены')
        if st.form_submit_button('Зарегистрировать выплату'):
            if not confirmed: raise ValueError('Подтвердите фактическую выплату денег')
            db.register_payment(pid,amount,reference,paid_on.isoformat(),method,user['id']); flash('Выплата сохранена'); st.rerun()
    if payments:
        st.subheader('История выплат')
        st.dataframe(pd.DataFrame([{'№':p['id'],'Документ':p['reference'],'Дата':p['paid_on'],'Сумма':p['amount'],'Способ':p['method'],'Статус':'Отменена' if p['void'] else 'Проведена'} for p in payments]),hide_index=True,width='stretch')
        active={p['id']:p for p in payments if not p['void']}
        if active and user['role']=='admin':
            with st.expander('Отменить ошибочную выплату'):
                selected=st.selectbox('Выплата',list(active),format_func=lambda x:active[x]['reference'],key='void_payment_id')
                reason=st.text_input('Причина отмены')
                confirm=st.checkbox('Подтверждаю отмену записи о выплате')
                if st.button('Отменить выплату',disabled=not confirm):
                    db.void_payment(selected,reason,user['id']); flash('Выплата отменена, запись и причина сохранены в истории'); st.rerun()
