@echo off
REM ---------------------------------------------------------------------
REM  SWG-O build script
REM
REM  Run from the folder containing swgo.py.
REM    build.bat          normal windowed build
REM    build.bat debug    console build, so errors are visible
REM ---------------------------------------------------------------------

setlocal
set APPNAME=SWG-O

if /I "%~1"=="debug" (
    set WINDOWMODE=--console
    echo [debug build: console window enabled]
) else (
    set WINDOWMODE=--noconsole
)

echo.
echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist\%APPNAME% rmdir /s /q dist\%APPNAME%
if exist %APPNAME%.spec del %APPNAME%.spec

echo.
echo === Checking tools ===
py -m pip show pyinstaller >nul 2>&1 || py -m pip install pyinstaller
py -m pip show PySide6 >nul 2>&1 || py -m pip install PySide6

REM Do NOT uninstall PySide6-Addons to save space. It shares MSVC runtime DLLs
REM with PySide6-Essentials, and removing it breaks QtCore with
REM "DLL load failed while importing QtCore". If you want a smaller install,
REM uninstall all four PySide6 packages and install PySide6-Essentials alone.
REM PyInstaller's excludes below trim the build without touching the install.

echo.
echo === Building ===
REM Only Qt modules are excluded, and only at build time. Stdlib excludes
REM (email, http, xml, pydoc) save a few MB and break importlib.metadata,
REM which PySide6 reaches on startup. Not worth it.
py -m PyInstaller ^
  %WINDOWMODE% ^
  --onedir ^
  --clean ^
  --noconfirm ^
  --name "%APPNAME%" ^
  --icon swgo.ico ^
  --version-file version_info.txt ^
  --add-data "swgo.ico;." ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQuick3D ^
  --exclude-module PySide6.QtQuickWidgets ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtMultimedia ^
  --exclude-module PySide6.QtMultimediaWidgets ^
  --exclude-module PySide6.Qt3DCore ^
  --exclude-module PySide6.Qt3DRender ^
  --exclude-module PySide6.QtCharts ^
  --exclude-module PySide6.QtDataVisualization ^
  --exclude-module PySide6.QtOpenGL ^
  --exclude-module PySide6.QtOpenGLWidgets ^
  --exclude-module PySide6.QtSql ^
  --exclude-module PySide6.QtTest ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtPdfWidgets ^
  --exclude-module tkinter ^
  swgo.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED
    exit /b 1
)

echo.
echo === Result ===
if not exist "dist\%APPNAME%\%APPNAME%.exe" (
    echo ERROR: dist\%APPNAME%\%APPNAME%.exe was not produced.
    exit /b 1
)
echo Output folder: dist\%APPNAME%
REM No caret before the pipe: it sits inside double quotes, so cmd passes it
REM through untouched. Escaping it sends a literal ^ to PowerShell instead.
powershell -nop -c "$f = Get-ChildItem -Recurse -File 'dist\%APPNAME%'; 'Total size: {0:N0} MB across {1} files' -f (($f | Measure-Object Length -Sum).Sum/1MB), $f.Count" 2>nul
echo.
echo Test it now, before packaging:   dist\%APPNAME%\%APPNAME%.exe
echo.

where iscc >nul 2>&1
if errorlevel 1 (
    echo Inno Setup not on PATH. Open installer.iss in the Inno Setup Compiler
    echo and press Compile, or run it directly:
    echo   "C:\Program Files ^(x86^)\Inno Setup 6\ISCC.exe" installer.iss
    goto :done
)

echo Press any key to build the installer, or close this window to stop.
pause >nul
iscc installer.iss
if errorlevel 1 (
    echo.
    echo Installer compile FAILED.
    goto :done
)
echo.
echo Installer written to dist\

:done
echo.
echo Done.
endlocal
