import os
import sys
import traceback

from infos import IgnoredArtist
from pathlib import Path
from utils import Ask, ExitInSeconds, NewFileLogger

_DEBUG = False

RemoveGroup = False
logger = NewFileLogger(__file__, _DEBUG)

def FindArtistStartIndex(who: str | Path) -> str:
    inputPath = who.name if isinstance(who, Path) else who
    startIdx, endIdx = inputPath.find('['), inputPath.find(']')
    if startIdx == -1 or endIdx == -1:
        return -1, ""

    inBrackets = inputPath[startIdx + 1:endIdx]
    artist = inBrackets
    if RemoveGroup:
        startIdxInB, endIdxInB = inBrackets.find('('), inBrackets.find(')')
        if startIdxInB != -1 and endIdxInB != -1:
            artist = inBrackets[startIdxInB + 1: endIdxInB].strip()

    if any(ignored in artist for ignored in IgnoredArtist):
        remainingPath = inputPath[endIdx + 1:].strip()
        nextStartIdx, newArtist = FindArtistStartIndex(remainingPath)
        return endIdx + nextStartIdx + 1, newArtist
    return startIdx, artist


def FormatName(path: str | Path) -> str:
    name: str = path.name if isinstance(path, Path) else path

    startIdx, artist = FindArtistStartIndex(name)
    if startIdx == -1 and artist == "":
        logger.warning(f"No artist found in {name}")
        return ""

    suffix = name[:startIdx].strip()
    dotIdx = name.rfind('.')
    extIdx = dotIdx if dotIdx != -1 else len(name)
    ext = name[extIdx:] if dotIdx != -1 else ""
    withoutSuffixAndExt = name[startIdx:extIdx].strip()

    ret = f"{withoutSuffixAndExt} {suffix}{ext}"

    logger.debug(f"withoutSuffixAndExt : {withoutSuffixAndExt}\nsuffix : {suffix}\next : {ext}")
    logger.debug(f"phase 1 : {ret}")

    withoutArtist = ret[ret.find(']') + 1:].strip()
    ret = f"[{artist}] {withoutArtist}"
    return ret


def ChangeArtistOnly(name: str, artist: str) -> str:
    withoutArtist = name[name.find(']') + 1:].strip()
    return f"[{artist}] {withoutArtist}"

def formatNameTask(inputPaths: list[Path], noAsk: bool = False):
    inputPaths = sorted(inputPaths, key=lambda path: os.stat(path).st_ctime_ns)

    failed = False
    mp = {}
    for path in inputPaths:
        newname = FormatName(path.name)
        if newname == "":
            logger.error(f"Failed to format {path.name}")
            failed = True
            continue
        logger.info(f"{path.name} ==>\n\t{newname}")
        mp[path] = newname

    if failed:
        logger.warning("Some files failed to format, please check them")
        input()
        return

    if noAsk or Ask("Change these name? (y/N)"):
        for path in inputPaths:
            newpath = path.with_name(mp[path])
            path.rename(newpath)
    logger.info("Work Done!")

def main():
    if len(sys.argv) <= 1:
        logger.error("Please take parameters as input")
        exit(0)

    if Ask("Remove group name? (y/N)"):
        global RemoveGroup
        RemoveGroup = True

    formatNameTask([Path(x) for x in sys.argv[1:]])


def UnitTest():
    cases = {
        "(useless) [I'm artist] This is name.zip": "[I'm artist] This is name (useless).zip"
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


if __name__ == "__main__":
    UnitTest()
    try:
        main()
    except Exception:
        logger.error(traceback.format_exc())
    ExitInSeconds(10)
