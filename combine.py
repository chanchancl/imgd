import traceback
from shutil import copy
from sys import argv
from pathlib import Path
from tempfile import TemporaryDirectory
from send2trash import send2trash

from zip import extract, package


def combineFolder(inputPath: Path, outputPath: Path, index):
    files: list[Path] = [file for file in inputPath.iterdir()]
    files.sort(key=lambda x: x.name)

    for file in files:
        fileExt = file.suffix.lstrip(".")
        if fileExt not in ["jpg", "png", "webp"]:
            continue
        newFileName = f"{index:04}.{fileExt}"
        newFilePath = outputPath.joinpath(newFileName)
        print(f"\tMove : {file}")
        print(f"\t  to : {newFilePath}")
        copy(file, newFilePath)
        index += 1
    return index


def combineFolders(inputPaths: list[Path], outputPath: Path):
    currentIndex = 1

    with TemporaryDirectory(dir=outputPath.parent) as tempDirName:
        tempDirPath = outputPath.parent.joinpath(tempDirName)
        print(f"Output : {tempDirPath}")
        for folder in inputPaths:
            copy(folder, tempDirPath)
        for zipFile in tempDirPath.iterdir():
            realPath = zipFile
            if zipFile.suffix == '.zip':
                realPath = extract(zipFile)
            print(f"Iterate : {realPath}")
            currentIndex = combineFolder(realPath, outputPath, currentIndex)
    package(outputPath)
    send2trash(outputPath)


def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(arg) for arg in argv[1:]]
    inputPaths.sort()

    print("Here are folder list :")
    for path in inputPaths:
        print(f"\t{path}")

    basePath = Path(inputPaths[0]).parent
    print(f"BasePath : {basePath}")

    print("\nPlease give output folder name")
    outputName = input()
    destPath = basePath.joinpath(outputName)

    if destPath.exists():
        print(f"Output path exists, will remove it, {destPath}")
        destPath.rmdir()

    destPath.mkdir()

    combineFolders(inputPaths, destPath)

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
        input()
    input()
