"""Демо без вымышленных налоговых ставок и предустановленных паролей."""
from engine import generate_timesheet


def seed(db,user):
    if any(e['number'].startswith('DEMO-') for e in db.employees()):
        raise ValueError('Демонстрационные сотрудники уже загружены')
    departments=['Администрация','Бухгалтерия','Производство']
    positions=['Директор','Бухгалтер','Инженер','Оператор','Специалист']
    for table,names in [('Departments',departments),('Positions',positions)]:
        existing={r['name'] for r in db.query(f'SELECT name FROM {table}')}
        for name in names:
            if name not in existing: db.catalog(table,name,user)
    ds={r['name']:r['id'] for r in db.query('SELECT * FROM Departments')}
    ps={r['name']:r['id'] for r in db.query('SELECT * FROM Positions')}
    names=['Каримов Алишер Саидович','Рахимова Мадина Фарходовна','Саидов Фирдавс Рустамович','Назарова Нигина Ахмадовна','Юсуфов Бехруз Алиевич','Одинаева Дилором Рахмоновна','Шарипов Далер Усмонович','Мирзоева Мехрона Саидовна','Холиков Рустам Бахтиёрович','Алиева Фарзона Каримовна']
    for i,name in enumerate(names):
        eid=db.save_employee(dict(number=f'DEMO-{i+1:03}',name=name,department_id=ds[departments[i%3]],position_id=ps[positions[i%5]],hired='2026-01-01',dismissed=None,pay_type='hourly' if i%3==2 else 'salary',rate=str(30+i*3 if i%3==2 else 3000+i*500),notes='Вымышленный сотрудник для проверки'),user)
        e=next(e for e in db.employees() if e['id']==eid)
        rows=generate_timesheet('2026-10',e['hired'])
        if i==1:
            for r in rows[:7]: r.update(code='О',hours='0')
        if i==2: rows[0]['overtime']='2'
        db.save_timesheet(e,'2026-10',rows,user)
