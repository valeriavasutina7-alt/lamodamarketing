@echo off
rem === Task Scheduler: Lamoda avto-prostanovka cen na novye gotovye modeli ===
rem Skan gotovnosti (foto + net prodazhnoy ceny) -> COGS iz data-lake -> cena po X=2.6 ->
rem zapis big+prodazhnaya, otchyot v temu 1826 tolko kogda chto-to prostavili.
rem Dannye/log - v lamodamarketing\data\. Python venv i datalake - iz wb-ad-agents.
rem Kommentarii ASCII: cmd chitaet fayl v OEM-kodirovke.
set "LAMODA_ROOT=C:\Users\yablonskaya.o.n\Desktop\Cursor\lamodamarketing"
set "WB_AGENTS_ROOT=C:\Users\yablonskaya.o.n\Desktop\reznikowaol\wb-ad-agents"
cd /d "%LAMODA_ROOT%"
echo ==== %date% %time% start ==== >> data\_sched_auto_pricer.log
"%WB_AGENTS_ROOT%\portal\.venv\Scripts\python.exe" scripts\auto_pricer.py --apply --notify >> data\_sched_auto_pricer.log 2>&1
echo ==== %date% %time% exit %errorlevel% ==== >> data\_sched_auto_pricer.log
