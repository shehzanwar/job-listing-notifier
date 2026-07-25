@echo off
cd /d "S:\Projects\Job-Listing-Notifier"
"C:\Users\couga\AppData\Local\Programs\Python\Python312\python.exe" main_scraper.py >> logs\scraper_task.log 2>&1
