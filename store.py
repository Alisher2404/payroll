from app_time import today as dushanbe_today, now as dushanbe_now
import sqlite3
import json
import hashlib
import secrets
import hmac
from pathlib import Path
from contextlib import contextmanager
from datetime import date
from engine import dec, money, validate_timesheet, calculate

ROOT=Path(__file__).resolve().parent


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True)


def password_hash(password, salt=None):
    if len(password)<10:
        raise ValueError('Пароль должен содержать не менее 10 символов')
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()


class Store:
    def __init__(self,path=None):
        self.path=Path(path or ROOT/'data'/'payroll.sqlite3')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connection() as c:
            c.executescript((ROOT/'schema.sql').read_text(encoding='utf-8'))
            # Добавляем поля без пересоздания таблиц и потери пользовательских данных.
            for table,field,definition in [('Employees','version','INTEGER NOT NULL DEFAULT 1'),('Employees','schedule',"TEXT NOT NULL DEFAULT '{}'"),('Employees','dismissal_reason',"TEXT NOT NULL DEFAULT ''"),('Timesheets','version','INTEGER NOT NULL DEFAULT 1')]:
                if field not in {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {field} {definition}')

    @contextmanager
    def connection(self):
        c=sqlite3.connect(self.path,timeout=20)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def query(self,sql,args=()):
        with self.connection() as c:
            return [dict(r) for r in c.execute(sql,args)]

    def authorize(self,c,user_id,admin=False):
        u=c.execute('SELECT * FROM Users WHERE id=? AND active=1',(user_id,)).fetchone()
        if not u or (admin and u['role']!='admin'):
            raise ValueError('Недостаточно прав')

    def audit(self,c,user,action,details):
        c.execute('INSERT INTO AuditLog(user_id,action,details,created) VALUES(?,?,?,?)',(user,action,encode(details),dushanbe_now().isoformat()))

    def create_user(self,login,password,role,user=None):
        if not login.strip() or role not in ('admin','accountant'):
            raise ValueError('Проверьте логин и роль')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT count(*) FROM Users').fetchone()[0]:
                self.authorize(c,user,True)
            elif role!='admin':
                raise ValueError('Первый пользователь должен быть администратором')
            c.execute('INSERT INTO Users(login,password,role) VALUES(?,?,?)',(login.strip(),password_hash(password),role))
            self.audit(c,user,'Пользователь создан',{'login':login,'role':role})

    def login(self,login,password):
        rows=self.query('SELECT * FROM Users WHERE login=? AND active=1',(login,))
        if rows:
            u=rows[0]
            try:
                valid=hmac.compare_digest(u['password'],password_hash(password,u['password'].split(':')[0]))
            except ValueError:
                valid=False
            if valid:
                return {k:u[k] for k in ('id','login','role')}
        return None

    def catalog(self,table,name,user):
        if table not in ('Departments','Positions') or not name.strip():
            raise ValueError('Введите название справочника')
        with self.connection() as c:
            self.authorize(c,user)
            if c.execute(f'SELECT 1 FROM {table} WHERE name=?',(name.strip(),)).fetchone():
                raise ValueError('Такое название уже существует')
            c.execute(f'INSERT INTO {table}(name) VALUES(?)',(name.strip(),))
            self.audit(c,user,'Справочник',{'table':table,'name':name})

    def employees(self):
        return self.query('SELECT e.*,d.name department,p.name position FROM Employees e JOIN Departments d ON d.id=e.department_id JOIN Positions p ON p.id=e.position_id ORDER BY e.number')

    def save_employee(self,values,user,employee_id=None):
        fields=('number','name','department_id','position_id','hired','dismissed','pay_type','rate','notes','dismissal_reason')
        v={k:values.get(k,'') if k=='dismissal_reason' else values[k] for k in fields}
        v['dismissal_reason']=v['dismissal_reason'].strip() if v['dismissed'] else ''
        v['number']=str(v['number']).strip().upper()
        v['name']=v['name'].strip()
        if not v['name'].strip() or not v['number'].strip():
            raise ValueError('ФИО и табельный номер обязательны')
        date.fromisoformat(v['hired'])
        if v['dismissed'] and date.fromisoformat(v['dismissed'])<date.fromisoformat(v['hired']):
            raise ValueError('Увольнение раньше приёма')
        v['rate']=str(money(v['rate']))
        if not money(v['rate']):
            raise ValueError('Оклад или часовая ставка должны быть больше нуля')
        if v['pay_type'] not in ('salary','hourly'):
            raise ValueError('Выберите оклад или почасовую оплату')
        schedule=values.get('schedule','{}')
        if isinstance(schedule,str): schedule=json.loads(schedule)
        from engine import scheduled_timesheet
        scheduled_timesheet(v['hired'][:7],v['hired'],v['dismissed'],schedule)
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            self.authorize(c,user)
            old=c.execute('SELECT * FROM Employees WHERE id=?',(employee_id,)).fetchone() if employee_id else None
            employment_changed=bool(old and (old['dismissed']!=v['dismissed'] or old['dismissal_reason']!=v['dismissal_reason'])) or bool(not old and v['dismissed'])
            if employment_changed:
                self.authorize(c,user,True)
                if v['dismissed'] and not v['dismissal_reason']:
                    raise ValueError('Укажите причину увольнения или основание: например, «По собственному желанию»')
            duplicate=c.execute('SELECT id,name FROM Employees WHERE UPPER(TRIM(number))=? AND id!=?',(v['number'],employee_id or -1)).fetchone()
            if duplicate:
                raise ValueError(f"Табельный номер {v['number']} уже занят сотрудником «{duplicate['name']}». Выберите его карточку для редактирования или используйте другой номер.")
            if employee_id:
                old=c.execute('SELECT * FROM Employees WHERE id=?',(employee_id,)).fetchone()
                if not old: raise ValueError('Карточка уже удалена. Обновите список')
                if values.get('version') is not None and values['version']!=old['version']:
                    raise ValueError('Карточка изменена в другом окне. Обновите страницу и повторите изменение')
                for t in c.execute('SELECT period,data FROM Timesheets WHERE employee_id=?',(employee_id,)):
                    try:
                        validate_timesheet(t['period'],json.loads(t['data']),v)
                    except ValueError as exc:
                        raise ValueError(f"Проверьте сохранённый табель за {t['period']}: {exc}. Сначала исправьте табель или даты трудоустройства.") from exc
                c.execute('UPDATE Employees SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',(*v.values(),employee_id))
                c.execute('UPDATE Employees SET version=version+1,schedule=? WHERE id=?',(encode(schedule),employee_id))
            else:
                employee_id=c.execute('INSERT INTO Employees('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',tuple(v.values())).lastrowid
                c.execute('UPDATE Employees SET schedule=? WHERE id=?',(encode(schedule),employee_id))
            if employment_changed:
                event='Восстановление' if not v['dismissed'] else 'Увольнение' if not old or not old['dismissed'] else 'Изменение увольнения'
                c.execute('INSERT INTO EmploymentEvents(employee_id,user_id,event,effective_date,reason,snapshot,created) VALUES(?,?,?,?,?,?,?)',(employee_id,user,event,v['dismissed'] or dushanbe_today().isoformat(),v['dismissal_reason'] or 'Восстановлен в списке работников',encode({'before':dict(old) if old else None,'after':v}),dushanbe_now().isoformat()))
            self.audit(c,user,'Карточка сотрудника',{'id':employee_id,'values':v})
        return employee_id

    def save_timesheet(self,employee,period,rows,user,expected_version=None):
        validate_timesheet(period,rows,employee)
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            self.authorize(c,user)
            current=c.execute('SELECT * FROM Employees WHERE id=?',(employee['id'],)).fetchone()
            if not current: raise ValueError('Сотрудник удалён')
            validate_timesheet(period,rows,dict(current))
            prev=c.execute('SELECT version FROM Timesheets WHERE employee_id=? AND period=?',(employee['id'],period)).fetchone()
            if expected_version is not None and expected_version!=(prev[0] if prev else 0):
                raise ValueError('Табель изменён в другом окне. Перезагрузите его перед сохранением')
            c.execute('INSERT INTO Timesheets(employee_id,period,data) VALUES(?,?,?) ON CONFLICT(employee_id,period) DO UPDATE SET data=excluded.data',(employee['id'],period,encode(rows)))
            if prev: c.execute('UPDATE Timesheets SET version=version+1 WHERE employee_id=? AND period=?',(employee['id'],period))
            self.audit(c,user,'Табель сохранён',{'employee':employee['id'],'period':period,'rows':rows})

    def save_rule(self,starts,ends,rule,user,rule_id=None):
        date.fromisoformat(starts); date.fromisoformat(ends)
        if starts>ends or not rule.get('source'):
            raise ValueError('Проверьте период и основание')
        for k in ('income','worker','employer','upper_rate'):
            if dec(rule[k])>100:
                raise ValueError('Ставка должна быть от 0 до 100')
        for k in ('deduction','threshold','overtime_factor'):
            dec(rule[k])
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            self.authorize(c,user,True)
            if c.execute('SELECT 1 FROM TaxSettings WHERE starts<=? AND ends>=? AND id!=?',(ends,starts,rule_id or -1)).fetchone():
                raise ValueError('Периоды правил пересекаются')
            old=None
            if rule_id:
                old=dict(c.execute('SELECT * FROM TaxSettings WHERE id=?',(rule_id,)).fetchone())
                c.execute('UPDATE TaxSettings SET starts=?,ends=?,data=? WHERE id=?',(starts,ends,encode(rule),rule_id))
            else:
                c.execute('INSERT INTO TaxSettings(starts,ends,data) VALUES(?,?,?)',(starts,ends,encode(rule)))
            self.audit(c,user,'Налоговые правила',{'before':old,'starts':starts,'ends':ends,'rule':rule})

    def rule(self,period):
        from engine import month_days
        days=month_days(period)
        rows=self.query('SELECT * FROM TaxSettings WHERE starts<=? AND ends>=?',(days[0].isoformat(),days[-1].isoformat()))
        if not rows:
            raise ValueError('Нет правил, покрывающих весь месяц. Изменение правил внутри месяца требует отдельного расчёта')
        return json.loads(rows[0]['data'])

    def save_payroll(self,result,user,recalculate=False):
        # Подтверждаем текущие входные данные и атомарно создаём ревизию.
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            self.authorize(c,user)
            e=dict(c.execute('SELECT e.*,d.name department,p.name position FROM Employees e JOIN Departments d ON d.id=e.department_id JOIN Positions p ON p.id=e.position_id WHERE e.id=?',(result['employee']['id'],)).fetchone())
            t=c.execute('SELECT data FROM Timesheets WHERE employee_id=? AND period=?',(e['id'],result['period'])).fetchone()
            rule=self.rule(result['period'])
            if not t:
                raise ValueError('Сначала сохраните табель')
            draft=c.execute('SELECT data FROM PayrollDrafts WHERE employee_id=? AND period=?',(e['id'],result['period'])).fetchone()
            if draft and json.loads(draft[0])!=result['adjustments']:
                raise ValueError('Доплаты или удержания изменились. Выполните расчёт заново')
            fresh=calculate(e,result['period'],json.loads(t[0]),rule,result['adjustments'],final=True)
            if encode(fresh)!=encode(result):
                raise ValueError('Данные изменились. Выполните расчёт заново')
            prev=c.execute('SELECT MAX(revision) FROM Payroll WHERE employee_id=? AND period=?',(e['id'],result['period'])).fetchone()[0] or 0
            if c.execute('SELECT 1 FROM Payments p JOIN Payroll r ON r.id=p.payroll_id WHERE r.employee_id=? AND r.period=? AND p.void=0',(e['id'],result['period'])).fetchone():
                raise ValueError('По расчёту есть выплаты. Сначала администратор должен отменить ошибочную выплату с указанием причины')
            if prev and not recalculate:
                raise ValueError('Расчёт уже существует. Включите перерасчёт')
            c.execute('UPDATE Payroll SET current=0 WHERE employee_id=? AND period=?',(e['id'],result['period']))
            pid=c.execute('INSERT INTO Payroll(employee_id,period,revision,snapshot,created) VALUES(?,?,?,?,?)',(e['id'],result['period'],prev+1,encode(result),dushanbe_now().isoformat())).lastrowid
            for kind,items in [('earning',result['earnings']),('deduction',result['deductions']),('employer',{'Взнос работодателя':result['employer']})]:
                c.executemany('INSERT INTO PayrollItems(payroll_id,kind,name,amount) VALUES(?,?,?,?)',[(pid,kind,k,v) for k,v in items.items()])
            self.audit(c,user,'Расчёт сохранён',{'payroll':pid,'revision':prev+1})
            return pid

    def next_number(self):
        used={r['number'].upper() for r in self.query('SELECT number FROM Employees')}
        n=1
        while f'EMP-{n:04}' in used: n+=1
        return f'EMP-{n:04}'

    def delete_employee(self,employee_id,user):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); self.authorize(c,user,True)
            employee=c.execute('SELECT * FROM Employees WHERE id=?',(employee_id,)).fetchone()
            if not employee: raise ValueError('Карточка уже удалена')
            for table in ('Timesheets','Payroll','PayrollDrafts','EmploymentEvents'):
                if c.execute(f'SELECT 1 FROM {table} WHERE employee_id=?',(employee_id,)).fetchone():
                    raise ValueError('У сотрудника есть табели или расчёты. Укажите дату увольнения в карточке: история должна сохраниться')
            c.execute('DELETE FROM Employees WHERE id=?',(employee_id,))
            self.audit(c,user,'Карточка удалена',dict(employee))

    def purge_employee(self,employee_id,user,confirmation,reason,expected_version):
        """Явное удаление всей истории администратором. Копия предшествует DELETE."""
        from datetime import datetime
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); self.authorize(c,user,True)
            employee=c.execute('SELECT * FROM Employees WHERE id=?',(employee_id,)).fetchone()
            if not employee: raise ValueError('Карточка уже удалена')
            if confirmation.strip()!=employee['number']: raise ValueError('Для подтверждения введите точный табельный номер сотрудника')
            if expected_version!=employee['version']: raise ValueError('Карточка изменена. Обновите страницу перед удалением')
            if len(reason.strip())<5: raise ValueError('Укажите причину удаления (не менее 5 символов)')
            counts={t:c.execute(f'SELECT count(*) FROM {t} WHERE employee_id=?',(employee_id,)).fetchone()[0] for t in ('Timesheets','Payroll','PayrollDrafts','EmploymentEvents')}
            # Удерживаем блокировку записи, пока другой read-only connection снимает копию.
            folder=self.path.parent/'deletion-backups'
            target=folder/('before-delete-'+dushanbe_now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)+'.sqlite3')
            try:
                folder.mkdir(exist_ok=True)
                from contextlib import closing
                with self.connection() as source, closing(sqlite3.connect(target)) as dest:
                    source.backup(dest)
            except (OSError,sqlite3.Error) as exc:
                raise ValueError('Не удалось создать резервную копию. Удаление отменено') from exc
            c.execute('DELETE FROM Payments WHERE payroll_id IN (SELECT id FROM Payroll WHERE employee_id=?)',(employee_id,))
            c.execute('DELETE FROM PayrollItems WHERE payroll_id IN (SELECT id FROM Payroll WHERE employee_id=?)',(employee_id,))
            for table in ('Payroll','PayrollDrafts','Timesheets','EmploymentEvents'):
                c.execute(f'DELETE FROM {table} WHERE employee_id=?',(employee_id,))
            c.execute('DELETE FROM Employees WHERE id=?',(employee_id,))
            self.audit(c,user,'Сотрудник удалён со всей историей',{'employee':dict(employee),'counts':counts,'reason':reason.strip(),'backup':str(target.resolve())})
            return str(target.resolve())

    def update_catalog(self,table,row_id,name,user,delete=False):
        if table not in ('Departments','Positions'): raise ValueError('Неизвестный справочник')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); self.authorize(c,user,delete)
            old=c.execute(f'SELECT * FROM {table} WHERE id=?',(row_id,)).fetchone()
            if not old: raise ValueError('Запись уже удалена')
            if delete:
                field='department_id' if table=='Departments' else 'position_id'
                if c.execute(f'SELECT 1 FROM Employees WHERE {field}=?',(row_id,)).fetchone():
                    raise ValueError('Запись используется в карточках сотрудников. Сначала измените их')
                c.execute(f'DELETE FROM {table} WHERE id=?',(row_id,))
            else:
                if not name.strip(): raise ValueError('Введите название')
                if c.execute(f'SELECT 1 FROM {table} WHERE name=? AND id!=?',(name.strip(),row_id)).fetchone():
                    raise ValueError('Такое название уже существует')
                c.execute(f'UPDATE {table} SET name=? WHERE id=?',(name.strip(),row_id))
            self.audit(c,user,'Справочник удалён' if delete else 'Справочник изменён',{'table':table,'before':dict(old),'name':name})

    def save_draft(self,employee_id,period,data,user,expected_version=None):
        from engine import month_days
        month_days(period)
        for value in data.values(): dec(value)
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); self.authorize(c,user)
            prev=c.execute('SELECT version FROM PayrollDrafts WHERE employee_id=? AND period=?',(employee_id,period)).fetchone()
            if expected_version is not None and expected_version!=(prev[0] if prev else 0):
                raise ValueError('Доплаты изменены в другом окне. Перезагрузите страницу')
            c.execute('INSERT INTO PayrollDrafts(employee_id,period,data) VALUES(?,?,?) ON CONFLICT(employee_id,period) DO UPDATE SET data=excluded.data,version=PayrollDrafts.version+1',(employee_id,period,encode(data)))
            self.audit(c,user,'Доплаты и удержания сохранены',{'employee':employee_id,'period':period,'data':data})

    def register_payment(self,payroll_id,amount,reference,paid_on,method,user):
        from decimal import Decimal
        amount=money(amount); date.fromisoformat(paid_on)
        if not amount or not reference.strip() or method not in ('Наличные','Перевод'):
            raise ValueError('Укажите положительную сумму, номер документа и способ выплаты')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); self.authorize(c,user)
            r=c.execute('SELECT * FROM Payroll WHERE id=? AND current=1',(payroll_id,)).fetchone()
            if not r: raise ValueError('Можно оплатить только действующую версию расчёта')
            if c.execute('SELECT 1 FROM Payments WHERE payroll_id=? AND reference=?',(payroll_id,reference.strip())).fetchone():
                raise ValueError('Выплата с этим номером документа уже зарегистрирована')
            paid=sum((Decimal(row[0]) for row in c.execute('SELECT amount FROM Payments WHERE payroll_id=? AND void=0',(payroll_id,))),Decimal(0))
            if amount>Decimal(json.loads(r['snapshot'])['net'])-paid:
                raise ValueError('Сумма превышает остаток к выплате')
            pid=c.execute('INSERT INTO Payments(payroll_id,amount,reference,paid_on,method) VALUES(?,?,?,?,?)',(payroll_id,str(amount),reference.strip(),paid_on,method)).lastrowid
            self.audit(c,user,'Выплата зарегистрирована',{'id':pid,'payroll':payroll_id,'amount':str(amount),'reference':reference,'date':paid_on,'method':method})
            return pid

    def void_payment(self,payment_id,reason,user):
        if len(reason.strip())<5: raise ValueError('Укажите причину отмены (не менее 5 символов)')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE'); self.authorize(c,user,True)
            row=c.execute('SELECT * FROM Payments WHERE id=? AND void=0',(payment_id,)).fetchone()
            if not row: raise ValueError('Выплата не найдена или уже отменена')
            c.execute('UPDATE Payments SET void=1 WHERE id=?',(payment_id,))
            self.audit(c,user,'Выплата отменена',{'before':dict(row),'reason':reason.strip()})

    def backup(self,user):
        from io import BytesIO
        import tempfile
        with self.connection() as c:
            self.authorize(c,user,True)
            self.audit(c,user,'Резервная копия',{})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'backup.sqlite3'
            from contextlib import closing
            with self.connection() as c, closing(sqlite3.connect(path)) as dest:
                c.backup(dest)
            return path.read_bytes()
