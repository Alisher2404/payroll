from io import BytesIO
from pathlib import Path
from decimal import Decimal
from xml.sax.saxutils import escape
import json
import pandas as pd


def records(store,period=None,history=False):
    sql='SELECT * FROM Payroll WHERE '+('1=1' if history else 'current=1')
    args=()
    if period:
        sql+=' AND period=?'; args=(period,)
    return [dict(json.loads(r['snapshot']),revision=r['revision'],id=r['id']) for r in store.query(sql+' ORDER BY period,employee_id,revision',args)]


def table(results):
    return pd.DataFrame([{'Период':r['period'],'Таб. №':r['employee']['number'],'ФИО':r['employee']['name'],
                         'Подразделение':r['employee']['department'],'Начислено':r['gross'],'Удержано':r['withheld'],
                         'К выплате':r['net'],'Взнос работодателя':r['employer'],'Версия':r.get('revision',0)} for r in results])


def aggregate(results,key):
    groups={}
    for r in results:
        label=r['employee']['department'] if key=='Подразделение' else r['period']
        target=groups.setdefault(label,{k:Decimal(0) for k in ('Начислено','Удержано','К выплате','Взнос работодателя')})
        for k,f in [('Начислено','gross'),('Удержано','withheld'),('К выплате','net'),('Взнос работодателя','employer')]:
            target[k]+=Decimal(r[f])
    return pd.DataFrame([{key:k,**{f:str(v) for f,v in vals.items()}} for k,vals in sorted(groups.items())])


def excel(frame):
    output=BytesIO()
    # Суммы остаются точными десятичными строками; формулы из пользовательских полей запрещены.
    safe=frame.map(lambda v: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
    with pd.ExcelWriter(output,engine='openpyxl') as writer:
        safe.to_excel(writer,index=False,sheet_name='Отчёт')
        sheet=writer.sheets['Отчёт']; sheet.freeze_panes='A2'; sheet.auto_filter.ref=sheet.dimensions
        from openpyxl.styles import Font, PatternFill
        for cell in sheet[1]:
            cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='16324F')
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width=min(45,max(15,max(len(str(c.value or '')) for c in col)+2))
    return output.getvalue()


def pdf(frame,title):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    fonts=[Path(__file__).resolve().parent/'assets'/'DejaVuSans.ttf']
    font=next((p for p in fonts if p.exists()),None)
    if not font:
        raise ValueError('Для PDF установите Arial или поместите DejaVuSans.ttf в assets')
    pdfmetrics.registerFont(TTFont('Payroll',str(font)))
    styles=getSampleStyleSheet(); style=styles['Normal']; style.fontName='Payroll'; style.fontSize=8; style.leading=11
    output=BytesIO(); doc=SimpleDocTemplate(output,pagesize=landscape(A4),rightMargin=24,leftMargin=24)
    rows=[[Paragraph(escape(str(c)),style) for c in frame.columns]]+[[Paragraph(escape(str(c)),style) for c in row] for row in frame.itertuples(index=False,name=None)]
    grid=Table(rows,repeatRows=1,colWidths=[(landscape(A4)[0]-48)/max(1,len(frame.columns))]*len(frame.columns))
    grid.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dbeafe')),('GRID',(0,0),(-1,-1),.3,colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    doc.build([Paragraph(escape(title),style),Spacer(1,15),grid])
    return output.getvalue()


def payslip(result):
    e=result['employee']
    rows=[('Сотрудник',e['name']),('Табельный номер',e['number']),('Должность',e['position']),('Период',result['period']),('Оклад / часовая ставка',e['rate']),('Отработано дней',result['days']),('Отработано часов',result['hours']),('Сверхурочных часов',result['overtime'])]
    rows+=list(result['earnings'].items())+list(result['deductions'].items())
    rows += [('Всего начислено',result['gross']),('Всего удержано',result['withheld']),('К выплате, TJS',result['net']),('Взнос работодателя (справочно)',result['employer'])]
    # Одна колонка содержит ФИО, даты, дни и деньги. Однородные строки нужны
    # Arrow/Streamlit: смешанный object (str + int) вызывает ArrowTypeError.
    return pd.DataFrame([(str(label),str(value)) for label,value in rows],columns=['Показатель','Значение'])
