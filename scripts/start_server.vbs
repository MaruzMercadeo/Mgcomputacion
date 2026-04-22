' Wrapper que lanza start_server.bat sin mostrar ventana de consola.
' Usa esto en el startup folder de Windows.

Dim shell, fso, scriptDir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 0 = ventana oculta, False = no esperar que termine
shell.Run Chr(34) & scriptDir & "\start_server.bat" & Chr(34), 0, False
