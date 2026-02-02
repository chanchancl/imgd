
import sys
import time
from pathlib import Path
from logging import Logger, getLogger, StreamHandler, FileHandler, Formatter, INFO, DEBUG

def BuildHeaderFromStr(s: dict):
    headers = {}
    lines = s.split("\n")
    for line in lines:
        if line == "":
            continue
        parts = line.split(": ")
        if parts is None or len(parts) < 2:
            continue
        headers[parts[0]] = parts[1]
    return headers


def Ask(prompt=""):
    if prompt != "":
        print(prompt)
    ans = input().strip()
    if ans == "" or ans not in ".yY":
        return False
    return True


def ExitInSeconds(seconds=10):
    try:
        import keyboard
    except ImportError:
        print("Warning: 'keyboard' library not installed. Run: pip install keyboard")
        for i in range(seconds):
            print(f"Will exit after {seconds - i} seconds")
            time.sleep(1)
        return

    esc_pressed = False

    def on_esc(event):
        nonlocal esc_pressed
        esc_pressed = True

    keyboard.on_press_key('esc', on_esc)

    try:
        for i in range(seconds):
            print(f"Will exit after {seconds - i} seconds")
            time.sleep(1)
            if esc_pressed:
                print("ESC pressed, exiting...")
                break
    finally:
        keyboard.remove_hotkey('esc')


def NewFileLogger(filePath: str, debug: bool = False) -> Logger:
    logFilePath = Path(filePath).with_suffix('.log').name

    logger = getLogger(filePath)
    logger.setLevel(DEBUG)

    fileFormatter = Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    fileHandler = FileHandler(logFilePath, mode='a', encoding='utf-8')
    fileHandler.setLevel(INFO)
    fileHandler.setFormatter(fileFormatter)

    # Custom formatter to log raw messages without additional formatting in console
    class RawMessageFormatter(Formatter):
        def format(self, record):
            return record.getMessage()
    consoleFormatter = Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    consoleHandler = StreamHandler(sys.stdout)
    consoleHandler.setLevel(DEBUG if debug else INFO)
    consoleHandler.setFormatter(consoleFormatter)
    # consleHandler.setFormatter(RawMessageFormatter())

    logger.addHandler(fileHandler)
    logger.addHandler(consoleHandler)

    return logger

def TestLogger():
    logger = NewFileLogger(__file__, True)
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")

if __name__ == "__main__":
    TestLogger()
