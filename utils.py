
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
    for i in range(seconds):
        print(f"Will exist after {seconds - i} seconds")
        time.sleep(1)


def NewFileLogger(filePath: str, debug: bool = False) -> Logger:
    logFilePath = Path(filePath).with_suffix('.log').name

    logger = getLogger(filePath)
    logger.setLevel(DEBUG)

    fileFormatter = Formatter(
        '%(asctime)s | %(name)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    fileHandler = FileHandler(logFilePath, mode='a', encoding='utf-8')
    fileHandler.setLevel(INFO)
    fileHandler.setFormatter(fileFormatter)

    # Custom formatter to log raw messages without additional formatting in console
    class RawMessageFormatter(Formatter):
        def format(self, record):
            return record.getMessage()

    consleHandler = StreamHandler(sys.stdout)
    consleHandler.setLevel(DEBUG if debug else INFO)
    consleHandler.setFormatter(RawMessageFormatter())

    logger.addHandler(fileHandler)
    logger.addHandler(consleHandler)

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
