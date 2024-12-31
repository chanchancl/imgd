import os
import sys
import time
import traceback

from infos import IgnoredArtist
from pathlib import Path
from utils import Ask

_DEBUG = False


def FindArtistStartIndex(who: str|Path) -> str:
    input_path = who.name if isinstance(who, Path) else who
    start_idx, end_idx = input_path.find('['), input_path.find(']')
    if any(x == -1 for x in [start_idx, end_idx]):
        return -1, ""

    inBrackets = input_path[start_idx+1:end_idx]
    artist = inBrackets
    # startia, endia = inBrackets.find('('), inBrackets.find(')')
    # if all(x != -1 for x in [startia, endia]):
    #     artist = inBrackets[startia+1: endia].strip()

    if any(ignored in artist for ignored in IgnoredArtist):
        remainingPath = input_path[end_idx+1:].strip()
        # print(f"ignored found {inputPath}, end {endi}, will find in {remainingPath}")
        nextStartI, nextArtist = FindArtistStartIndex(remainingPath)
        return end_idx + nextStartI + 1, nextArtist
    return start_idx, artist


def FormatName(path: str|Path):
    name: str = path.name if isinstance(path, Path) else path

    starti, artist = FindArtistStartIndex(name)
    if starti == -1 and artist == "":
        print(f"No artist found in {name}")
        return ""

    suffix = name[:starti].strip()
    dotidx = name.rfind('.')
    exti = dotidx if dotidx != -1 else len(name)
    ext = name[exti:] if dotidx != -1 else ""
    withoutSuffixAndExt = name[starti:exti].strip()

    ret = f"{withoutSuffixAndExt} {suffix}{ext}"

    if _DEBUG:
        print(f"withoutSuffixAndExt : {withoutSuffixAndExt}\nsuffix : {suffix}\next : {ext}")
        print(f"phase 1 : {ret}")

    withoutArtist = ret[ret.find(']')+1:].strip()
    ret = f"[{artist}] {withoutArtist}"
    return ret


def ChangeArtistOnly(name: str, artist: str) -> str:
    withoutArtist = name[name.find(']')+1:].strip()
    return f"[{artist}] {withoutArtist}"


def main():
    if len(sys.argv) <= 1:
        print("Please take parameters as input")
        exit(0)

    inputPaths = [Path(x) for x in sys.argv[1:] ]
    inputPaths = sorted(inputPaths, key= lambda path: os.stat(path).st_ctime_ns)

    mp = {}
    for path in inputPaths:
        newname = FormatName(path.name)
        print(f"   {path.name}\n-> {newname}\n")
        mp[path] = newname

    if Ask("Change these name? (y/N)"):
        if Ask("Specify a common name? (y/N)"):
            print("Please input common name : ")
            common = input()
            for path in inputPaths:
                mp[path] = ChangeArtistOnly(mp[path], common)
        for path in inputPaths:
            # change by order
            newpath = path.with_name(mp[path])
            path.rename(newpath)
    print("Work Done!")


def ExitInSeconds(seconds):
    for i in range(seconds):
        print(f"Will exist after {seconds-i} seconds")
        time.sleep(1)


def UnitTest():
    cases = {
        "(useless) [I'm artist] This is name.zip": "[I'm artist] This is name (useless).zip"
    }
    for raw, expect in cases.items():
        got = FormatName(raw)
        if got != expect:
            print(f"Expect '{expect}', but got '{got}'")
            input()

    cases = {
        "[I'm artist] This is name.zip": "[new artist] This is name.zip"
    }
    for raw, expect in cases.items():
        got = ChangeArtistOnly(raw, "new artist")
        if got != expect:
            print(f"Expect '{expect}', but got '{got}'")
            input()


if __name__ == "__main__":
    UnitTest()
    try:
        main()
    except Exception:
        print(traceback.format_exc())
    input()

