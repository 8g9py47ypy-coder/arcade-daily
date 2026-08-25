@echo off
cd /d "%~dp0"
start "Daily Arcade server" /min python server.py
start "Daily Arcade" http://localhost:3000
