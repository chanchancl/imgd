
import os
import sys
import shutil
import traceback

from re import search
from infos import DownloadDir, IgnoredArtist, ArtistAlias
from pathlib import Path
from collections import defaultdict, deque
from utils import Ask, ExitInSeconds, NewFileLogger

ROOT_PATH = DownloadDir


cachedir = None
fileNameTemplate = "{0:04}"
# DEBUG_MODE = True
DEBUG_MODE = False

logger = NewFileLogger(__file__, DEBUG_MODE)

def Move(src, dst):
    if not DEBUG_MODE:
        try:
            shutil.move(src, dst)
        except Exception:
            print("*" * 80)
            print(f"Exception meet : can't move {src}, {dst} is exist")
            print("*" * 80)


def OrganizeFilesByFolder(target2Src: dict[str, list]):
    for targetFolder, srcPaths in target2Src.items():
        targetPath = Path(targetFolder)
        if not targetPath.exists():
            targetPath.mkdir()
        sortedSrcPaths = sorted(
            srcPaths, key=lambda path: os.stat(path).st_ctime_ns)
        for path in sortedSrcPaths:
            # move path to targetFolder
            logger.info(f"Move {path.name} to")
            Move(path, targetFolder)
        logger.info(f"\t{targetFolder}")


def HandleNewArtistFolders(noExistSaveFolder: dict[str, list]):
    if len(noExistSaveFolder.keys()) > 0:
        for path in noExistSaveFolder.keys():
            logger.info(f"New artist folder: {path.name}")
        logger.info(f"Some new artists detected. Create folders for them? ({len(noExistSaveFolder.keys())})")

        if Ask("y/N"):
            logger.info("Creating new folders and moving files.")
            OrganizeFilesByFolder(noExistSaveFolder)
        else:
            logger.info("No new folders created. No action taken.")


def MergeAlias(artist):
    for line in ArtistAlias:
        raw, aliasList = [x.strip() for x in line.split(":")]
        li = [x.strip() for x in aliasList.split(",") if x.strip() != ""]
        if artist in li:
            return raw
    return artist


# two types artist
# 1: [group(artist)]
# 2: [artist]
def FindArtist(who: Path) -> str:
    inputPath = who.name if isinstance(who, Path) else who

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
    inputPath = who.name if isinstance(who, Path) else who

    startIdx, endIdx = inputPath.find('[') + 1, inputPath.find(']')
    if startIdx == -1 or endIdx == -1 or startIdx >= endIdx:
        return ""

    inBrackets = inputPath[startIdx:endIdx]
    artist = inBrackets
    startIdInB, endIdInB = inBrackets.find('(') + 1, inBrackets.find(')')
    if startIdInB != -1 and endIdInB != -1:
        artist = inBrackets[startIdInB: endIdInB]

    if any(artist.find(ignored) != -1 for ignored in IgnoredArtist):
        remainingPath = inputPath[endIdx:]
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


def SplitBySaveFolder(path2artist) -> tuple[defaultdict[Path, list], defaultdict[Path, list]]:
    saveFolder2SrcPath = defaultdict(deque)
    noExistSaveFolder = defaultdict(deque)
    for rawPath, artist in path2artist.items():
        logger.info(f"Raw path: {rawPath}")
        logger.info(f"\tArtist: {artist}")
        saveFolder = FindSaveFolder(artist)
        logger.info(f"\tSave folder: {saveFolder}")
        if saveFolder:
            # artist already has one folder
            saveFolder2SrcPath[saveFolder].append(rawPath)
        else:
            # artist doesn't have a folder, create a new one
            newSaveFolder = Path(ROOT_PATH).joinpath(artist)
            noExistSaveFolder[newSaveFolder].append(rawPath)
    return saveFolder2SrcPath, noExistSaveFolder


def main():
    # if Ask(f"Do you know what you are doing?\n\tDEBUG_MODE = {DEBUG_MODE}\n(y/N)"):
    #    return

    if len(sys.argv) <= 1:
        logger.error("No input parameters provided. Please provide input paths.")
        exit(0)

    inputPaths = [Path(x) for x in sys.argv[1:]]
    inputPaths = sorted(inputPaths)

    path2Artist = {raw: artist for raw in inputPaths
                   if (artist := FindArtistV2(raw))}

    saveFolder, noExistSaveFolder = SplitBySaveFolder(path2Artist)

    OrganizeFilesByFolder(saveFolder)
    HandleNewArtistFolders(noExistSaveFolder)

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    ExitInSeconds(10)
