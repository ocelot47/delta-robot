#!/usr/bin/env python3
"""
main.py — Entry point của Delta Robot Control Center.
Chạy: python main.py
"""
from app import DeltaControlApp

if __name__ == "__main__":
    import multiprocessing as mp

    mp.freeze_support()
    app = DeltaControlApp()
    app.mainloop()
