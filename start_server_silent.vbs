Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\blackjack-pilot"
WshShell.Run "python -u server.py", 0, False

