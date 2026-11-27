package app.starfire.webapp

import org.json.JSONObject

object DownloadScript {
    const val LISTENER_NAME = "starfireDownload"
    private const val CHUNK_BYTES = 196608

    fun forBlob(blobUrl: String, fileName: String): String =
        "(function(url,name){" +
            "var port=$LISTENER_NAME;var chunk=$CHUNK_BYTES;var stopped=false;" +
            "port.onmessage=function(e){if(e.data==='stop'){stopped=true;}};" +
            "fetch(url).then(function(r){return r.blob();}).then(function(blob){" +
            "port.postMessage('S\\n'+blob.size+'\\n'+(blob.type||'')+'\\n'+name);" +
            "var offset=0;" +
            "function next(){" +
            "if(stopped){port.postMessage('X');return;}" +
            "if(offset>=blob.size){port.postMessage('E');return;}" +
            "var reader=new FileReader();" +
            "reader.onload=function(){var text=reader.result;" +
            "port.postMessage('C\\n'+text.substring(text.indexOf(',')+1));offset+=chunk;next();};" +
            "reader.onerror=function(){port.postMessage('X');};" +
            "reader.readAsDataURL(blob.slice(offset,offset+chunk));}" +
            "next();" +
            "}).catch(function(){port.postMessage('X');});" +
            "})(${JSONObject.quote(blobUrl)},${JSONObject.quote(fileName)});"
}
