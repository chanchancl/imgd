
from sys import argv
from pathlib import Path
import traceback
from typing import List

fileNameTemplate = "{0:04}"

def RefreshFolder(inputPaths: List[Path]):
    for dir in inputPaths:
        if dir.is_dir():
            dest = dir.joinpath("tmptest")
            dest.mkdir(exist_ok=True)
            dest.rmdir()
            print(f"Done on {dir}")

def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]

    RefreshFolder(inputPaths)

    print("Work Done!")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    input()
