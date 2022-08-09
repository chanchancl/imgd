from sys import argv
from pathlib import Path
import traceback
import winshell

from infos import LinkPath

def LinkTo(src: Path, destDir: Path):
    print(src.stem)
    stem = src.stem

    destDir = destDir.joinpath(stem + ".lnk")
    print(src, destDir)
    winshell.CreateShortcut(
        Path=str(destDir),
        Target=str(src),
    )

def main():
    inputPaths = [Path(x) for x in argv[1:]]
    dest = Path(LinkPath)
    for path in inputPaths:
        LinkTo(path, dest)

    print("Work Done!")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    # input()
