from app_time import now as dushanbe_now
"""Запуск реальных тестов и сохранение результата в UTF-8."""
from pathlib import Path
from datetime import datetime
import os
import subprocess
import sys
import pandas
import streamlit

root=Path(__file__).resolve().parent
result=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=root,env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8')
header=f'Executed: {dushanbe_now().isoformat(timespec="seconds")}\nPython: {sys.version.split()[0]}\nStreamlit: {streamlit.__version__}\nPandas: {pandas.__version__}\nCommand: python -m pytest -q\n\n'
(root/'docs'/'test-results-update.txt').write_text(header+result.stdout,encoding='utf-8')
print(result.stdout)
sys.exit(result.returncode)
