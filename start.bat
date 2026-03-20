@REM uvicorn dataserver:app --host 0.0.0.0 --port 8353 --reload

@REM pythonw dataserver.py --bat


@echo off
if "%1"=="hide" goto HideRunning

mshta vbscript:createobject("wscript.shell").run("""%~0"" hide",0)(window.close)&&exit

:HideRunning
python "dataserver.py" --bat

exit