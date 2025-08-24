import json
import math
import asyncio
import uvicorn
import difflib
import datetime

from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from utils import NewFileLogger
from infos import DownloadDir, ActualDownload
from autoclassfiy import FindArtistV2

logger = NewFileLogger(__file__, True)

partMatchPercent = 0.65
lastDataUpdateDate = datetime.datetime.now()
nameCache = []
authorCache = []

async def ReadAllFiles(newcache=False):
    global nameCache
    jsonCache = {
        "names": [],
        "time": "",
    }
    if not newcache and Path("cache/nameCache.json").exists():
        with open("cache/nameCache.json", "r", encoding="utf-8") as f:
            jsonCache = json.load(f)
        jsonCache["time"] = datetime.datetime.fromisoformat(jsonCache["time"])
        if datetime.datetime.now() - jsonCache["time"] < datetime.timedelta(days=1):
            nameCache.clear()
            nameCache.extend(jsonCache["names"])
            nameCache = sorted(nameCache, reverse=True)
            getAuthorFromNameCache()
            logger.debug(f"Read NameCache from file, length : {len(nameCache)}")
            logger.debug(f"Generate authorCache, length : {len(authorCache)}")
            return

    if newcache:
        logger.debug("Refresh cache")
    root = Path(DownloadDir)
    if not root.exists():
        return []
    for p, dirnames, filenames in root.walk():
        if p == root:
            continue
        jsonCache["names"].extend(dirnames)
        jsonCache["names"].extend(f.removesuffix('.zip') for f in filenames if f.endswith('.zip'))
    jsonCache["names"].extend(
        [p.name.removesuffix('.zip') for p in Path(ActualDownload).iterdir()
         if p.is_file() and p.name.endswith('.zip')])

    jsonCache["time"] = datetime.datetime.now().isoformat()

    nameCache.clear()
    nameCache.extend(jsonCache["names"])
    nameCache = sorted(nameCache, reverse=True)
    getAuthorFromNameCache()

    logger.debug(f"Read {len(nameCache)} names from {DownloadDir} and {ActualDownload}")

    with open("cache/nameCache.json", "w", encoding="utf-8") as f:
        json.dump(jsonCache, f, ensure_ascii=False, indent=4)


def checkAuthorInName(name: str, author: str):
    if f'[{author}]' in name or f'({author})' in name:
        return True
    return False


def partMatch(cache: str, name: str):
    found = False
    foundName = ""
    limit = int(math.ceil(len(name) * (1 - partMatchPercent)))
    # found half of the rname
    for i in range(1, min(20, limit)):
        tname = name[:-i]
        if tname == "":
            break
        if tname in cache:
            found = True
            foundName = cache
            break
    return found, foundName


def getAuthorFromNameCache():
    authorCache.clear()
    for name in nameCache:
        author = FindArtistV2(name)
        if len(author) == 0 or author in authorCache:
            continue
        authorCache.append(author)


async def queryName(name: str, author: str = "") -> tuple[bool, str]:
    # use fuzzy match
    cutoff = 0.6
    if len(name) < 15:
        cutoff = 0.8
    matches = difflib.get_close_matches(name, nameCache, n=3, cutoff=cutoff)
    if matches:
        for match in matches:
            if not checkAuthorInName(match, author):
                logger.debug(f"fuzzy match : {match}, but author not found : {author}")
                continue
            logger.debug(f"Query Name {name}, fuzzy match found {match}")
            return True, match

    found = False
    foundName = ""
    for cache in nameCache:
        if name in cache:
            found = True
            foundName = cache
            break

        tFound, tFoundName = partMatch(cache, name)
        if not tFound:
            continue
        if author == "":
            found = tFound
            foundName = tFoundName
            break
        if checkAuthorInName(tFoundName, author):
            found = tFound
            foundName = tFoundName
            break
        else:
            logger.debug(f"part match :{tFoundName}, but no author found : {author}")
    if found:
        logger.debug(f"Part found : {foundName}")
        return True, foundName
    return False, ""


async def queryAuthor(author: str):
    for cache in authorCache:
        if author in cache:
            return True
    return False


async def refreshNameCache():
    global nameCache
    while True:
        logger.info("Waiting for 12 hours to refresh name cache...")
        await asyncio.sleep(3600 * 12)  # Refresh every 12 hours
        nameCache = []
        logger.info("Refresh cache every 12 hours")
        await ReadAllFiles(newcache=True)
        logger.info(f"Name cache refreshed, len: {len(nameCache)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start
    # import logging
    # logger = logging.getLogger("uvicorn.access")
    # logger.handlers[0].setFormatter(logging.Formatter(
    #     "%(asctime)s - %(levelname)s - %(message)s "))
    global nameCache
    await ReadAllFiles()
    asyncio.create_task(refreshNameCache())
    # handle request
    yield
    # exit
    nameCache.clear()


app = FastAPI(lifespan=lifespan)


# Allow CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware('http')
async def updateCacheMiddleware(req: Request, call_next):
    global lastDataUpdateDate
    now = datetime.datetime.now()
    if now - lastDataUpdateDate > datetime.timedelta(hours=3):
        lastDataUpdateDate = now
        logger.debug("Refresh cache due to 6 hour passed since last query")
        await ReadAllFiles(newcache=True)
    return await call_next(req)

# @app.middleware('http')
# async def timeCostMiddleware(req: Request, call_next):
#     start = datetime.datetime.now()
#     rsp = await call_next(req)
#     eplased = datetime.datetime.now() - start
#     logger.debug(f"Query use {eplased}")
#     return rsp

@app.get("/")
async def _():
    return JSONResponse(content={"message": "Hello, World!"}, status_code=200)


@app.post("/query/name")
async def _(request: Request):
    data: dict = await request.json()
    author = data.get('author')
    name = data.get("name")

    found, foundName = await queryName(name, author)
    if found:
        logger.debug(f"Found query '{name}' and author '{author}', ")
        return JSONResponse(content={"name": foundName}, status_code=200)

    logger.debug(f"Nothing query '{name}' and author '{author}'")
    return JSONResponse(content={"name": ""}, status_code=404)


@app.post("/query/author")
async def _(request: Request):
    data: dict = await request.json()
    author = data.get("author")

    found = await queryAuthor(author)
    if found:
        logger.debug(f"Found query '{author}'")
        return JSONResponse(content={}, status_code=200)

    logger.debug(f"Nothing query '{author}'")
    return JSONResponse(content={}, status_code=404)

@app.post("/query/extractAuthor")
async def _(request: Request):
    data: dict = await request.json()
    title = data.get("title")
    author = FindArtistV2(title)
    logger.debug(f"Find artist for {title} : {author}")
    return JSONResponse(content={"author": author}, status_code=200)

if __name__ == "__main__":
    # 只在直接运行时启动 uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
