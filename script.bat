@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
)

call venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements.txt

python cv2_hack.py --video giraffe_clipped.mp4 --audio giraffe_clipped_audio.mp3

pause