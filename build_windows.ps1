$ErrorActionPreference = "Stop"

python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --noconsole --onefile --name ArtPracticeJournal main.py

Write-Host "Built dist\ArtPracticeJournal.exe"
