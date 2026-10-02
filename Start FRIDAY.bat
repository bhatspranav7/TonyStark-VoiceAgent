@echo off
rem Double-click to start FRIDAY: tool server, voice agent and the HUD in your browser.
rem Close this window to stop her.
title F.R.I.D.A.Y.
cd /d "%~dp0"
uv run friday
echo.
pause
