' launch.vbs
' Target-side bootstrap for the control-channel connector.
'
' Responsibilities:
'   - Resolve the connector script path relative to this file's folder.
'   - Start the connector with a hidden window (no console flash on logon).
'   - Wait for it to exit, then re-launch after a short delay. This gives the
'     connector itself primary responsibility for reconnect, and treats
'     process-level crashes as a last-resort safety net.
'
' This script performs no TCP work of its own - VBScript has no reliable
' built-in for raw sockets. All network I/O lives in connector.py.

Option Explicit

Dim sh, fso, scriptDir, projectRoot, connectorPath, venvPython, pythonExe, cmd, restartDelayMs

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fso.GetParentFolderName(scriptDir)
connectorPath = fso.BuildPath(scriptDir, "connector.py")

' Prefer repo venv (has opencv/pygame/pycaw). Else PATH pythonw.exe.
venvPython = fso.BuildPath(projectRoot, "venv\Scripts\pythonw.exe")
If fso.FileExists(venvPython) Then
    pythonExe = """" & venvPython & """"
Else
    pythonExe = "pythonw.exe"
End If

restartDelayMs = 5000

Do
    cmd = """" & pythonExe & """ """ & connectorPath & """"
    ' 0 = hidden window, True = block until the process exits.
    sh.Run cmd, 0, True
    WScript.Sleep restartDelayMs
Loop
