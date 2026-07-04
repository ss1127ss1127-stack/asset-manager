# 資産管理ダッシュボードを起動するヘルパー。
# Python の Scripts フォルダが PATH に無いため、python.exe をフルパスで呼ぶ。
$ErrorActionPreference = "Stop"
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$env:PYTHONUTF8 = "1"
Set-Location -Path $PSScriptRoot
& $py -m streamlit run app.py
