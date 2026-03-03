import schedule
import time
from collect_all import run_collection
from datetime import datetime

def job():
    print(f"\n{'='*50}")
    print(f"Scheduled collection started at {datetime.now()}")
    print(f"{'='*50}")
    run_collection()

# Schedule collections every 2 hours
schedule.every(2).hours.do(job)

print("Scheduler started. Collections every 2 hours")
print("Press Ctrl+C to stop")

while True:
    schedule.run_pending()
    time.sleep(60)
