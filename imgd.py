
import re
import math
import json
import aiohttp
import asyncio
import hashlib
import pathlib
import aiofiles
import functools

from PIL import Image
from io import BytesIO
from datetime import datetime
from bs4 import BeautifulSoup as bs


import infos
import utils

endpoint = infos.Endpoint
header = utils.BuildHeaderFromStr(infos.HeaderStr)


ProxyAddress = infos.ProxyAddress
# 下载目录
DOWNLOAD_DIR = infos.DownloadDir
# 下载线程数
WORKER_NUM = infos.WorkerThreadNum
# 是否对图像进行修复
Reduction = infos.Reduction
# 若文件已经存在，是否重新下载并覆盖
ReDownload = infos.ReDownload
# 漫画ID，使用' '分隔
# 有若干章节的漫画，填到这里，用' '分隔
# 下载目录的子目录，为空的话则不创建
DownloadInfo = infos.DownloadInfo

DefaultSleepTime = 0.1
BeginOfReductionID = 226784

LogFilePath = infos.LogFilePath

from rich.progress import (
    TextColumn,
    SpinnerColumn,
    BarColumn,
    Progress,
    TimeElapsedColumn,
    TimeRemainingColumn,
    MofNCompleteColumn,
)

progress = Progress(
    SpinnerColumn(),
    TextColumn("[bold blue]Downloading...", justify="right"),
    BarColumn(),
    MofNCompleteColumn(),
    TimeElapsedColumn(),
    TimeRemainingColumn(),
)



def getNum(e: str, t: str):
    a = 10
    if int(e) >= 268850:
        # 在这之后采用新的加密方法
        n = f"{e}{t}"
        hs = hashlib.md5()
        hs.update(n.encode())
        n = ord(hs.hexdigest()[-1]) % 10
        a = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20][n]
    return a


def ReductionImage(image: Image.Image, num: int) -> Image.Image:
    # create a same (mode, size) image
    newImage = Image.new(image.mode, image.size)
    width, height = image.size
    ph = math.floor(height / num)

    for i in range(num):
        rawX = 0
        rawY = (num - i - 1) * ph
        newX = 0
        newY = i * ph
        newDiff = 0
        if i == 0:
            # fill the first diff block
            rawDiff = height - (rawY + ph)
        else:
            newDiff = rawDiff
        newImage.paste(image.crop(
            (rawX, rawY, width, rawY + ph + rawDiff)),
            (newX, newY + newDiff))
    return newImage


async def get(session: aiohttp.ClientSession, url: str, *args, **kwargs) -> bytes:
    MaxRetry = 10
    retry = 0
    sleepTime = DefaultSleepTime
    while retry < MaxRetry:
        retry += 1
        if retry >= MaxRetry // 2:
            sleepTime = DefaultSleepTime * 2
        ret = None
        try:
            async with session.get(url, *args, **kwargs) as rsp:
                if rsp.status == 200:
                    ret = await rsp.read()
                    return ret
        except Exception as e:
            print(f"Exception is raised {e} when connecting {url}")
            if retry == MaxRetry:
                raise  # raise out
            await asyncio.sleep(sleepTime)
        finally:
            if ret is None:
                print(f"Failed with {retry} times")

    print(f"All retry are failed, {MaxRetry} times")


lock = asyncio.Lock()

async def Worker(workerID: int, path: str, comicID: str, queue: list, session: aiohttp.ClientSession, progressTask):
    count = 0
    while True:
        # pop an work from queue
        await lock.acquire()
        try:
            if len(queue) == 0:
                break
            photo = queue.pop()
        finally:
            lock.release()

        count += 1
        fileName = photo['id']
        imageURL = photo.img['data-original']
        dest = path.joinpath(fileName)

        if count % 7 == 1:
            progress.console.print(f"Worker {workerID}")
            progress.console.print(fileName, imageURL)
            progress.console.print(dest)
        if not ReDownload and dest.exists():
            continue
        
        try:
            rsp = await get(session, imageURL, headers=header, proxy=ProxyAddress)
        except Exception:
            # retry, but failed
            async with lock:
                # put work to queue again
                queue.append(photo)
            continue

        img = Image.open(BytesIO(rsp))
        # img.save(dest)
        newimg = img
        if Reduction and int(comicID) >= BeginOfReductionID:
            num = getNum(comicID, fileName.split('.')[0])
            newimg = ReductionImage(img, num)

        # Image.save is a sync method, so make it async
        save = functools.partial(newimg.save, dest)
        await asyncio.get_event_loop().run_in_executor(None, save)

        async with lock:
            progress.update(progressTask, advance=1)

        await asyncio.sleep(DefaultSleepTime)
    progress.console.print(f"Worker {workerID} is done! Do {count} works")
    return count


async def Download(url: str, dest: pathlib.Path, info: dict = None):
    # 识别两种不同的URL格式，并从格式中提取漫画ID
    # getTitle
    # getPageRange
    comicID = url.rsplit('/')[-1]
    with progress:
        async with aiohttp.ClientSession() as session:
            try:
                rsp = await get(session, url, headers=header, proxy=ProxyAddress)
            except Exception:
                print(f"Failed to download web page {url}, Please check network config")
                exit()

            soup = bs(rsp, "html.parser")
            try:
                a = soup.find('div', class_='panel-body')
                photos = a.find_all('div', class_="center scramble-page")
                photos.reverse()
            except Exception as e:
                print(f"Failed to parse html in {url}, with exception : {e}")
                exit()
            allWork = len(photos)

            panel = soup.find('div', class_='panel-heading')
            title = panel.find('div', class_='pull-left').text.strip()
            title = re.sub('[\\/:*?"<>|]', '', title)
            title = title.strip()

            basePath = pathlib.Path(dest)
            path = basePath.joinpath(title)

            path.mkdir(parents=True, exist_ok=True)
            progress.console.print(title)
            progress.console.print(path)
            if info is not None:
                info.setdefault("comics", [])
                info['comics'].append({
                    'title': title,
                    'path': str(path),
                    'url': url,
                    'page': len(photos),
                })
                info['threads'] = WORKER_NUM

            tasks = []  # coroutine task
            progressTask = progress.add_task("total", total=len(photos))
            for i in range(WORKER_NUM):
                tasks.append(asyncio.create_task(
                    Worker(i, path, comicID, photos, session, progressTask)))

            done = sum(await asyncio.gather(*tasks))

            progress.console.print(f"All worker are done, {done}/{allWork}")
            progress.remove_task(progressTask)
    return


async def GetAllComicIdFromAlbum(albumID: str, dest: pathlib.Path, info: dict = None):
    url = f"{endpoint}/album/{albumID}"
    async with aiohttp.ClientSession() as session:
        rsp = await get(session, url, headers=header, proxy=ProxyAddress)

    idList = []
    soup = bs(rsp, "html.parser")
    ul = soup.find('ul', class_='btn-toolbar')
    for a in ul.find_all('a'):
        comicID = a['href'].rsplit('/', 1)[-1]
        idList.append(comicID)

    title = soup.title.text
    title = re.sub('[\\/:*?"<>|]', '', title)
    newdir = dest.joinpath(title)

    for comicID in idList:
        await Download(f"{endpoint}/photo/{comicID}", newdir, info)
    return


async def SaveLog(informations):
    async with aiofiles.open(LogFilePath, "a+", encoding="utf-8") as f:
        for info in informations:
            if info == infos.EmptyInfo:
                continue
            await f.write(json.dumps(info, ensure_ascii=False, indent=2) + "\n")


async def main():
    for info in DownloadInfo:
        if info == infos.EmptyInfo:
            continue

        info['time'] = datetime.now().strftime("%Y.%m.%d %T")
        comicIDs = [x for x in info['comicIds'].strip().split(' ') if x != ""]
        dest = pathlib.Path(DOWNLOAD_DIR)
        if info['subDir'] != "":
            dest = dest.joinpath(info['subDir'])
        print(f"Comic list : {comicIDs}")
        print(f"Destination dir : {dest}")

        for comicID in comicIDs:
            await Download(f"{endpoint}/photo/{comicID}", dest, info)

        albumIDs = [x for x in info['albumPages'].strip().split(' ')
                    if x != ""]
        for albumID in albumIDs:
            await GetAllComicIdFromAlbum(albumID, dest, info)

    await SaveLog(DownloadInfo)
    print("Main exit")

if __name__ == "__main__":
    asyncio.run(main())
