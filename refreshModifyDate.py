
import traceback

from os import utime
from sys import argv
from pathlib import Path
from pprint import pprint
from time import sleep, time
from typing import List


fileNameTemplate = "{0:04}"


def RefreshFolder(inputPaths: List[Path]):
    for destPath in inputPaths:
        currentTimestamp = time()
        utime(destPath, (currentTimestamp, currentTimestamp))
        print("Success to refresh time")
        sleep(0.1)


def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths = sorted(inputPaths)
    pprint(inputPaths)

    RefreshFolder(inputPaths)

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    # input()
