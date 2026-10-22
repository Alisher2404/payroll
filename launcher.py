"""Запуск локального сервера без консоли, журнал ошибок и защита от второго запуска."""
from pathlib import Path
import argparse
import ctypes
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
PORT=8501
URL=f'http://127.0.0.1:{PORT}'
RECORD=DATA/'server.json'


def message(text,error=False):
    if os.name=='nt': ctypes.windll.user32.MessageBoxW(0,text,'Зарплата кофейни',0x10 if error else 0x40)
    else: print(text)


def healthy():
    try:
        with urllib.request.urlopen(URL+'/_stcore/health',timeout=2) as response:
            return response.status==200
    except (OSError,ValueError): return False


def owned_process(record):
    """Не останавливаем посторонний процесс при повторном использовании PID."""
    if record.get('app')!=str(ROOT/'app.py'): return False
    pid=int(record.get('pid',0))
    if pid<=0: return False
    if os.name!='nt': return False
    command=f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; if($p) {{$p.CommandLine}}"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    return '-m streamlit' in result.stdout and str(ROOT/'app.py').casefold() in result.stdout.casefold()


def load_record():
    try: return json.loads(RECORD.read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}


def start(open_browser=True):
    DATA.mkdir(exist_ok=True)
    # Именованный mutex живёт, пока длится запуск, и автоматически освобождается при сбое.
    name='Local\\CafePayroll-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:24]
    mutex=None
    if os.name=='nt':
        kernel=ctypes.windll.kernel32
        kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,name)
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        status=kernel.WaitForSingleObject(mutex,60000)
        if status not in (0,0x80): raise RuntimeError('Другой запуск ещё выполняется. Подождите минуту')
    try:
        record=load_record()
        if owned_process(record) and healthy():
            if open_browser: webbrowser.open(URL)
            return 'reused'
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',PORT))==0:
                raise RuntimeError('Порт 8501 занят. Закройте старое чёрное окно программы и снова нажмите «Запустить».')
        python=ROOT/'.venv'/'Scripts'/'pythonw.exe'
        if not python.exists(): raise RuntimeError('Сначала выполните установку через start.bat. Затем используйте «Запустить.vbs».')
        with (DATA/'server.log').open('a',encoding='utf-8') as log:
            command=[str(python),'-m','streamlit','run',str(ROOT/'app.py'),'--server.address','127.0.0.1','--server.port',str(PORT),'--server.headless','true','--browser.gatherUsageStats','false']
            env=dict(os.environ,PYTHONUTF8='1')
            process=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
        RECORD.write_text(json.dumps({'pid':process.pid,'app':str(ROOT/'app.py'),'url':URL}),encoding='utf-8')
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('Не удалось запустить сервер. Подробности в data/server.log. Для переустановки библиотек используйте start.bat.')
            if healthy():
                if open_browser: webbrowser.open(URL)
                return 'started'
            time.sleep(.4)
        raise RuntimeError('Запуск занял больше минуты. Проверьте data/server.log и повторите запуск.')
    finally:
        if mutex:
            kernel.ReleaseMutex.argtypes=[ctypes.c_void_p]; kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            kernel.ReleaseMutex(mutex); kernel.CloseHandle(mutex)


def stop():
    record=load_record()
    if not owned_process(record):
        message('Фоновая программа уже остановлена.'); return
    result=subprocess.run(['taskkill.exe','/PID',str(int(record['pid'])),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError('Не удалось остановить сервер. Проверьте, запущен ли он под вашей учётной записью.')
    RECORD.unlink(missing_ok=True)
    message('Программа остановлена. Сохранённые данные остались в базе.')


def main():
    global PORT, URL
    parser=argparse.ArgumentParser(); parser.add_argument('--stop',action='store_true'); parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--address',default='127.0.0.1',choices=['127.0.0.1'])
    parser.add_argument('--port',default=8501,type=int,choices=[8501])
    args=parser.parse_args()
    PORT=args.port; URL=f'http://{args.address}:{PORT}'
    try:
        if args.stop: stop()
        else: start(not args.no_browser)
    except Exception as exc:
        DATA.mkdir(exist_ok=True)
        with (DATA/'launcher.log').open('a',encoding='utf-8') as log:
            import traceback; traceback.print_exc(file=log)
        message(str(exc),True)


if __name__=='__main__': main()
