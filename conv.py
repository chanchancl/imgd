import os
import sys
import traceback
from sys import argv
from pathlib import Path
from pprint import pprint
from PIL import Image
import pillow_avif # make pillow support avif format

WantReplace = ".avif"
Target      = '.jpg'

def translateFormat(p: Path):
    base = p.parent
    for x in Path(p).iterdir():
        if not x.name.endswith("avif"):
            continue
        newPath = Path(base, f"New {x.parts[-2]}", Path(x.parts[-1]).with_suffix(Target))
        print(x)
        print(f'\t{newPath}')
        if not newPath.parent.exists():
            newPath.parent.mkdir(parents=True)
        with Image.open(x) as image:
            img = image.convert("RGB")
            img.save(newPath, 'JPEG')

def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths.sort()

    for path in inputPaths:
        translateFormat(path)

    print("Work Done!")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
