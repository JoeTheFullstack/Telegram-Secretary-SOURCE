#requires -Version 5.1
<#
Install Stage 3.4 (property search and Telegram media display).

Run this script from the Telegram-Secretary-SOURCE-GIT folder after:
    git pull origin stage-3.4-property-search

The target defaults to the known live project folder. You can override it:
    .\Install-Stage-3.4.ps1 -TargetPath "D:\MyBot\Telegram-Secretary"

This installer replaces only the nine Stage 3.4 source/test files. It does not
touch config, data, database files, migrations, or the running Python process.
A dated backup is created in the target project's backups folder first.
#>
[CmdletBinding()]
param(
    [string]$TargetPath = "C:\Users\NooraGP\Downloads\Telegram-Secretary-v2\Telegram-Secretary"
)

$ErrorActionPreference = "Stop"
$SourceRoot = $PSScriptRoot

$RelativeFiles = @(
    "app\core\customer_flow.py",
    "app\main.py",
    "app\adapters\telegram.py",
    "app\repositories\properties.py",
    "app\services\property_service.py",
    "app\core\permissions.py",
    "app\core\router.py",
    "app\core\property_search.py",
    "tests\test_property_search.py"
)

$TargetPath = [System.IO.Path]::GetFullPath($TargetPath)
if (!(Test-Path -LiteralPath (Join-Path $TargetPath "app\main.py"))) {
    throw "پوشه پروژه مقصد معتبر نیست یا app\main.py در آن وجود ندارد: $TargetPath"
}
if (!(Test-Path -LiteralPath (Join-Path $TargetPath "tests"))) {
    throw "پوشه tests در پروژه مقصد پیدا نشد."
}

foreach ($relative in $RelativeFiles) {
    $source = Join-Path $SourceRoot $relative
    if (!(Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "فایل منبع بسته پیدا نشد: $relative. مطمئن شو روی شاخه stage-3.4-property-search هستی و git pull انجام شده است."
    }
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupRoot = Join-Path $TargetPath ("backups\stage_3_4_before_install_" + $stamp)
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$HadOriginal = @{}
foreach ($relative in $RelativeFiles) {
    $target = Join-Path $TargetPath $relative
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        $backupFile = Join-Path $BackupRoot $relative
        $backupDir = Split-Path -Parent $backupFile
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination $backupFile -Force
        $HadOriginal[$relative] = $true
    } else {
        $HadOriginal[$relative] = $false
    }
}

try {
    foreach ($relative in $RelativeFiles) {
        $source = Join-Path $SourceRoot $relative
        $target = Join-Path $TargetPath $relative
        $targetDir = Split-Path -Parent $target
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
        Write-Host ("Installed: " + $relative) -ForegroundColor Green
    }
}
catch {
    Write-Warning "نصب کامل نشد؛ بازگردانی فایل‌های قبلی آغاز می‌شود."
    foreach ($relative in $RelativeFiles) {
        $target = Join-Path $TargetPath $relative
        if ($HadOriginal[$relative]) {
            $backupFile = Join-Path $BackupRoot $relative
            if (Test-Path -LiteralPath $backupFile) {
                Copy-Item -LiteralPath $backupFile -Destination $target -Force
            }
        } elseif (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
    }
    throw
}

Write-Host ""
Write-Host "Stage 3.4 installed successfully." -ForegroundColor Green
Write-Host ("Project: " + $TargetPath)
Write-Host ("Backup:  " + $BackupRoot)
Write-Host "No database migration was required. Config and data files were not changed."
