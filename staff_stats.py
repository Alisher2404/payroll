from app_time import today as dushanbe_today, now as dushanbe_now
"""Статистика по текущим версиям расчётов, без двойного учёта перерасчётов."""
import json
from datetime import date
from decimal import Decimal
from engine import dec


def employee_statistics(db,employee_id,today=None):
    today=today or dushanbe_today().isoformat()
    employee=db.query('SELECT hired,dismissed FROM Employees WHERE id=?',(employee_id,))
    if not employee: raise ValueError('Карточка сотрудника не найдена')
    employee=employee[0]
    history=[dict(json.loads(r['snapshot']),id=r['id'],revision=r['revision'],current=r['current']) for r in db.query('SELECT * FROM Payroll WHERE employee_id=? ORDER BY period,revision',(employee_id,))]
    current=[r for r in history if r['current']]
    totals={k:sum((Decimal(r[k]) for r in current),Decimal(0)) for k in ('gross','withheld','net','employer')}
    payments=db.query('SELECT p.*,r.period,r.revision FROM Payments p JOIN Payroll r ON r.id=p.payroll_id WHERE r.employee_id=? ORDER BY p.paid_on,p.id',(employee_id,))
    totals['paid']=sum((Decimal(p['amount']) for p in payments if not p['void']),Decimal(0))
    totals['remaining']=totals['net']-totals['paid']
    # Авансы из расчётов выводятся отдельно: не смешиваем их с выплатой остатка.
    totals['advance']=sum((Decimal(r['adjustments'].get('advance','0')) for r in current),Decimal(0))
    time=[]
    for t in db.query('SELECT * FROM Timesheets WHERE employee_id=? ORDER BY period',(employee_id,)):
        rows=[r for r in json.loads(t['data']) if employee['hired']<=r['date']<=today and (not employee['dismissed'] or r['date']<=employee['dismissed'])]
        time.append({'Период':t['period'],'Явок':sum(r['code']=='Я' and dec(r['hours'])>0 for r in rows),'Обычных часов':str(sum((dec(r['hours']) for r in rows),Decimal(0))),'Сверхурочных часов':str(sum((dec(r['overtime']) for r in rows),Decimal(0))),'Дней отпуска':sum(r['code']=='О' for r in rows),'Больничных дней':sum(r['code']=='Б' for r in rows),'Прогулов':sum(r['code']=='ПР' for r in rows),'Отсутствий':sum(r['code']=='Н' for r in rows)})
    return {'history':history,'current':current,'totals':{k:str(v) for k,v in totals.items()},'payments':payments,'time':time,'events':db.query('SELECT e.event,e.effective_date,e.reason,e.created,u.login FROM EmploymentEvents e JOIN Users u ON u.id=e.user_id WHERE employee_id=? ORDER BY e.id DESC',(employee_id,))}
