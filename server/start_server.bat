@echo off
chcp 65001 >/dev/null
set PYTHONIOENCODING=utf-8
python -m uvicorn main:app --host 0.0.0.0 --port 8021
