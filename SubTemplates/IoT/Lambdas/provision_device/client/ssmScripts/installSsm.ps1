$code = $args[0]
$id = $args[1]
$region = $args[2]

$dir = $env:Temp + "\SSM"
$installerPath = $dir + "\AmazonSSMAgentSetup.exe"
$installerExists = Test-Path $installerPath -PathType leaf

New-Item -ItemType directory -Path $dir -Force
Set-Location $dir


if (-not $installerExists) {
    Write-Host Downloading SSM Agent...
    (New-Object System.Net.WebClient).DownloadFile("https://amazon-ssm-$region.s3.amazonaws.com/latest/windows_amd64/AmazonSSMAgentSetup.exe", $installerPath)
    Write-Host Download Complete
}
try {
    # SSM currently installed
    Get-Service -Name "AmazonSSMAgent" -ErrorAction Stop
    Write-Host SSM Agent Currently Active
    Write-Host Uninstall existing ssm agent
    Start-Process .\AmazonSSMAgentSetup.exe -ArgumentList @("/uninstall /quiet") -Wait
    Write-Host Uninstall Complete
}
catch {
    Write-Host SSM Agent Not Currently Active
}

Write-Host SSM Agent Install 
Start-Process .\AmazonSSMAgentSetup.exe -ArgumentList @("/q", "/log", "install.log", "CODE=$code", "ID=$id", "REGION=$region") -Wait
Get-Content ($env:ProgramData + "\Amazon\SSM\InstanceData\registration")
Get-Service -Name "AmazonSSMAgent"
Write-Host SSM Activation Complete