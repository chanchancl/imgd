
import traceback
from sys import argv
from pathlib import Path
from datetime import datetime
from os import environ
from wcwidth import wcswidth

OUTPUT_PATH = "TRENDING_PATH"

def main():
    now = datetime.now()
    timeStr = now.strftime("%Y-%m-%d %H:%M:%S")

    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths.sort()

    outputPath = environ[OUTPUT_PATH]

    with open(outputPath, "a", encoding="utf-8") as f:
        f.write(f"\n{timeStr} Trending:\n")
        maxLen = -1
        buffers = []
        for path in inputPaths:
            print(path.name)
            try:
                name, tags = path.name.split(" ", 1)
            except Exception:
                name = path.name
                tags = ""
            print(name, wcswidth(name))
            maxLen = max(maxLen, wcswidth(name))
            buffers.append([name, tags])
        print(maxLen)
        for buffer in buffers:
            print(buffer[0], maxLen, maxLen - wcswidth(buffer[0]))
            space = " " * (maxLen - wcswidth(buffer[0]) + 1)
            f.write(f"  {buffer[0]}{space}{buffer[1]}\n")

    print("Work Done!")


def readenv():
    with open(".env", "r") as f:
        for line in [x for x in f.readlines() if x.strip() != ""]:
            key, value = line.split()
            environ[key] = value


if __name__ == "__main__":
    try:
        readenv()
        main()
    except Exception:
        print(traceback.format_exc())
        input()
    input()
