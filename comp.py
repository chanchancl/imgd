import traceback
from pathlib import Path
from sys import argv

import pillow_avif  # noqa: F401 # make pillow support avif format
import send2trash
from PIL import Image

from utils import ExitInSeconds
from zip import extract, package

WantReplace = ".avif"
Target = ".jpg"
if Target == ".jpg":
    FORMAT = "JPEG"


def compressFolder(path: Path) -> Path:
    base = path.parent
    newBase = base.joinpath(f"new {path.name}")
    for x in Path(path).iterdir():
        if x.suffix not in [".jpg", ".png", ".avif"]:
            newBase.mkdir(exist_ok=True)
            newFilePath = newBase.joinpath(x.name)
            x.rename(newFilePath)
            continue
        newPath = newBase.joinpath(Path(x.parts[-1]).with_suffix(Target))
        print(x)
        print(f"\t{newPath}")
        if not newPath.parent.exists():
            newPath.parent.mkdir(parents=True)
        with Image.open(x) as image:
            # img = image
            img = image.convert("RGB")
            # img.resize(map(int, [image.width * 0.6, image.height * 0.6]))
            img.save(newPath, FORMAT)
    send2trash.send2trash(path)
    Path(f"New : {newBase}")
    return newBase


def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths.sort()

    for path in inputPaths:
        inZIP = False
        output = path
        if path.name.endswith(".zip"):
            inZIP = True
            output = Path(extract(path))
            path.rename(path.with_name(f"back {path.name}"))

        newPath = compressFolder(output)

        newPath = newPath.rename(output)
        print(f"output : {output}")
        print(f"newPath : {newPath}")
        if inZIP:
            package(newPath)
            send2trash.send2trash(newPath)

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
    ExitInSeconds(10)
