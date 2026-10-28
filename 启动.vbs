' ============================================================
'  Enterprise Credit Shot - launcher (NO console window)
'  Double-click this file to start the GUI silently.
'  All Chinese messages are handled by the Python app itself.
' ============================================================
Option Explicit

Dim shell, fso, base, pyRoot, pyDir, best, cmd, launcher, known
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = base & "\launcher.pyw"

If Not fso.FileExists(launcher) Then
    MsgBox "launcher.pyw not found next to this script:" & vbCrLf & launcher, 48, "Credit Shot"
    WScript.Quit 1
End If

best = ""

' 1) known install path
known = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\pythonw.exe"
If fso.FileExists(known) Then best = known

' 2) scan every python version folder
If best = "" Then
    pyRoot = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
    If fso.FolderExists(pyRoot) Then
        For Each pyDir In fso.GetFolder(pyRoot).SubFolders
            If fso.FileExists(pyDir.Path & "\pythonw.exe") Then
                best = pyDir.Path & "\pythonw.exe"
                Exit For
            End If
        Next
    End If
End If

' 3) fall back to PATH
If best = "" Then
    Dim shExec
    Set shExec = shell.Exec("where pythonw.exe")
    If Not shExec.StdOut.AtEndOfStream Then
        Dim line1
        line1 = Trim(shExec.StdOut.ReadLine())
        If line1 <> "" Then best = line1
    End If
End If

If best = "" Then
    MsgBox "Python (pythonw.exe) was not found." & vbCrLf & vbCrLf & _
           "Please run the .bat launcher in this folder to install" & vbCrLf & _
           "the dependencies first.", 48, "Credit Shot"
    WScript.Quit 1
End If

cmd = """" & best & """ """ & launcher & """"
' 0 = hidden window, False = do not wait
shell.Run cmd, 0, False
