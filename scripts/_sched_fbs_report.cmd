@echo off
rem === Task Scheduler: Lamoda FBS svodka (LARETTO, read-only) ===
rem Gonit fbs.py --html -> shlyot HTML v Telegram (ReportOnly, russkaya podpis).
rem Dannye/log - v lamodamarketing\data\. Otchyot idyot v temu 1826 gruppy "Agenty Olesya".
rem Kommentarii ASCII: cmd chitaet fayl v OEM-kodirovke.
set "LAMODA_ROOT=C:\Users\yablonskaya.o.n\Desktop\Cursor\lamodamarketing"
set "WB_AGENTS_ROOT=C:\Users\yablonskaya.o.n\Desktop\reznikowaol\wb-ad-agents"
cd /d "%LAMODA_ROOT%"
echo ==== %date% %time% start ==== >> data\_sched_fbs_report.log
"%WB_AGENTS_ROOT%\portal\.venv\Scripts\python.exe" scripts\fbs.py --html >> data\_sched_fbs_report.log 2>&1
set RC=%errorlevel%
echo ==== %date% %time% exit %RC% ==== >> data\_sched_fbs_report.log
powershell -NoProfile -ExecutionPolicy Bypass -File "%WB_AGENTS_ROOT%\scripts\notify_telegram.ps1" -Title lamoda-fbs -Status %RC% -ReportOnly -AttachGlob "data\fbs_report_*.html" -ChatId "-1003797610374" -ThreadId 1826 >> data\_sched_fbs_report.log 2>&1
