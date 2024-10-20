
import os
import sys
import time
import shutil
import traceback
from re import search
from infos import DownloadDir, IgnoredArtist, ArtistAlias
from pathlib import Path, WindowsPath
from collections import defaultdict
from pprint import pprint

ROOT_PATH = DownloadDir
cachedir = None

fileNameTemplate = "{0:04}"

# DEBUG_MODE = True
DEBUG_MODE = False

def Ask():
    ans = input().strip()
    if ans == "" or ans not in "yY":
        return False
    return True


def Move(src, dst):
    if not DEBUG_MODE:
        try:
            shutil.move(src, dst)
            print(f"Want move {src} to {dst}")
        except:
            print("*"*80)
            print(f"Exception meet : can't move {src}, {dst} is exist")
            print("*"*80)


def ProcessTarget2Raw(target2Src:dict[str,list]):
    for targetFolder, srcPaths in target2Src.items():
         targetPath = Path(targetFolder)
         if not targetPath.exists():
             targetPath.mkdir()
         sortedSrcPaths = sorted(srcPaths, key= lambda path: os.stat(path).st_ctime_ns)
         for path in sortedSrcPaths:
            # move path to targetFolder
            print(f"Move {path.name} to\n\t{targetFolder}")
            Move(path, targetFolder)


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
def FindArtist(who)-> str:
    inputPath = who
    if type(who) is WindowsPath:
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

    if any(artist == ignored for ignored in IgnoredArtist):
        remainingPath = inputPath[ret.end():]
        # print(f"ignored found {inputPath}, end {ret.end()}, will find in {remainingPath}")
        return FindArtist(remainingPath)
    # print(f"{artist}")
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


def main():
    #print("Do you know what you are doing?")
    #print(f"\t DEBUG_MODE = {DEBUG_MODE}")
    #print("(y/N)")
    #ans = input()
    #if ans.strip() == "" or ans.strip() not in "yY":
    #    return

    if len(sys.argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in sys.argv[1:] ]
    inputPaths = sorted(inputPaths)
    # pprint(inputPaths)

    # c:\[abc]hello\ : abc
    path2artist = {}
    for x in inputPaths:
        if ret := FindArtist(x):
            path2artist[x] = ret

    targetFolder2SrcPath = defaultdict(list)
    NoTargetFolder2SrcPath = defaultdict(list)
    for rawPath, artist in path2artist.items():
        print(rawPath)
        print("\t" + str(artist))
        saveFolder = FindSaveFolder(artist)
        print(f"\t\t {saveFolder}")
        if saveFolder is not None:
            targetFolder2SrcPath[saveFolder].append(rawPath)
        else:
            # artist doesn't have save folder, create new one
            saveFolder = Path(ROOT_PATH).joinpath(artist)
            NoTargetFolder2SrcPath[saveFolder].append(rawPath)

    ProcessTarget2Raw(targetFolder2SrcPath)

    if len(NoTargetFolder2SrcPath.keys()) > 0:
        print(f"Some new artists, create folder for them? ({len(NoTargetFolder2SrcPath.keys())})")
        for path in NoTargetFolder2SrcPath.keys():
            print(f"\t{path.name}")
        print("y/N")

        if Ask():
            print("Create new folder and move")
            ProcessTarget2Raw(NoTargetFolder2SrcPath)
        else:
            print("Don't create new folder, no action")
        
    print("Work Done!")


def Test():
    for it in os.listdir(ROOT_PATH):
        ret = FindArtist(it)
        if ret != "":
            pass
            print(it)
            print(f"\t{ret}")
            print(f"\t\t{FindSaveFolder(ret)}")


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
