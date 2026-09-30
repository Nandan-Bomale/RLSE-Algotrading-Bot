@echo off
echo Stopping RLSE Algotrading Bot...
powershell -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo Bot and Terminal stopped!
