from app_time import today as dushanbe_today, now as dushanbe_now
from datetime import date
from decimal import Decimal
import pandas as pd
import streamlit as st
from staff_stats import employee_statistics
from reports import table, excel


def profile(db,employee):
    st.subheader('Статистика и история сотрудника')
    st.write(f"{employee['name']} · {employee['number']} · {employee['position']} · {employee['department']}")
    st.write('Дата приёма: '+employee['hired']+' · Дата увольнения: '+(employee['dismissed'] or 'работает'))
    if employee['dismissed']:
        st.info('Причина / основание увольнения: '+(employee['dismissal_reason'] or 'Не указана в прежней версии. Администратор может дополнить карточку.'))
    stats=employee_statistics(db,employee['id'])
    totals=stats['totals']
    a,b,c,d=st.columns(4)
    for col,key,label in [(a,'gross','Начислено за всё время'),(b,'withheld','Удержано'),(c,'paid','Выдан остаток зарплаты'),(d,'remaining','Осталось выдать')]:
        col.metric(label,totals[key])
    st.caption(f"Учтённые авансы: {totals['advance']} сомони. Взносы работодателя: {totals['employer']} сомони. Итоги зарплаты рассчитаны по последним версиям; старые версии не суммируются повторно.")
    st.subheader('Рабочее время, отпуска и отсутствия')
    if stats['time']:
        frame=pd.DataFrame(stats['time'])
        st.dataframe(frame,hide_index=True,width='stretch')
        st.caption('Учитываются сохранённые отметки по сегодняшний день. Будущие смены не включены. Табель может содержать учебные или плановые отметки — проверьте их соответствие фактической работе.')
        a,b,c=st.columns(3)
        a.metric('Всего явок',sum(r['Явок'] for r in stats['time']))
        b.metric('Всего обычных часов',str(sum((Decimal(r['Обычных часов']) for r in stats['time']),Decimal(0))))
        c.metric('Всего сверхурочных часов',str(sum((Decimal(r['Сверхурочных часов']) for r in stats['time']),Decimal(0))))
    else: st.info('Сохранённых табелей пока нет')
    st.subheader('Начисления по месяцам')
    include_old=st.checkbox('Показать также прежние версии расчётов',key=f"profile_versions_{employee['id']}")
    selected=stats['history'] if include_old else stats['current']
    if selected:
        frame=table(selected)
        frame['Статус версии']=['Текущая' if r['current'] else 'Заменена перерасчётом' for r in selected]
        st.dataframe(frame,hide_index=True,width='stretch')
        detail=[]
        for r in selected:
            for kind,items in [('Начисление',r['earnings']),('Удержание',r['deductions'])]:
                detail.extend({'Период':r['period'],'Версия':r['revision'],'Тип':kind,'Основание':name,'Сумма':amount} for name,amount in items.items())
        with st.expander('Все начисления и удержания подробно'):
            st.dataframe(pd.DataFrame(detail),hide_index=True,width='stretch')
        st.download_button('Скачать историю начислений Excel',excel(frame),f"history-{employee['number']}.xlsx",key=f"profile_export_{employee['id']}")
    else: st.info('Окончательные расчёты ещё не сохранены. Черновики доплат не считаются начисленной зарплатой.')
    st.subheader('Все выплаты')
    if stats['payments']:
        st.dataframe(pd.DataFrame([{'Период':p['period'],'Дата':p['paid_on'],'Документ':p['reference'],'Сумма':p['amount'],'Способ':p['method'],'Статус':'Отменена' if p['void'] else 'Проведена'} for p in stats['payments']]),hide_index=True,width='stretch')
    else: st.info('Выплаты не зарегистрированы')
    st.subheader('Увольнения и восстановления')
    if stats['events']:
        st.dataframe(pd.DataFrame([{'Действие':r['event'],'Дата':r['effective_date'],'Причина':r['reason'],'Кто оформил':r['login'],'Записано':r['created']} for r in stats['events']]),hide_index=True,width='stretch')
    else: st.caption('Кадровых событий после установки этой функции ещё нет.')


def archive_page(db,user):
    archived=[e for e in db.employees() if e['dismissed'] and e['dismissed']<=dushanbe_today().isoformat()]
    st.caption('Здесь находятся уволенные сотрудники. Их табели, расчёты и выплаты сохраняются. Раздел показывает данные за всё время, независимо от месяца слева.')
    query=st.text_input('Поиск в архиве по ФИО, номеру или причине',key='archive_search')
    archived=[e for e in archived if query.casefold() in (e['name']+' '+e['number']+' '+e['dismissal_reason']).casefold()]
    if not archived: st.info('В архиве нет сотрудников, соответствующих поиску'); return
    st.dataframe(pd.DataFrame([{'Таб. №':e['number'],'ФИО':e['name'],'Должность':e['position'],'Дата приёма':e['hired'],'Дата увольнения':e['dismissed'],'Причина увольнения':e['dismissal_reason'] or 'Не указана'} for e in archived]),hide_index=True,width='stretch')
    mapping={e['id']:e for e in archived}
    eid=st.selectbox('Бывший сотрудник',list(mapping),format_func=lambda x:mapping[x]['number']+' · '+mapping[x]['name'],key='archive_employee')
    if user['role']=='admin' and st.button('Открыть карточку для изменения или восстановления'):
        st.session_state.open_employee=eid; st.session_state.next_page='Сотрудники'; st.rerun()
    profile(db,mapping[eid])
