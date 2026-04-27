
import traceback
import shutil
import subprocess
import zipfile
from sys import argv
from pathlib import Path

from utils import Ask, ExitInSeconds


def findRarFiles(directory: Path) -> list[Path]:
    rarFiles = []
    for f in directory.rglob("*.rar"):
        rarFiles.append(f)
    return sorted(rarFiles)


def extractRar(rarPath: Path, outputDir: Path) -> bool:
    outputDir.mkdir(exist_ok=True)
    try:
        subprocess.run(
            ["C:\\Program Files\\7-Zip\\7z.exe", "x", str(rarPath), f"-o{outputDir}", "-y"],
            capture_output=True, text=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        subprocess.run(
            ["C:\\Program Files\\WinRAR\\WinRAR.exe", "x", str(rarPath), str(outputDir), "-y"],
            capture_output=True, text=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return False


def convertRarToZip(rarPath: Path) -> Path | None:
    tempDir = rarPath.with_suffix("").with_name(rarPath.stem + "_temp")

    if not extractRar(rarPath, tempDir):
        print(f"  Error: Cannot extract {rarPath}. Please install 7-Zip or WinRAR.")
        return None

    zipPath = rarPath.with_suffix(".zip")

    with zipfile.ZipFile(zipPath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as zipObj:
        for file in tempDir.rglob("*"):
            if file.is_file():
                zipObj.write(file, file.relative_to(tempDir))

    shutil.rmtree(tempDir)
    return zipPath


def main():
    if len(argv) <= 1:
        print("Please provide a directory path as input")
        exit(0)

    inputDir = Path(argv[1])
    if not inputDir.exists() or not inputDir.is_dir():
        print(f"Error: {inputDir} is not a valid directory")
        exit(1)

    rarFiles = findRarFiles(inputDir)

    if not rarFiles:
        print("No .rar files found.")
        exit(0)

    print(f"Found {len(rarFiles)} .rar file(s):")
    for f in rarFiles:
        print(f"  {f}")

    if not Ask("Convert these files to .zip format?"):
        print("Aborted.")
        exit(0)

    for rarPath in rarFiles:
        print(f"Converting: {rarPath}")
        result = convertRarToZip(rarPath)
        if result:
            print(f"  -> {result}")
        else:
            print(f"  Failed!")

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    ExitInSeconds(10)
