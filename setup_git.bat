@echo off
cd /d "%~dp0"
echo Configurando identidad Git...
git config --global user.email "ericraftingz@gmail.com"
git config --global user.name "Erick Espina"
echo Limpiando git anterior...
if exist .git rmdir /s /q .git
echo Iniciando repositorio Git...
git init
git add .
git commit -m "OGGI primera version"
git branch -M main
git remote add origin https://github.com/ericraftingz-create/oggi-heladeria.git
echo.
echo Subiendo codigo a GitHub...
echo Si aparece una ventana del navegador para autenticarte, aceptala.
echo.
git push -u origin main --force
echo.
if %ERRORLEVEL%==0 (
    echo EXITO - Codigo subido a GitHub correctamente!
) else (
    echo ERROR - No se pudo subir. Revisa que tengas acceso a GitHub.
)
echo.
pause
