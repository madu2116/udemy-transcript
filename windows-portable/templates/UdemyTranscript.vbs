' UdemyTranscript.vbs - Double-click de chay ung dung (KHONG hien cua so console).
' Muon xem log: mo file app.log, hoac chay start.bat (che do debug co console).
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run """" & dir & "\runtime\pythonw.exe"" """ & dir & "\launcher.py""", 0, False
