@echo off
echo Stopping RLSE Algotrading Bot...
taskkill /FI "WINDOWTITLE eq Administrator:  RLSE Algotrading Bot*" /F /T > nul 2>&1
taskkill /FI "WINDOWTITLE eq RLSE Algotrading Bot*" /F /T > nul 2>&1
echo Bot stopped!
