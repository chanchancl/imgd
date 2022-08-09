
from shutil import copy
from sys import argv
from pathlib import Path
import traceback

fileNameTemplate = "{0:04}"

def CombineFolder(inputPath: Path, outputPath: Path, index):
    files: list[Path] = [x for x in inputPath.iterdir()]
    files.sort()

    for file in files:
        fileExt = file.suffix.rsplit(".", 1)[-1]
        newFileName = fileNameTemplate.format(index) + f".{fileExt}"
        newFilePath = outputPath.joinpath(newFileName)
        copy(file, newFilePath)
        print(f"\tMove : {file}")
        print(f"\t  to : {newFilePath}")
        index += 1
    return index


def CombineFolders(inputPaths, output):
    currentItem = 1
    for dir in inputPaths:
        print(f"Iterate : {dir}")
        currentItem = CombineFolder(dir, output, currentItem)

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
