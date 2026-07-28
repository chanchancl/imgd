import os
import shutil
import sys
import traceback
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from re import search

from config import ArtistAlias, IgnoredArtist, SearchPathDir
from utils import Ask, ExitInSeconds, NewFileLogger

ROOT_PATH = SearchPathDir


cachedir = None
# DEBUG_MODE = True
DEBUG_MODE = False

logger = NewFileLogger(__file__, DEBUG_MODE)


def Move(src: Path, dst: Path) -> bool | None:
    if not DEBUG_MODE:
        try:
            shutil.move(str(src), str(dst))
            return True
        except (OSError, shutil.Error):
            return False
    return None


def Remove(dst: str) -> None:
    if not DEBUG_MODE:
        os.remove(dst)


def OrganizeFilesByFolder(target2Src: dict[Path, list[Path]]):
    faileds: list[tuple[Path, Path]] = []
    for targetFolder, srcPaths in target2Src.items():
        if not targetFolder.exists():
            targetFolder.mkdir(parents=True, exist_ok=True)
        sortedSrcPaths = sorted(srcPaths, key=lambda p: os.stat(p).st_ctime_ns)
        for path in sortedSrcPaths:
            logger.info(f"Move {path.name} to")
            if Move(path, targetFolder) is False:
                faileds.append((path, targetFolder))
        logger.info(f"\t{targetFolder}")

    if not faileds:
        return

    print("\n" + "*" * 79 + "\n")
    for src, dst in faileds:
        print(f"  {src.name}  ->  {dst}")
    if Ask("Above files exist in target, overwrite? (Y/n)"):
        for src, dst in faileds:
            target_file = dst / src.name
            Remove(str(target_file))
            if Move(src, dst) is False:
                logger.error(f"Failed to overwrite: {src.name} -> {dst}")


def HandleNewArtistFolders(new_folders: dict[Path, list[Path]]):
    if new_folders:
        for folder in new_folders:
            logger.info(f"New artist folder: {folder.name}")
        length = len(new_folders.keys())
        logger.info(f"Some new artists detected. Create folders for them? ({length})")

        if Ask("y/N"):
            logger.info("Creating new folders and moving files.")
            OrganizeFilesByFolder(new_folders)
        else:
            logger.info("No new folders created. No action taken.")


def MergeAlias(artist: str) -> str:
    for line in ArtistAlias:
        if ":" not in line:
            continue
        raw, _, aliasList = line.partition(":")
        raw = raw.strip()
        aliases = [x.strip() for x in aliasList.split(",") if x.strip()]
        if artist in aliases:
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
        remainingPath = inputPath[ret.end() :]
        # print(f"ignored found {inputPath}, end {ret.end()}, will find in {remainingPath}")
        return FindArtist(remainingPath)
    # print(f"{artist}")
    return artist.strip()


@lru_cache(maxsize=512)
def FindArtistV2(who: Path) -> str:
    name = who.name if isinstance(who, Path) else who

    # 定位最外层 [...]
    left = name.find("[")
    right = name.find("]", left + 1)
    if left == -1 or right == -1:
        return ""

    # 提取 [...] 内的内容，优先取 (...) 中的名字
    content = name[left + 1 : right]
    inner_left = content.find("(")
    if inner_left != -1:
        inner_right = content.find(")", inner_left)
        if inner_right != -1:
            artist = content[inner_left + 1 : inner_right]
        else:
            artist = content
    else:
        artist = content

    if any(ignored in artist for ignored in IgnoredArtist):
        return FindArtistV2(name[right + 1 :].strip())

    return artist.strip()


def FindSaveFolder(artist: str) -> Path | None:
    global cachedir
    if cachedir is None:
        cachedir = os.listdir(ROOT_PATH)

    artist = MergeAlias(artist)

    for dir_name in cachedir:
        # 精确匹配 "artist" 或 "artist (xxx)" 格式，避免 "abc" 误匹配 "abcdef"
        if dir_name == artist or dir_name.startswith(artist + " ("):
            return Path(ROOT_PATH) / dir_name
    return None


def SplitBySaveFolder(
    path2artist: dict[Path, str],
) -> tuple[defaultdict[Path, list], defaultdict[Path, list]]:
    saveFolder2SrcPath = defaultdict(list)
    new_folders = defaultdict(list)
    for rawPath, artist in path2artist.items():
        logger.debug(f"Raw path: {rawPath}")
        logger.debug(f"  Artist: {artist}")
        saveFolder = FindSaveFolder(artist)
        logger.debug(f"  Save folder: {saveFolder}")
        if saveFolder:
            # artist already has save folder
            saveFolder2SrcPath[saveFolder].append(rawPath)
        else:
            # new artist, create new folder
            newSaveFolder = Path(ROOT_PATH).joinpath(artist)
            new_folders[newSaveFolder].append(rawPath)
    return saveFolder2SrcPath, new_folders


def main():
    # if Ask(f"Do you know what you are doing?\n\tDEBUG_MODE = {DEBUG_MODE}\n(y/N)"):
    #    return

    if len(sys.argv) <= 1:
        logger.error("No input parameters provided. Please provide input paths.")
        sys.exit(1)

    inputPaths = [Path(x) for x in sys.argv[1:]]
    inputPaths = [x for x in inputPaths if x.suffix in [".zip", ".rar"]]
    inputPaths = sorted(inputPaths)

    path2Artist = {raw: artist for raw in inputPaths if (artist := FindArtistV2(raw))}

    saveFolder, new_folders = SplitBySaveFolder(path2Artist)

    OrganizeFilesByFolder(saveFolder)
    HandleNewArtistFolders(new_folders)

    print("Work Done!")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
    ExitInSeconds(10)
