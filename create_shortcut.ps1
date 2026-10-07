$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = $shell.CreateShortcut("$desktop\Joule Widget.lnk")
$lnk.TargetPath = "C:\Program Files\Python314\pythonw.exe"
$lnk.Arguments = '"C:\mydata\JD\Joulewarehouse\floating_icon.pyw"'
$lnk.Hotkey = "CTRL+SHIFT+J"
$lnk.WindowStyle = 7
$lnk.Description = "SAP Joule floating chat widget"
$lnk.Save()
Write-Host "Shortcut created on Desktop"
