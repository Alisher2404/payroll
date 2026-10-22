Option Explicit
Dim shell, fso, folder, python
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
python = folder & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(python) Then
  shell.CurrentDirectory = folder
  shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & folder & "\launcher.py" & Chr(34) & " --stop", 0, False
End If
