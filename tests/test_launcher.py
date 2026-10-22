from pathlib import Path
import json
from unittest.mock import Mock
import launcher


def test_do_not_treat_foreign_pid_as_ours(monkeypatch):
    mocked=Mock(return_value=Mock(stdout='python.exe other_program.py'))
    monkeypatch.setattr(launcher.subprocess,'run',mocked)
    assert not launcher.owned_process({'pid':123,'app':str(launcher.ROOT/'app.py')})
    assert not launcher.owned_process({'pid':123,'app':'C:/another/app.py'})


def test_repeat_launch_reuses_existing_server(tmp_path,monkeypatch):
    monkeypatch.setattr(launcher,'DATA',tmp_path)
    monkeypatch.setattr(launcher,'load_record',lambda:{'pid':123,'app':str(launcher.ROOT/'app.py')})
    monkeypatch.setattr(launcher,'owned_process',lambda _:True)
    monkeypatch.setattr(launcher,'healthy',lambda:True)
    opened=Mock(); monkeypatch.setattr(launcher.webbrowser,'open',opened)
    popen=Mock(); monkeypatch.setattr(launcher.subprocess,'Popen',popen)
    assert launcher.start()=='reused'
    opened.assert_called_once_with(launcher.URL)
    popen.assert_not_called()


def test_corrupt_record_is_recoverable(tmp_path,monkeypatch):
    record=tmp_path/'server.json'; record.write_text('not json',encoding='utf-8')
    monkeypatch.setattr(launcher,'RECORD',record)
    assert launcher.load_record()=={}


def test_stop_foreign_process_never_kills(monkeypatch):
    monkeypatch.setattr(launcher,'load_record',lambda:{'pid':123})
    monkeypatch.setattr(launcher,'owned_process',lambda _:False)
    run=Mock(); monkeypatch.setattr(launcher.subprocess,'run',run)
    monkeypatch.setattr(launcher,'message',Mock())
    launcher.stop(); run.assert_not_called()
