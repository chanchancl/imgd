
from rich.progress import (
    get_console,
    TextColumn,
    SpinnerColumn,
    BarColumn,
    Progress,
    TimeElapsedColumn,
    TimeRemainingColumn,
    MofNCompleteColumn,
)
import re
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
from reduction import ReductionImage

endpoint = infos.Endpoint
header = utils.BuildHeaderFromStr(infos.HeaderStr)

# 代理地址
ProxyAddress = infos.ProxyAddress
# 下载目录
DOWNLOAD_DIR = infos.DownloadDir
# 下载线程数
WORKER_NUM = infos.WorkerThreadNum
# 是否对图像进行修复
Reduction = infos.Reduction
# 若文件已经存在，是否重新下载并覆盖
ForceDownloadIfExist = infos.ReDownload
# 漫画ID，使用' '分隔
# 有若干章节的漫画，填到这里，用' '分隔
# 下载目录的子目录，为空的话则不创建
DownloadInfo = infos.DownloadInfo

DefaultSleepTime = 0.1
BeginOfReductionID = 223301

LogFilePath = infos.LogFilePath

progress = Progress(
    SpinnerColumn(),
    TextColumn("[bold blue]Downloading...", justify="right"),
    BarColumn(),
    MofNCompleteColumn(),
    TimeElapsedColumn(),
    TimeRemainingColumn(),
)


def AsyncWrapper(func):
    @functools.wraps(func)  # 用于保留被包装函数的函数名，文档等内容
    async def _wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        pfunc = functools.partial(func, *args, **kwargs)
        result = await loop.run_in_executor(None, pfunc)
        return result

    return _wrapper


def HashPageColumnNumber(comicID: str, pageID: str):
    column = 10
    if int(comicID) >= 268850:
        # 在这之后采用新的加密方法
        n = f"{comicID}{pageID}"
        hs = hashlib.md5()
        hs.update(n.encode())
        n = ord(hs.hexdigest()[-1]) % 10
        column = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20][n]
    return column


# 去除不合法的文件名字符
def StripText(text: str) -> str:
    return re.sub('[.\\/:*?"<>|\n]', '', text).strip()


async def get(session: aiohttp.ClientSession, url: str, *args, **kwargs) -> bytes:
    MaxRetry = 10
    retry = 0
    sleepTime = DefaultSleepTime
    # print(f"Download : {url}")
    while retry < MaxRetry:
        if retry >= MaxRetry // 2:
            sleepTime = sleepTime * 2
        retry += 1
        ret = None
        try:
            async with session.get(url, *args, **kwargs) as rsp:
                if rsp.status == 200:
                    ret = await rsp.read()
                    return ret
        except KeyboardInterrupt:
            # 将key board 异常向上发送，使得外部可以退出，实际上只要不
            # except Exception as e:  就没必要写这句，因为默认就会向外扔
            raise
        except aiohttp.ClientError as e:
            # 网络错误，尝试重试，如果超过MaxRetry次，则抛出异常
            print(f"Exception is raised {e} when connecting {url}")
            if retry >= MaxRetry:
                raise  # raise out
            await asyncio.sleep(sleepTime)
        if ret is None:
            print(f"Failed with {retry} times")

    print(f"All retry are failed, {MaxRetry} times")


# 所有的worker，在操作队列时，需要加锁
lock = asyncio.Lock()


async def Worker(workerID: int, path: str, comicID: str, queue: list, session: aiohttp.ClientSession, progressTask):
    count = 0
    # 所有的Worker都处于 progress 的有效作用域
    while True:
        # pop an work from queue
        await lock.acquire()
        try:
            if len(queue) == 0:
                break
            work = queue.pop()
        finally:
            lock.release()

        # 计数
        count += 1
        fileName = work['id']
        imageURL = work['url']
        dest = path.joinpath(fileName)

        # 打印部分下载状态
        if count % 7 == 1:
            print(f"Worker {workerID}")
            print(fileName, imageURL)
            print(dest)

        # 文件存在时，是否重新下载
        if not ForceDownloadIfExist and dest.exists():
            continue

        # 获取资源，如果失败则把task放回队列
        try:
            rsp = await get(session, imageURL, headers=header, proxy=ProxyAddress)
            # 处理图片
            img = Image.open(BytesIO(rsp))
            if Reduction and int(comicID) >= BeginOfReductionID:
                column = HashPageColumnNumber(comicID, fileName.split('.')[0])
                img = await AsyncWrapper(ReductionImage)(img, column)
            # 异步IO保存图片 Image.save is a sync method, so make it async
            await AsyncWrapper(img.save)(dest)
        except KeyboardInterrupt as e:
            # 下载过程中检测到 退出信号，则打印log并退出
            print(f"Get input from keyboard, will exit {e}")
            raise
        except Exception:
            # 处理其余任何导致下载失败的异常
            # retry, but failed
            if work['count'] > 3:
                print(f"In worker {workerID}, Failed to download {imageURL} with retry")
                progress.console.print_exception()
                continue  # drop this task
            work['count'] += 1
            async with lock:
                # put work to queue again
                queue.append(work)
            continue

        # 更新进度条
        async with lock:
            progress.update(progressTask, advance=1)

        # 休眠
        await asyncio.sleep(DefaultSleepTime)
    print(f"Worker {workerID} is done! Do {count} works")
    return count


async def Download(url: str, dest: pathlib.Path, info: dict = None):
    # 识别两种不同的URL格式，并从格式中提取漫画ID
    # getTitle
    # getPageRange
    comicID = url.rsplit('/')[-1]
    nextPageURL = url
    print(f"Start to download comic {comicID}")

    async with aiohttp.ClientSession() as session:
        # 尝试获取资源
        allWork = 0
        works = []

        # 循环遍历所有page，将所有工作添加至 works
        while nextPageURL is not None:
            url = nextPageURL
            nextPageURL = None
            try:
                rsp = await get(session, url, headers=header, proxy=ProxyAddress)
            except Exception:
                print(f"Failed to download web page {url}, Please check network config")
                progress.console.print_exception()
                exit()

            # 从页面获取所有目标资源地址，打包进 works
            soup = bs(rsp, "html.parser")
            try:
                a = soup.find('div', class_='panel-body')
                photos = a.find_all('div', class_="center scramble-page")
                photos.reverse()
            except Exception as e:
                print(f"Failed to parse html in {url}, with exception : {e}")
                progress.console.print_exception()
                # wait and retry here
                nextPageURL = url
                await asyncio.sleep(1)
                continue
                # exit()

            works.extend(
                [{
                    "id": x["id"],                  # 文件夹名
                    "url": x.img['data-original'],  # 图片地址
                    "count": 0,                     # 重试次数
                } for x in photos]
            )

            # 取标题，并进行非法字符的删除
            panel = soup.find('div', class_='panel-heading')
            title = panel.find('div', class_='pull-left').text.strip()
            title = StripText(title)

            # 路径计算
            basePath = pathlib.Path(dest)
            path = basePath.joinpath(title)
            path.mkdir(parents=True, exist_ok=True)

            # 打印标题与路径
            print(title)
            print(path)

            # 尝试寻找下一页
            nextPage = soup.find('a', class_='prevnext')
            if nextPage is not None:
                nextPageURL = nextPage['href']

        # 创建进度条
        progressTask = progress.add_task("total", total=len(works))
        # 创建 WORKER_NUM 个task，从同一个list中取task，直到list为空
        tasks = []  # coroutine task
        copyWorks = works.copy()
        for i in range(WORKER_NUM):
            tasks.append(asyncio.create_task(
                Worker(i, path, comicID, copyWorks, session, progressTask)))

        # 等待并统计完成的工作数量
        done = sum(await asyncio.gather(*tasks))

        allWork += len(works)
        print(f"All workers on {comicID} are done, {done}/{allWork}")
        # 删除进度条
        progress.remove_task(progressTask)
    return


async def GetAllComicIdFromAlbum(albumID: str, dest: pathlib.Path, info: dict = None):
    url = f"{endpoint}/album/{albumID}"
    async with aiohttp.ClientSession() as session:
        rsp = await get(session, url, headers=header, proxy=ProxyAddress)
        if len(rsp) <= 200:
            print("some error happen")
            print(rsp)
            return

    idList = []
    soup = bs(rsp, "html.parser")
    ul = soup.find('ul', class_='btn-toolbar')
    for a in ul.find_all('a'):
        comicID = a['href'].rsplit('/', 1)[-1]
        idList.append(comicID)

    title = soup.title.text
    title = StripText(title)
    newdir = dest.joinpath(title)

    for comicID in idList:
        await Download(f"{endpoint}/photo/{comicID}", newdir, info)
    return


async def SaveLog(informations):
    async with aiofiles.open(LogFilePath, "a+", encoding="utf-8") as f:
        for info in informations:
            if info == infos.EmptyInfo:
                continue
            comicIDs = [x for x in info['comicIds'].strip().split(' ')
                        if x != ""]
            albumIDs = [x for x in info['albumPages'].strip().split(' ')
                        if x != ""]
            if len(comicIDs) == 0 and len(albumIDs) == 0:
                continue
            await f.write(json.dumps(info, ensure_ascii=False) + "\n")


async def main():
    for info in DownloadInfo:
        if info == infos.EmptyInfo:
            continue

        info['time'] = datetime.now().strftime("%Y.%m.%d %T")
        comicIDs = [x for x in info['comicIds'].strip().split(' ') if x != ""]
        dest = pathlib.Path(DOWNLOAD_DIR)

        # Redirect dest if prefix match
        if info['subDir'] != "":
            perfectMatchPath = dest.joinpath(info['subDir'])
            if perfectMatchPath.exists():
                dest = perfectMatchPath
            else:
                prefixMatchPath = perfectMatchPath   # default value, if prefixMatch is None
                for it in dest.iterdir():
                    if it.is_dir() and it.name.startswith(info['subDir']):
                        prefixMatchPath = it
                        print(f"Redirect dest path to {dest}")
                        break
                dest = prefixMatchPath

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
    with progress:
        print = progress.console.print
        asyncio.run(main())
