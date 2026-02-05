import os
import sys
import traceback

from infos import IgnoredArtist
from pathlib import Path
from utils import Ask, ExitInSeconds, NewFileLogger

_DEBUG = True

RemoveGroup = False
logger = NewFileLogger(__file__, _DEBUG)

commonArtist = ""

def FindArtistStartIndex(who: str | Path) -> str:
    inputPath = who.name if isinstance(who, Path) else who
    startId, endId = inputPath.find('['), inputPath.find(']')
    if startId == -1 or endId == -1 or startId >= endId:
        return -1, ""

    inBrackets = inputPath[startId + 1:endId]
    artist = inBrackets
    if RemoveGroup:
        startIdInB, endIdInB = inBrackets.find('(') + 1, inBrackets.find(')')
        if startIdInB != -1 and endIdInB != -1:
            artist = inBrackets[startIdInB: endIdInB].strip()

    if any(ignored in artist for ignored in IgnoredArtist):
        remainingPath = inputPath[endId + 1:]  # no strip !!!!!!!
        nextStartId, newArtist = FindArtistStartIndex(remainingPath)
        logger.debug(f"Remaining {remainingPath}, {inputPath[endId + nextStartId + 1:]}, {nextStartId}, {endId}")
        return endId + nextStartId + 1, newArtist
    return startId, artist


def FormatName(path: str | Path) -> str:
    global commonArtist
    path: Path = path if isinstance(path, Path) else Path(path)
    filename = path.name

    logger.debug(f"input : {path}")

    startIdx, artist = FindArtistStartIndex(filename)
    if startIdx == -1 and artist == "":
        if commonArtist == "":
            logger.warning(f"No artist found in {filename}")
            if not Ask("Want common artist?"):
                return ""
            commonArtist = input("Please input common artist")
        artist = commonArtist
        startIdx = 0

    logger.debug(f"artist path : {filename[startIdx:]}")
    # dotIdx = name.rfind('.')
    # extIdx = dotIdx if dotIdx != -1 else len(name)
    # ext = name[extIdx:] if dotIdx != -1 else ""
    # (a) [b] [artist] c [d].e
    #
    prefix = filename[:startIdx].strip()
    ext = ""
    if not path.is_dir():
        ext = path.suffix
    core_with_artist = filename[startIdx:len(filename) - len(ext)].strip()
    core_without_artist = core_with_artist[core_with_artist.find(']') + 1:].strip()
    if core_without_artist.startswith("["):
        r = core_without_artist.find("]")
        if r != len(core_without_artist) - 1 or core_without_artist.count("]") == 1:
            core_without_artist = core_without_artist[1: r] + core_without_artist[r + 1:]
    ret = " ".join([f"[{artist}]", core_without_artist, prefix])
    ret = ret.replace("(", " (").replace(")", ") ")
    ret = ret.replace("  ", " ").strip()
    ret = ret + ext

    logger.debug(f"core_with_artist : {core_with_artist}")
    logger.debug(f"core_without_artist : {core_without_artist}")
    logger.debug(f"ext : {ext}")
    logger.debug(f"ret : {ret}")
    return ret


def ChangeArtistOnly(name: str, artist: str) -> str:
    withoutArtist = name[name.find(']') + 1:].strip()
    return f"[{artist}] {withoutArtist}"

def formatNameTask(inputPaths: list[Path], noAsk: bool = False):
    inputPaths = sorted(inputPaths, key=lambda path: os.stat(path).st_ctime_ns)

    failed = False
    mp = {}
    for path in inputPaths:
        newname = FormatName(path)
        if newname == "":
            logger.error(f"Failed to format {path.name}")
            failed = True
            continue
        logger.info(f"{path.name} ==>")
        logger.info(f"{newname}")
        print("")
        mp[path] = newname

    if failed:
        logger.warning("Some files failed to format, please check them")
        input()
        return

    if noAsk or Ask("Change these name? (y/N)"):
        for path in inputPaths:
            if path == mp[path]:
                continue
            newpath = path.with_name(mp[path])
            path.rename(newpath)
    logger.info("Work Done!")

def main():
    global RemoveGroup
    if len(sys.argv) <= 1:
        logger.error("Please take parameters as input")
        exit(0)

    #if Ask("Remove group name? (y/N)"):
    RemoveGroup = True

    formatNameTask([Path(x) for x in sys.argv[1:]])


def UnitTest():
    global RemoveGroup
    RemoveGroup = True
    cases = {
        "(useless) [I'm artist] This is name.zip": "[I'm artist] This is name (useless).zip",
    }
    for raw, expect in cases.items():
        got = FormatName(raw)
        if got != expect:
            logger.error(f"Expect '{expect}', but got '{got}'")
            input()

    cases = {
        "[I'm artist] This is name.zip": "[new artist] This is name.zip"
    }
    for raw, expect in cases.items():
        got = ChangeArtistOnly(raw, "new artist")
        if got != expect:
            logger.error(f"Expect '{expect}', but got '{got}'")
            input()
    RemoveGroup = False


if __name__ == "__main__":
    UnitTest()
    try:
        main()
    except Exception:
        logger.error(traceback.format_exc())
    ExitInSeconds(10)
