package org.openwallpaper.client

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.UnknownHostException
import java.net.SocketTimeoutException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import java.io.IOException

object Server {
 private fun prefs(c:Context)=c.getSharedPreferences("settings",Context.MODE_PRIVATE)
 fun url(c:Context)=prefs(c).getString("url","")!!.trimEnd('/')
 fun token(c:Context)=prefs(c).getString("token","")!!
 fun configure(c:Context,url:String){prefs(c).edit().putString("url",url.trim().trimEnd('/')).remove("token").apply()}
 fun saveToken(c:Context,t:String){prefs(c).edit().putString("token",t).apply()}
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
 fun sync(c:Context):JSONObject {
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
  for(id in ids)if(id.matches(Regex("[a-fA-F0-9]{32}")))download(c,id)
  File(c.filesDir,"scene.json").writeText(result.toString())
  return result
 }
 fun download(c:Context,id:String):File {
  require(id.matches(Regex("[a-fA-F0-9]{32}")))
  val dir=File(c.filesDir,"media").also{it.mkdirs()};val dest=File(dir,id)
  if(dest.exists() && dest.length()>0)return dest
  val temp=File(dir,"$id.part")
  val conn=(URL(url(c)+"/api/device/media/"+id).openConnection() as HttpURLConnection)
  conn.connectTimeout=12000;conn.readTimeout=60000;conn.setRequestProperty("Authorization","Bearer "+token(c))
  try {if(conn.responseCode!=200)throw IllegalStateException("Media HTTP ${conn.responseCode}");conn.inputStream.use{input->temp.outputStream().use{output->input.copyTo(output)}};if(!temp.renameTo(dest))throw IllegalStateException("Cannot save media");return dest}finally{conn.disconnect();temp.delete()}
 }
}
