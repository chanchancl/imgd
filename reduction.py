
from PIL import Image

def ReductionImage(image: Image.Image, column: int) -> Image.Image:
    # split the image into N column, and revert them
    # 0         N
    # 1       ...
    # 2     ->  3
    # 3         2
    # ...       1
    # N         0
    '''
    A simple example, an image with height 12[0, 12), and split it into 4 column
    12 / 4 = 3 ... 0, it is good

    column0 [0,  3)     height 3        newColumn0(column3) [0,  3), raw[9,  12),   height 3
    column1 [3,  6)     height 3  ----\ newColumn1(column2) [3,  6), raw[6,   9),   height 3
    column2 [6,  9)     height 3  ----/ newColumn2(column1) [6,  9), raw[3,   6),   height 3
    column3 [9, 12)     height 3        newColumn3(column0) [9, 12), raw[0,   3),   height 3


    But what if height % column not equal 0 ?

    Such as an image with height 13, and split it into 4 column
    so columnHeight is 13 // 4 = 3, and we also have a mod 1
    and columnN contains lines between [0 + N * columnHeight, 0 + (N + 1) * columnHeight)
    column0 [0,   3)     height 3
    column1 [3,   6)     height 3
    column2 [6,   9)     height 3
    column3 [9,  12)     height 3
            line 12      we lost it

    Inorder not lost the line 12, we have to modify column3 to [9,  12)
    then we can put column3 to the first column in new image
    newColumnN contains lines between [0 + N * columnHeight, 0 + (N + 1) * columnHeight)

    column0 [0,  3)     height 3        newColumn0(column3) [0,   4), raw[9,  13),   height 4
    column1 [3,  6)     height 3  ----\ newColumn1(column2) [4,   7), raw[6,   9),   height 3
    column2 [6,  9)     height 3  ----/ newColumn2(column1) [7,  10), raw[3,   6),   height 3
    column3 [9, 13)     height 4        newColumn3(column0) [10, 13), raw[0,   3),   height 3

    now we are clear, if we have a mod from height // column, we have to do :
    1. columnN    = [N * columnHeight, (N + 1) * columnHeight + mod]       if N == column - 1
                  = [N * columnHeight, (N + 1) * columnHeight]             if N != column - 1
    2. newColumnN = [0, columnHeight + mod]                                if N == 0
                  = [N * columnHeight + mod, (N + 1) * columnHeight + mod] if N != 0
    '''

    # create a same (mode, size) image
    newImage = Image.new(image.mode, image.size)
    width, height = image.size
    columnHeight = height // column
    mod = height % column
    # print(height, columnHeight, mod)

    for i in range(column):
        N = column - i - 1
        rawYstart = N * columnHeight
        rawYend = rawYstart + columnHeight
        if N == column - 1:  # last column in raw
            rawYend += mod

        N = i
        newYstart = N * columnHeight + mod
        newYend = newYstart + columnHeight
        if N == 0:
            newYstart, newYend = 0, columnHeight + mod
    
        try:
            # note, crop use [ ), left open right closed interval
            newImage.paste(image.crop((0, rawYstart, width, rawYend)),
                           (0, newYstart, width, newYend))
        finally:
            # print(f"{rawYstart}, {rawYend}.......{newYstart}, {newYend}")
            pass
    return newImage
