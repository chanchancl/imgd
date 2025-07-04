import json
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

logger = NewFileLogger(__file__)


nameCache = []

async def ReadAllFiles(newcache=False):
    global nameCache
    jsonCache = {
        "names": [],
        "time": ""
    }
    if not newcache and Path("cache/nameCache.json").exists():
        with open("cache/nameCache.json", "r", encoding="utf-8") as f:
            jsonCache = json.load(f)
        jsonCache["time"] = datetime.datetime.fromisoformat(jsonCache["time"])
        if datetime.datetime.now() - jsonCache["time"] < datetime.timedelta(days=1):
            nameCache.extend(jsonCache["names"])
            nameCache = sorted(nameCache, reverse=True)
            logger.info(f"Using cached nameCache, len : {len(nameCache)}")
            return

    root = Path(DownloadDir)
    if not root.exists():
        return []
    for p, dirnames, filenames in root.walk():
        if p == root:
            continue
        jsonCache["names"].extend(dirnames)
        jsonCache["names"].extend(f.removesuffix('.zip') for f in filenames if f.endswith('.zip'))
    jsonCache["names"].extend([p.name.removesuffix('.zip') for p in Path(ActualDownload).iterdir() if p.is_file() and p.name.endswith('.zip')])

    jsonCache["time"] = datetime.datetime.now().isoformat()

    nameCache.extend(jsonCache["names"])
    nameCache = sorted(nameCache, reverse=True)

    logger.info(f"Read {len(nameCache)} names from {DownloadDir} and {ActualDownload}")

    with open("cache/nameCache.json", "w", encoding="utf-8") as f:
        json.dump(jsonCache, f, ensure_ascii=False, indent=4)

def queryName(rname):
    # use fuzzy match
    matches = difflib.get_close_matches(rname, nameCache, n=1, cutoff=0.6)
    if matches:
        logger.info(f"Fuzzy match found {matches[0]}")
        return True, matches[0]

    found = False
    foundName = ""
    for name in nameCache:
        if found:
            break
        if rname in name:
            found = True
            foundName = name
        if not found:
            # found half of the rname
            for i in range(1, min(20, len(rname) * 2 // 3)):
                if rname[:i] != "" and rname[:-i] in name:
                    found = True
                    foundName = name
                    break
    if found:
        return True, foundName
    return False, ""

async def refreshNameCache():
    global nameCache
    while True:
        logger.info("Waiting for 12 hours to refresh name cache...")
        await asyncio.sleep(3600 * 12)  # Refresh every 12 hours
        nameCache = []
        await ReadAllFiles(newcache=True)
        logger.info(f"Name cache refreshed, len: {len(nameCache)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global nameCache
    await ReadAllFiles()
    asyncio.create_task(refreshNameCache())
    yield
    nameCache.clear()

app = FastAPI(lifespan=lifespan)

# Allow CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def _():
    return JSONResponse(content={"message": "Hello, World!"}, status_code=200)

@app.post("/queryname")
async def _(request: Request):
    data: dict = await request.json()
    rname = data.get("name")
    logger.info(f" {rname}, len of nameCache: {len(nameCache)}")

    found, foundName = queryName(rname)
    if found:
        return JSONResponse(content={"name": foundName}, status_code=200)
    return JSONResponse(content={"name": ""}, status_code=404)


if __name__ == "__main__":
    # 只在直接运行时启动 uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
