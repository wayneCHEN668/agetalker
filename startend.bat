@echo off
echo Starting AgeTalker Backend Service...
cd backend
call .venv\Scripts\activate
python -m uvicorn main:app --reload --port 8050
pause
