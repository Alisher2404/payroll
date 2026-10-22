from app_time import today as dushanbe_today, now as dushanbe_now
"""Примеры сотрудников кофейни. Повторная загрузка не меняет существующие карточки."""
from datetime import date
from store import encode
from engine import scheduled_timesheet

TEAM=[
    ('Управление','Управляющий','Каримов Алишер Саидович','salary','6000','5/2','8',0),
    ('Бар','Старший бариста','Рахимова Мадина Фарходовна','hourly','28','2/2','12',0),
    ('Бар','Бариста','Саидов Фирдавс Рустамович','hourly','23','2/2','12',0),
    ('Бар','Бариста','Назарова Нигина Ахмадовна','hourly','23','2/2','12',2),
    ('Бар','Бариста','Юсуфов Бехруз Алиевич','hourly','22','2/2','12',2),
    ('Зал','Кассир','Одинаева Дилором Рахмоновна','hourly','20','2/2','12',0),
    ('Зал','Кассир','Шарипов Далер Усмонович','hourly','20','2/2','12',2),
    ('Кухня','Кондитер','Мирзоева Мехрона Саидовна','salary','4500','5/2','8',0),
    ('Хозяйственная служба','Уборщик','Холиков Рустам Бахтиёрович','hourly','16','5/2','4',0),
    ('Управление','Бухгалтер','Алиева Фарзона Каримовна','salary','3000','5/2','4',0),
]


def seed_cafe(db,user,period=None):
    period=period or dushanbe_today().strftime('%Y-%m')
    # Полностью атомарная загрузка: при ошибке не останется половины команды.
    with db.connection() as c:
        c.execute('BEGIN IMMEDIATE'); db.authorize(c,user,True)
        created=0
        for i,(department,position,name,pay_type,rate,pattern,hours,offset) in enumerate(TEAM,1):
            number=f'CAFE-{i:03}'
            if c.execute('SELECT 1 FROM Employees WHERE number=?',(number,)).fetchone(): continue
            for table,value in [('Departments',department),('Positions',position)]:
                c.execute(f'INSERT OR IGNORE INTO {table}(name) VALUES(?)',(value,))
            did=c.execute('SELECT id FROM Departments WHERE name=?',(department,)).fetchone()[0]
            pid=c.execute('SELECT id FROM Positions WHERE name=?',(position,)).fetchone()[0]
            schedule={'pattern':pattern,'hours':hours,'anchor':period+f'-{1+offset:02}','salary_basis':'hours'}
            eid=c.execute('INSERT INTO Employees(number,name,department_id,position_id,hired,pay_type,rate,notes,schedule) VALUES(?,?,?,?,?,?,?,?,?)',(number,name,did,pid,period+'-01',pay_type,rate+'.00','Вымышленный сотрудник кофейни «Зёрна». Ставка и график — учебный пример.',encode(schedule))).lastrowid
            rows=scheduled_timesheet(period,period+'-01',schedule=schedule)
            if i==3:
                working=[r for r in rows if r['code']=='Я']
                for row in working[:2]: row.update(code='О',hours='0')
            c.execute('INSERT INTO Timesheets(employee_id,period,data) VALUES(?,?,?)',(eid,period,encode(rows)))
            norm=scheduled_timesheet(period,period+'-01',schedule=schedule)
            from decimal import Decimal
            draft={'norm_days':str(sum(r['code']=='Я' for r in norm)),'norm_hours':str(sum((Decimal(r['hours']) for r in norm),Decimal(0))),'bonus':'300' if i==2 else '0','tips':'150' if 2<=i<=5 else '0','allowance':'0','extra':'0','vacation':'0','sick':'0','exempt':'0','alimony':'0','advance':'500' if i==2 else '0','other':'0'}
            c.execute('INSERT INTO PayrollDrafts(employee_id,period,data) VALUES(?,?,?)',(eid,period,encode(draft)))
            created+=1
        db.audit(c,user,'Примеры кофейни загружены',{'created':created,'period':period})
        return created
