import traceback
from os import utime
from pathlib import Path
from pprint import pprint
from sys import argv
from time import sleep, time

fileNameTemplate = "{0:04}"


def RefreshFolder(inputPaths: list[Path]):
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
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
    # input()
