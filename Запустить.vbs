Option Explicit
Dim shell, fso, folder, python, script
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
python = folder & "\.venv\Scripts\pythonw.exe"
script = folder & "\launcher.py"
If Not fso.FileExists(python) Then
  MsgBox "Please run start.bat once to install Python dependencies.", 48, "Payroll"
Else
  shell.CurrentDirectory = folder
  shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & script & Chr(34), 0, False
End If
