
import os
import sys
import time
import shutil
import traceback

from re import search
from infos import DownloadDir, IgnoredArtist, ArtistAlias
from pathlib import Path
from collections import defaultdict
from utils import Ask

ROOT_PATH = DownloadDir
cachedir = None
fileNameTemplate = "{0:04}"
# DEBUG_MODE = True
DEBUG_MODE = False


def Move(src, dst):
    if not DEBUG_MODE:
        try:
            shutil.move(src, dst)
            print(f"Want move {src} to {dst}")
        except:
            print("*"*80)
            print(f"Exception meet : can't move {src}, {dst} is exist")
            print("*"*80)


def ProcessSaveFolder(target2Src:dict[str,list]):
    print("here")
    for targetFolder, srcPaths in target2Src.items():
         targetPath = Path(targetFolder)
         if not targetPath.exists():
             targetPath.mkdir()
         sortedSrcPaths = sorted(srcPaths, key= lambda path: os.stat(path).st_ctime_ns)
         for path in sortedSrcPaths:
            # move path to targetFolder
            print(f"Move {path.name} to\n\t{targetFolder}")
            Move(path, targetFolder)


def ProcessNoExistSaveFolder(noExistSaveFolder: dict[str, list]):
    if len(noExistSaveFolder.keys()) > 0:
        print(f"Some new artists, create folder for them? ({len(noExistSaveFolder.keys())})")
        for path in noExistSaveFolder.keys():
            print(f"\t{path.name}")
        print("y/N")

        if Ask():
            print("Create new folder and move")
            ProcessSaveFolder(noExistSaveFolder)
        else:
            print("Don't create new folder, no action")


def MergeAlias(artist):
    for line in ArtistAlias:
        raw, aliasList = [ x.strip() for x in line.split(":")]
        li = [ x.strip() for x in aliasList.split(",") if x.strip() != ""]
        if artist in li:
            return raw
    return artist


# two types artist
# 1: [group(artist)]
# 2: [artist]
def FindArtist(who: Path)-> str:
    inputPath = who
    if isinstance(who, Path):
        inputPath = who.name
    ret = search(r"\[(.*?)\]", inputPath)
    if not ret:
        # print(f"No [] found in path {inputPath}")
        return ""
    artistInnerQuote = search(r"\((.*?)\)", ret.group(1))
    artist = ""
    if artistInnerQuote:
        # [group(artist)]
        # print(f"\tWith artist quote {artistRet}")
        artist = artistInnerQuote.group(1)
    else:
        # [artist]
        # print(f"\tWithout quote")
        artist = ret.group(1)
    if any(artist.find(ignored) != -1 for ignored in IgnoredArtist):
        remainingPath = inputPath[ret.end():]
        # print(f"ignored found {inputPath}, end {ret.end()}, will find in {remainingPath}")
        return FindArtist(remainingPath)
    # print(f"{artist}")
    return artist.strip()

def FindArtistV2(who: Path) -> str:
    inputPath = who
    if isinstance(who, Path):
        inputPath = who.name
    starti, endi = inputPath.find('[')+1, inputPath.find(']')
    if any(x == -1 for x in [starti, endi]):
        return ""

    inBrackets = inputPath[starti:endi]
    artist = inBrackets
    startia, endia = inBrackets.find('(')+1, inBrackets.find(')')
    if all(x != -1 for x in [startia, endia]):
        artist = inBrackets[startia: endia]

    if any(artist.find(ignored) != -1 for ignored in IgnoredArtist):
        remainingPath = inputPath[endi:]
        # print(f"ignored found {inputPath}, end {endi}, will find in {remainingPath}")
        return FindArtistV2(remainingPath)
    return artist.strip()


def FindSaveFolder(artist: str) -> Path:
    global cachedir
    if cachedir is None:
        cachedir = os.listdir(ROOT_PATH)
    
    artist = MergeAlias(artist)

    for dir in cachedir:
        if dir.startswith(artist):
            return Path(ROOT_PATH).joinpath(dir)
    return None


def SplitBySaveFolder(path2artist) -> tuple[list, list]:
    saveFolder2SrcPath = defaultdict(list)
    noExistSaveFolder = defaultdict(list)
    for rawPath, artist in path2artist.items():
        print(rawPath)
        print("\t" + str(artist))
        saveFolder = FindSaveFolder(artist)
        print(f"\t\t {saveFolder}")
        if saveFolder is not None:
            # artist already have one folder
            saveFolder2SrcPath[saveFolder].append(rawPath)
        else:
            # artist doesn't have folder, create new one
            saveFolder = Path(ROOT_PATH).joinpath(artist)
            noExistSaveFolder[saveFolder].append(rawPath)
    return saveFolder2SrcPath, noExistSaveFolder


def main():
    # if Ask(f"Do you know what you are doing?\n\tDEBUG_MODE = {DEBUG_MODE}\n(y/N)"):
    #    return

    if len(sys.argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in sys.argv[1:] ]
    inputPaths = sorted(inputPaths)

    path2Artist = { raw: artist for raw in inputPaths
                   if (artist := FindArtistV2(raw))}

    saveFolder, noExistSaveFolder = SplitBySaveFolder(path2Artist)

    ProcessSaveFolder(saveFolder)
    ProcessNoExistSaveFolder(noExistSaveFolder)

    print("Work Done!")


def ExitInSeconds(seconds):
    for i in range(seconds):
        print(f"Will exist after {seconds-i} seconds")
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    ExitInSeconds(10)
