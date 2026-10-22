import pyarrow as pa
from test_payroll import setup
from engine import calculate
from reports import payslip


def test_payslip_serializes_to_arrow_without_fallback(setup):
    _,_,employee,rows,rule,adjustments=setup
    frame=payslip(calculate(employee,'2026-10',rows,rule,adjustments))
    arrow=pa.Table.from_pandas(frame,preserve_index=False)
    assert arrow.num_rows==len(frame)
    assert frame.loc[frame['Показатель']=='Отработано дней','Значение'].iloc[0]=='22'
    assert frame.loc[frame['Показатель']=='К выплате, TJS','Значение'].iloc[0]=='2656.00'
