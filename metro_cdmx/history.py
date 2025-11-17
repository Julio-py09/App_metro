import csv
import os
from datetime import datetime

HISTORIAL_PATH = os.path.join(os.path.dirname(__file__), 'afluencia_historial.csv')

class HistoryLogger:
    def __init__(self, path=HISTORIAL_PATH):
        self.path = path
        self.header_written = os.path.exists(self.path)

    def log(self, state: dict):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row = {'timestamp': now}
        row.update(state)
        write_header = not os.path.exists(self.path)
        with open(self.path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def read_all(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path, 'r') as f:
            reader = csv.DictReader(f)
            return list(reader)
