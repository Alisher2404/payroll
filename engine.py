"""Расчёт без float. Все параметры законодательства задаются явно."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import calendar
import json
from datetime import date


def dec(value):
    try:
        result = Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ValueError('Введите корректное число')
    if not result.is_finite() or result < 0:
        raise ValueError('Число должно быть конечным и неотрицательным')
    return result


def money(value):
    try:
        return dec(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError('Сумма слишком велика для расчёта')


def month_days(period):
    year, month = map(int, period.split('-'))
    return [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1]+1)]


def generate_timesheet(period, hired, dismissed=None, holidays=()):
    return [dict(date=d.isoformat(), code=('П' if d.isoformat() in holidays else 'В' if d.weekday()>4 else 'Я')
                 if d.isoformat() >= hired and (not dismissed or d.isoformat() <= dismissed) else 'Н',
                 hours='8' if d.weekday()<5 and d.isoformat() not in holidays and d.isoformat()>=hired and (not dismissed or d.isoformat()<=dismissed) else '0', overtime='0') for d in month_days(period)]


def scheduled_timesheet(period,hired,dismissed=None,schedule=None,holidays=()):
    """Шаблон графика, а не юридически утверждённый производственный календарь."""
    if isinstance(schedule,str): schedule=json.loads(schedule)
    schedule=schedule or {}
    pattern=schedule.get('pattern','5/2')
    if pattern not in ('5/2','2/2','manual'): raise ValueError('Неизвестный график')
    hours=dec(schedule.get('hours','8'))
    if not 0<hours<=24: raise ValueError('Продолжительность смены должна быть больше 0 и не более 24 часов')
    anchor=date.fromisoformat(schedule.get('anchor',hired))
    holidays=set(holidays)
    for holiday in holidays: date.fromisoformat(holiday)
    result=[]
    for d in month_days(period):
        in_employment=hired<=d.isoformat() and (not dismissed or d.isoformat()<=dismissed)
        working=(d.weekday()<5 if pattern=='5/2' else (d-anchor).days%4<2 if pattern=='2/2' else False)
        code='Я' if working else 'В'
        if d.isoformat() in holidays: code='П'
        if not in_employment: code='Н'
        result.append(dict(date=d.isoformat(),code=code,hours=str(hours) if code=='Я' else '0',overtime='0'))
    return result


def validate_timesheet(period, rows, employee):
    expected = {d.isoformat() for d in month_days(period)}
    if len(rows)!=len(expected) or {r['date'] for r in rows}!=expected:
        raise ValueError('Табель должен содержать каждый день месяца ровно один раз')
    for r in rows:
        if r['code'] not in ('Я','В','П','О','Б','Н','ПР'):
            raise ValueError('Неизвестный код табеля')
        h, overtime = dec(r['hours']), dec(r['overtime'])
        if h+overtime>24 or (r['code']!='Я' and (h or overtime)):
            raise ValueError('Часы допускаются только для явки; всего не более 24 часов в сутки')
        if (h or overtime) and (r['date']<employee['hired'] or (employee['dismissed'] and r['date']>employee['dismissed'])):
            raise ValueError('Работа вне периода трудоустройства')


def earnings_for(employee,period,rows,adjustments,overtime_factor=None):
    validate_timesheet(period, rows, employee)
    norm = dec(adjustments['norm_days'])
    norm_hours = dec(adjustments['norm_hours'])
    if not norm or not norm_hours:
        raise ValueError('Норма дней и часов должна быть больше нуля')
    days = sum(r['code']=='Я' and dec(r['hours'])>0 for r in rows)
    hours = sum((dec(r['hours']) for r in rows), Decimal(0))
    overtime = sum((dec(r['overtime']) for r in rows), Decimal(0))
    schedule=employee.get('schedule','{}')
    if isinstance(schedule,str): schedule=json.loads(schedule)
    by_hours=schedule.get('salary_basis','days')=='hours'
    if employee['pay_type']=='salary' and (hours>norm_hours if by_hours else days>norm):
        raise ValueError('Явки превышают норму. Работу в выходные оформите отдельной доплатой')
    rate = dec(employee['rate'])
    base = money((rate*hours/norm_hours if by_hours else rate*days/norm) if employee['pay_type']=='salary' else rate*hours)
    hourly = rate/norm_hours if employee['pay_type']=='salary' else rate
    if overtime and overtime_factor is None:
        raise ValueError('Для оплаты сверхурочных укажите проверенный множитель в налоговых правилах')
    earnings = {'Основная зарплата':base, 'Сверхурочные':money(hourly*overtime*dec(overtime_factor or '0'))}
    for key, label in [('bonus','Премия'),('allowance','Надбавки'),('tips','Распределённые чаевые'),('extra','Другие начисления'),('vacation','Отпускные (введены бухгалтером)'),('sick','Больничные (введены бухгалтером)')]:
        earnings[label]=money(adjustments.get(key,'0'))
    return earnings,days,hours,overtime


def calculate(employee, period, rows, rule, adjustments, final=False):
    if final and not rule.get('verified'):
        raise ValueError('Налоговые параметры требуют проверки администратором')
    if not rule.get('source'):
        raise ValueError('Укажите основание налоговых правил')
    for key in ('income','worker','employer','upper_rate'):
        if dec(rule[key])>100:
            raise ValueError('Ставки должны быть от 0 до 100 процентов')
    earnings,days,hours,overtime=earnings_for(employee,period,rows,adjustments,rule['overtime_factor'])
    gross=sum(earnings.values(),Decimal(0))
    exempt=money(adjustments.get('exempt','0'))
    if exempt>gross:
        raise ValueError('Необлагаемая сумма превышает начисление')
    social_base=max(Decimal(0), gross-exempt)
    worker=money(social_base*dec(rule['worker'])/100)
    taxable=max(Decimal(0),social_base-dec(rule['deduction'])-(worker if rule.get('deduct_worker') else 0))
    if dec(rule.get('threshold','0')):
        threshold=dec(rule['threshold'])
        tax=money(min(taxable,threshold)*dec(rule['income'])/100+max(Decimal(0),taxable-threshold)*dec(rule['upper_rate'])/100)
    else:
        tax=money(taxable*dec(rule['income'])/100)
    deductions={'Подоходный налог':tax,'Взнос работника':worker}
    for key,label in [('alimony','Алименты'),('advance','Аванс'),('other','Прочие удержания')]:
        deductions[label]=money(adjustments.get(key,'0'))
    withheld=sum(deductions.values(),Decimal(0))
    if withheld>gross:
        raise ValueError('Удержания превышают начисление')
    return dict(employee=dict(employee), period=period, rule=rule, adjustments=adjustments, timesheet=rows,
                days=days, hours=str(hours), overtime=str(overtime), earnings={k:str(v) for k,v in earnings.items()},
                deductions={k:str(v) for k,v in deductions.items()}, gross=str(gross), withheld=str(withheld),
                net=str(gross-withheld), employer=str(money(social_base*dec(rule['employer'])/100)), taxable=str(taxable))
