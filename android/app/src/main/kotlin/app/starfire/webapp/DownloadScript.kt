package app.starfire.webapp

import org.json.JSONObject

object DownloadScript {
    const val LISTENER_NAME = "starfireDownload"
    private const val CHUNK_BYTES = 196608
    private const val WINDOW = 4

    const val NAME_RECORDER =
        "(function(){var names={};window.__starfireNames=names;" +
            "document.addEventListener('click',function(e){" +
            "var node=e.target;" +
            "while(node&&node.nodeType===1&&node.tagName!=='A'){node=node.parentNode;}" +
            "if(node&&node.tagName==='A'&&node.hasAttribute('download')&&node.href.indexOf('blob:')===0){" +
            "names[node.href]=node.getAttribute('download');}},true);})();"

    fun forBlob(blobUrl: String, fileName: String, id: Int): String =
        "(function(url,fallbackName,id){" +
            "var port=$LISTENER_NAME;var chunk=$CHUNK_BYTES;var windowSize=$WINDOW;" +
            "var inflight=0;var offset=0;var reading=false;var finished=false;var stopped=false;var blob=null;" +
            "function post(kind,extra){port.postMessage(kind+'\\n'+id+(extra===undefined?'':'\\n'+extra));}" +
            "function release(){finished=true;blob=null;port.removeEventListener('message',onMessage);}" +
            "function end(kind){if(!finished){post(kind);release();}}" +
            "function pump(){" +
            "if(finished||blob===null){return;}" +
            "if(stopped){release();return;}" +
            "if(!reading&&inflight<windowSize&&offset<blob.size){readNext();return;}" +
            "if(offset>=blob.size&&inflight===0&&!reading){end('E');}}" +
            "function readNext(){reading=true;var reader=new FileReader();" +
            "reader.onload=function(){if(finished||blob===null){return;}var text=reader.result;" +
            "post('C',text.substring(text.indexOf(',')+1));offset+=chunk;inflight++;reading=false;pump();};" +
            "reader.onerror=function(){end('X');};" +
            "reader.readAsDataURL(blob.slice(offset,offset+chunk));}" +
            "function onMessage(e){" +
            "if(e.data==='stop:'+id){stopped=true;if(!reading){release();}}" +
            "else if(e.data==='ack:'+id){if(blob===null){return;}if(inflight>0){inflight--;}pump();}}" +
            "port.addEventListener('message',onMessage);" +
            "var recorded=(window.__starfireNames||{})[url];" +
            "var name=recorded||fallbackName;" +
            "fetch(url).then(function(r){return r.blob();}).then(function(result){" +
            "if(finished){return;}" +
            "blob=result;post('S',blob.size+'\\n'+(blob.type||'')+'\\n'+name);" +
            "}).catch(function(){end('X');});" +
            "})(${JSONObject.quote(blobUrl)},${JSONObject.quote(fileName)},$id);"
}
