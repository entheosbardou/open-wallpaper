package org.openwallpaper.client

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.net.UnknownHostException
import java.net.SocketTimeoutException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import java.io.IOException

object Server {
 data class SyncProgress(val completed:Int,val total:Int,val currentBytes:Long=0,val currentTotal:Long=-1)
 private fun prefs(c:Context)=c.getSharedPreferences("settings",Context.MODE_PRIVATE)
 fun url(c:Context)=prefs(c).getString("url","")!!.trimEnd('/')
 fun token(c:Context)=prefs(c).getString("token","")!!
 fun configure(c:Context,url:String){prefs(c).edit().putString("url",url.trim().trimEnd('/')).remove("token").apply()}
 fun saveToken(c:Context,t:String){prefs(c).edit().putString("token",t).apply()}
 fun cachedConfig(c:Context):JSONObject?=try{JSONObject(File(c.filesDir,"scene.json").readText())}catch(_:Exception){null}
 fun cacheFile(c:Context,id:String):File {
  val key=if(id.startsWith("gallery:"))"gallery_"+id.substringAfter(':') else id
  return File(File(c.filesDir,"media").also{it.mkdirs()},key)
 }
 // Preserve the original cause so TLS, DNS, proxy and HTTP failures are actionable.
 fun describeError(error:Throwable):String {
  val chain=generateSequence(error){it.cause}.take(6).toList()
  val cause=chain.last()
  val detail=chain.mapNotNull{it.message?.takeIf(String::isNotBlank)}.distinct().joinToString(" → ")
  val category=when {
   chain.any{it is SSLHandshakeException || it is SSLPeerUnverifiedException} -> "HTTPS certificate/TLS failure"
   chain.any{it is UnknownHostException} -> "DNS lookup failed"
   chain.any{it is SocketTimeoutException} -> "Connection timed out"
   else -> error.javaClass.simpleName.ifBlank { cause.javaClass.simpleName }
  }
  return if(detail.isNotEmpty())"$category: $detail" else "$category (${cause.javaClass.name})"
 }
 fun request(c:Context,path:String,body:JSONObject?=null):JSONObject {
  val endpoint=url(c)+path
  val conn=(URL(endpoint).openConnection() as HttpURLConnection)
  conn.connectTimeout=12000;conn.readTimeout=20000
  // Do not silently turn a POST into a GET when a reverse proxy redirects it.
  conn.instanceFollowRedirects=false
  conn.setRequestProperty("Accept","application/json")
  if(token(c).isNotEmpty())conn.setRequestProperty("Authorization","Bearer "+token(c))
  try {
   if(body!=null){
    conn.requestMethod="POST";conn.doOutput=true
    conn.setRequestProperty("Content-Type","application/json; charset=utf-8")
    conn.outputStream.use{it.write(body.toString().toByteArray(Charsets.UTF_8))}
   }
   val status=conn.responseCode
   if(status in 300..399){
    val location=conn.getHeaderField("Location")?:"(no Location header)"
    throw IOException("HTTP $status redirect to $location. Set the server URL to the final HTTPS address; check reverse proxy redirects and /api routing.")
   }
   val text=(if(status in 200..299)conn.inputStream else conn.errorStream)?.bufferedReader()?.use{it.readText()}?:""
   if(status !in 200..299)throw IOException("HTTP $status from $endpoint: ${text.take(600)}")
   try{return JSONObject(text)}catch(e:Exception){throw IOException("Invalid JSON from $endpoint (HTTP $status): ${text.take(250)}",e)}
  } finally {conn.disconnect()}
 }
 fun sync(c:Context,onProgress:((SyncProgress)->Unit)?=null):JSONObject {
  val result=request(c,"/api/device/config");val scene=result.optJSONObject("scene")
  val ids=mutableSetOf<String>()
  if(scene!=null){
   val layers=scene.optJSONArray("layers")
   if(layers!=null) for(i in 0 until layers.length()){
    val layer=layers.optJSONObject(i)?:continue
    val id=layer.optString("media_id");if(id.isNotEmpty())ids.add(id)
   }
  }
  fun collect(playlist:JSONObject?){
   val arr=playlist?.optJSONArray("media_ids")?:return
   for(i in 0 until arr.length())ids.add(arr.optString(i))
  }
  collect(result.optJSONObject("playlist"))
  val linked=result.optJSONObject("playlists")
  if(linked!=null){val keys=linked.keys();while(keys.hasNext())collect(linked.optJSONObject(keys.next()))}
  val downloadable=ids.filter{it.matches(Regex("[a-fA-F0-9]{32}")) || (it.matches(Regex("gallery:[1-9][0-9]{0,18}"))&&!result.optBoolean("gallery_outage"))}
  var completed=0
  onProgress?.invoke(SyncProgress(0,downloadable.size))
  var galleryDownloadFailed=false
  for(id in downloadable){
   if(id.matches(Regex("[a-fA-F0-9]{32}")))download(c,id){bytes,total->onProgress?.invoke(SyncProgress(completed,downloadable.size,bytes,total))}
   else if(id.matches(Regex("gallery:[1-9][0-9]{0,18}"))&&!result.optBoolean("gallery_outage")){
    try{download(c,id){bytes,total->onProgress?.invoke(SyncProgress(completed,downloadable.size,bytes,total))}}catch(_:Exception){galleryDownloadFailed=true}
   }
   completed++
   onProgress?.invoke(SyncProgress(completed,downloadable.size))
  }
  if(galleryDownloadFailed){
   result.put("gallery_notice",true)
   result.put("gallery_download_failed",true)
   val cached=cachedConfig(c)
   val denied=mutableSetOf<String>()
   val missingDownloads=ids.filter{it.startsWith("gallery:")&&!File(cacheFile(c,it).absolutePath).exists()}.toSet()
   fun collectGalleryLayers(scene:JSONObject?) {
    val layers=scene?.optJSONArray("layers")?:return
    for(i in 0 until layers.length()){
     val id=layers.optJSONObject(i)?.optString("media_id")?:continue
     if(id.startsWith("gallery:"))denied.add(id)
    }
   }
   collectGalleryLayers(result.optJSONObject("scene"))
   if(cached!=null){
    val cachedIds=mutableSetOf<String>()
    fun collectCachedPlaylist(playlist:JSONObject?) {
     val arr=playlist?.optJSONArray("media_ids")?:return
     for(i in 0 until arr.length()){val id=arr.optString(i);if(id.startsWith("gallery:"))cachedIds.add(id)}
    }
    collectCachedPlaylist(cached.optJSONObject("playlist"))
    val oldLinked=cached.optJSONObject("playlists")
    if(oldLinked!=null){val keys=oldLinked.keys();while(keys.hasNext())collectCachedPlaylist(oldLinked.optJSONObject(keys.next()))}
    collectGalleryLayers(cached.optJSONObject("scene"))
    val currentIds=ids.filter{it.startsWith("gallery:")}.toSet()
    val deniedFromServer=denied.toSet()
    val keepIds=(cachedIds intersect currentIds)-deniedFromServer-missingDownloads
    val cachedTypes=cached.optJSONObject("media_types")?:JSONObject()
    val nextTypes=result.optJSONObject("media_types")?:JSONObject()
    for(id in keepIds)if(cachedTypes.has(id)&&!nextTypes.has(id))nextTypes.put(id,cachedTypes.opt(id))
    result.put("media_types",nextTypes)
    val nextScene=result.optJSONObject("scene")
    val oldScene=cached.optJSONObject("scene")
    if(nextScene!=null&&oldScene!=null){
     val nextLayers=nextScene.optJSONArray("layers")?:JSONArray()
     val oldLayers=oldScene.optJSONArray("layers")?:JSONArray()
     val present=(0 until nextLayers.length()).mapNotNull{nextLayers.optJSONObject(it)?.optString("id")}.toMutableSet()
     for(i in 0 until oldLayers.length()){
      val layer=oldLayers.optJSONObject(i)?:continue
      val id=layer.optString("media_id")
      val layerId=layer.optString("id")
      if(keepIds.contains(id)&&present.add(layerId))nextLayers.put(JSONObject(layer.toString()))
     }
     nextScene.put("layers",nextLayers)
    }
    fun mergePlaylist(oldPlaylist:JSONObject?,nextPlaylist:JSONObject?) {
     if(oldPlaylist==null||nextPlaylist==null)return
     val oldIds=oldPlaylist.optJSONArray("media_ids")?:return
     val nextIds=nextPlaylist.optJSONArray("media_ids")?:JSONArray()
     val present=(0 until nextIds.length()).map{nextIds.optString(it)}.toMutableSet()
     for(i in 0 until oldIds.length()){
      val id=oldIds.optString(i)
      if(keepIds.contains(id)&&present.add(id))nextIds.put(id)
     }
     nextPlaylist.put("media_ids",nextIds)
    }
    mergePlaylist(cached.optJSONObject("playlist"),result.optJSONObject("playlist"))
    val cachedPlaylists=cached.optJSONObject("playlists")
    val nextPlaylists=result.optJSONObject("playlists")
    if(cachedPlaylists!=null&&nextPlaylists!=null){
     val keys=cachedPlaylists.keys()
     while(keys.hasNext()){
      val key=keys.next()
      mergePlaylist(cachedPlaylists.optJSONObject(key),nextPlaylists.optJSONObject(key))
     }
    }
   }
  }
  File(c.filesDir,"scene.json").writeText(result.toString())
  return result
 }
 fun download(c:Context,id:String,onProgress:((Long,Long)->Unit)?=null):File {
  val external=id.matches(Regex("gallery:[1-9][0-9]{0,18}"))
  require(external||id.matches(Regex("[a-fA-F0-9]{32}")))
  val dest=cacheFile(c,id);val dir=dest.parentFile!!
  if(dest.exists() && dest.length()>0){onProgress?.invoke(dest.length(),dest.length());return dest}
  val temp=File(dir,dest.name+".part")
  val pathId=URLEncoder.encode(id,"UTF-8").replace("+","%20")
  val conn=(URL(url(c)+"/api/device/media/"+pathId).openConnection() as HttpURLConnection)
  conn.connectTimeout=12000;conn.readTimeout=60000;conn.setRequestProperty("Authorization","Bearer "+token(c))
  try {if(conn.responseCode!=200)throw IllegalStateException("Media HTTP ${conn.responseCode}");val total=conn.contentLengthLong;var bytes=0L;conn.inputStream.use{input->temp.outputStream().use{output->val buffer=ByteArray(64*1024);while(true){val count=input.read(buffer);if(count<0)break;output.write(buffer,0,count);bytes+=count;onProgress?.invoke(bytes,total)}}};if(!temp.renameTo(dest))throw IllegalStateException("Cannot save media");return dest}finally{conn.disconnect();temp.delete()}
 }
}
