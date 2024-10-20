
import zipfile
import traceback
from pathlib import Path
from sys import argv
from pprint import pprint


def package(p: Path):
    zipFilePath = p.with_suffix(".zip")
    if zipFilePath.exists():
        print(f"\tFile exists : {zipFilePath}")
    with zipfile.ZipFile(zipFilePath, "w") as zipObj:
        for file in p.rglob('*'):
            zipObj.write(file, file.relative_to(p.parent))

def extract(p: Path):
    if p.suffix != ".zip":
        raise ValueError("Provided path is not a zip file")
    
    with zipfile.ZipFile(p, "r") as zipObj:
        all_files = zipObj.namelist()
        root_items = { Path(f).parts[0] for f in all_files }
        if len(root_items) == 1:
            print(p.parent)
            zipObj.extractall(p.parent)
        else:
            output_dir = p.with_suffix("")
            output_dir.mkdir(exist_ok=True)
            zipObj.extractall(output_dir)

def main():
    if len(argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in argv[1:]]
    inputPaths.sort()

    for path in inputPaths:
        print(f"Working on : {path}")
        if path.suffix == '.zip':
            extract(path)
        else:
            package(path)

    print("Work Done!")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    input()
