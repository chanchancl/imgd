
import os
import zipfile
import traceback
from pathlib import Path
from sys import argv

from utils import ExitInSeconds

# p ： 一个文件夹
# 将文件夹p压缩为 zip 压缩包
def package(p: Path):
    zipFilePath = p.with_suffix(".zip")
    if zipFilePath.exists():
        print(f"\tFile exists : {zipFilePath}")
        return

    with zipfile.ZipFile(zipFilePath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as zipObj:
        for file in p.rglob('*'):
            zipObj.write(file, file.relative_to(p.parent))
    atime = p.stat().st_atime
    mtime = p.stat().st_mtime

    os.utime(zipFilePath, (atime, mtime))

# p : 一个zip压缩包
# 如果p的根目录是许多文件，则将其解压缩到一个文件夹中
# 如果p的根目录只有一个文件夹，则将这个文件夹解压缩
def extract(p: Path) -> Path:
    if p.suffix != ".zip":
        raise ValueError("Provided path is not a zip file")

    output_dir = ""
    with zipfile.ZipFile(p, "r") as zipObj:
        allFiles = zipObj.namelist()
        rootItemsSet = {Path(f).parts[0] for f in allFiles}
        if len(rootItemsSet) == 1:
            # only have one folder there
            output_dir = Path(p.parent, rootItemsSet.pop())
            zipObj.extractall(p.parent)
        else:
            # have many files there
            output_dir = p.with_name(p.stem.strip())
            output_dir.mkdir(exist_ok=True)
            zipObj.extractall(output_dir)
    return output_dir


def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths.sort(key=lambda x: x.stat().st_mtime)

    for path in inputPaths:
        print(f"Working on : {path}")
        if path.suffix == '.zip':
            print("Extracting...")
            extract(path)
        else:
            print("Packaging...")
            package(path)

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    ExitInSeconds(10)
