
import os
import traceback
import send2trash
from shutil import copy, rmtree
from sys import argv
from pathlib import Path
from pprint import pprint

from zip import extract, package
from autoclassfiy import Ask

fileNameTemplate = "{0:04}"

def splitFileName(x: Path):
    #if " " in str(x.name):
    #    return str(x.name).split()[-1]
    # print(x.name)
    return x.name

def CombineFolder(inputPath: Path, outputPath: Path, index):
    files: list[Path] = [x for x in inputPath.iterdir()]
    files.sort(key=splitFileName)

    for file in files:
        fileExt = file.suffix.rsplit(".", 1)[-1]
        if fileExt not in ["jpg", "png", "webp"]:
            continue
        newFileName = fileNameTemplate.format(index) + f".{fileExt}"
        newFilePath = outputPath.joinpath(newFileName)
        print(f"\tMove : {file}")
        print(f"\t  to : {newFilePath}")
        copy(file, newFilePath)
        index += 1
    return index


def CombineFolders(inputPaths: list[Path], output: Path):
    currentItem = 1
    rmDirs = []
    for dir in inputPaths:
        realPath = dir
        if dir.suffix == '.zip':
            extract(dir)
            realPath = dir.with_suffix("")
        print(f"Iterate : {realPath}")
        currentItem = CombineFolder(realPath, output, currentItem)
        rmDirs.append(realPath)
    package(output)
    rmDirs.append(output)
    pprint(rmDirs)
    send2trash.send2trash(rmDirs)

def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths.sort()

    print("Here are folder list :")
    for path in inputPaths:
        print(f"\t{path}")

    basePath = Path(inputPaths[0]).parent
    print(f"BasePath : {basePath}")
    print("\nPlease input output folder name")

    outputName = input()
    destPath = basePath.joinpath(outputName)

    if destPath.exists():
        print(f"Output path is exists, will remove it, {destPath}")
        destPath.rmdir()

    destPath.mkdir()

    CombineFolders(inputPaths, destPath)

    print("Work Done!")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        input()
    input()
