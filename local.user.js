(function () {
    'use strict';
    // let img = document.getElementById('s_lg_img');

    // document.onreadystatechange = async e => {
    //     let blob = await convertImageToBlob(img);
    //     await sendImageTo("http://localhost:8000/this is my name/001.jpg", blob);
    // };
})();

const convertImageToBlob = async (img) => {
    var canvas = document.createElement("canvas");
    canvas.width = img.width;
    canvas.height = img.height;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);
    
    return new Promise( async resolve => canvas.toBlob(resolve, "image/jpg", 0.9));
}

const sendImageTo = async (url, blob) => {
    let form = new FormData();

    // this name should align with fastapi
    form.append("imagefile", blob, "test.png");

    await new Promise(resolve => {
        GM_xmlhttpRequest({
            method: "POST",
            url: url,
            data: form,
            onload: function (response) {
                resolve();
            }
        })
    });
}

const isFileExists = async (url) => {
    // this name should align with fastapi
    return await new Promise(resolve => {
        GM_xmlhttpRequest({
            method: "GET",
            url: url,
            onload: function (response) {
                // console.log("StatusCode of " + response.status);
                if (response.status != 200) {
                    resolve(false)
                }
                resolve(true);
            }
        })
    });
}