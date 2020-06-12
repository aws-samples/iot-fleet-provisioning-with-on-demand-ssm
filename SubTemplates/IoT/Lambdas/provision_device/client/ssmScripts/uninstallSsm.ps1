$dir = $env:Temp + "\SSM"
Set-Location $dir
Start-Process .\AmazonSSMAgentSetup.exe -ArgumentList @("/uninstall /quiet") -Wait
Write-Host Uninstall Complete