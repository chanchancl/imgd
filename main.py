import re
import logging
import coloredlogs

from copy import copy
from pathlib import Path
from fastapi import FastAPI, UploadFile, HTTPException
from PIL import Image, ImageFile
from io import BytesIO
from urllib.parse import unquote

from infos import DownloadDir

class CustomFormatter(coloredlogs.ColoredFormatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def formatMessage(self, record):
        record = copy(record)
        msg = super().formatMessage(record)
        return unquote(msg)


app = FastAPI()

@app.on_event("startup")
async def _():
    logger = logging.getLogger("uvicorn.access")
    logger.handlers[0].setFormatter(CustomFormatter("%(asctime)s - %(levelname)s - %(message)s "))


@app.get("/")
def read_root():
    return {"Hello": "World"}

def CompressPic(picBytes):
    k = 1
    expectedSize = 1500  # KB
    ImageFile.LOAD_TRUNCATED_IMAGES = True

    curSize = len(picBytes) // 1024
    # print(f'input size {curSize} KB')
    if curSize <= expectedSize:
        return picBytes

    output = Image.open(BytesIO(picBytes))
    # print(output.format, output.size, output.mode)
    if 'A' in output.mode:
        output = output.convert('RGB')

    while curSize > expectedSize:
        bt = BytesIO()
        output = output.resize(
            map(lambda x: int(k * x), output.size), Image.ANTIALIAS)
        output.save(bt, 'jpeg', quality=100)
        curSize = len(bt.getbuffer()) // 1024
        # print(output.size, curSize)
        k = 0.95

    # print('output size {} KB'.format(curSize))

    btio = BytesIO()
    output.save(btio, 'jpeg')
    return btio.getbuffer().tobytes()


@app.get("/{comic_name}/{page_id}")
def check_item(comic_name: str, page_id: str):
    comic_name = re.sub(r'[\\/:*?"<>|#]', '', comic_name)
    root = Path(DownloadDir).joinpath(comic_name)
    if root.exists():
        filepath = root.joinpath(page_id)
        if filepath.exists():
            print(f"File {filepath} is exists")
            raise HTTPException(status_code=404, detail="File is exists")

    return {"res": "File not exists"}


@app.post("/{comic_name}/{page_id}")
def write_item(comic_name: str, page_id: str, imagefile: UploadFile):
    bt = imagefile.file.read()
    comic_name = re.sub(r'[\\/:*?"<>|#]', '', comic_name)
    root = Path(DownloadDir).joinpath(comic_name)
    if not root.exists():
        root.mkdir(parents=True)

    filepath = root.joinpath(page_id)
    if filepath.exists():
        print(f"File {filepath} is exists")
        raise HTTPException(status_code=404, detail="File is exists")

    with filepath.open("bw") as f:
        ret = CompressPic(bt)
        f.write(ret)
        print(len(ret) // 1024, len(bt) // 1024)
    return {"comic_name": comic_name, "page_id": page_id, "file_size": len(bt)}
