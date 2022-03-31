
# comicIds   : 漫画ID，使用' '(white space)分隔
# subDir     : 下载目录的子目录，为空的话则不创建
# albumPages : 有若干章节的漫画，填到这里，用' '(white space)分隔

# EmptyInfo 是一个空信息
EmptyInfo = {
    "comicIds": "",
    "subDir": "",
    "albumPages": ""
}

# 可同时存放多个
DownloadInfo = [
    {
        "comicIds": "",
        "subDir": "",
        "albumPages": ""
    },
    {
        "comicIds": "",
        "subDir": "",
        "albumPages": ""
    },
]

Endpoint = "https://example.com"

DownloadDir = "./"

ProxyAddress = "http://localhost:8888"

# 工作线程(协程)数量
WorkerThreadNum = 5

# 是否对图像进行修复
Reduction = True

# 若文件已经存在，是否重新下载并覆盖
ReDownload = False

# 日志文件
LogFilePath = "./logFile.log"

# Header 的文本形式，可以直接从Chrome复制过来
HeaderStr = '''
a: b
'''
