import traceback
from pathlib import Path
from sys import argv
from zipfile import ZipFile

import pillow_avif  # noqa: F401 # make pillow support avif format
import send2trash
from PIL import Image

from utils import ExitInSeconds
from zip import extract, package

WantReplace = ".avif"
Target = ".jpg"
if Target == ".jpg":
    FORMAT = "JPEG"


def translateFormat(path: Path) -> Path:
    base = path.parent
    newDirName = f"new {path.name}"
    newBase = base.joinpath(newDirName)
    for x in Path(path).iterdir():
        if not x.name.endswith(WantReplace):
            # copy x to new dir
            newBase.mkdir(exist_ok=True)
            newFilePath = newBase.joinpath(x.name)
            x.rename(newFilePath)
            print(f"Move file : {x} to {newFilePath}")
            continue

        newPath = newBase.joinpath(Path(x.parts[-1]).with_suffix(Target))
        print(x)
        print(f"\t{newPath}")
        if not newPath.parent.exists():
            newPath.parent.mkdir(parents=True)
        with Image.open(x) as image:
            img = image.convert("RGB")
            img.save(newPath, FORMAT)
    send2trash.send2trash(path)
    Path(f"New : {newBase}")
    return newBase


def has_avif_in_zip(zip_path: Path) -> bool:
    with ZipFile(zip_path, "r") as zip_file:
        for file_name in zip_file.namelist():
            if file_name.endswith(WantReplace):
                return True
    return False


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
            if not has_avif_in_zip(path):
                print(f"Skip {path}, no avif in zip")
                continue
            output = Path(extract(path))
            path.rename(path.with_name(f"back {path.name}"))
        else:
            # handle single file
            if path.name.endswith(WantReplace):
                with Image.open(path) as image:
                    newPath = path.with_name(path.with_suffix(Target).name)
                    img = image.convert("RGB")
                    img.save(newPath, FORMAT)
            continue

        newPath = translateFormat(output)

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
