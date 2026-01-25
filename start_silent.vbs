Set WshShell = CreateObject("WScript.Shell")
strPath = WshShell.CurrentDirectory
' Run the batch file invisibly (0) and don't wait for it to finish (False)
WshShell.Run chr(34) & strPath & "\run.bat" & chr(34), 0, False
Set WshShell = Nothing
