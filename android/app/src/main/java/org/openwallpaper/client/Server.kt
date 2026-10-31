package org.openwallpaper.client

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

object Server {
 private fun prefs(c:Context)=c.getSharedPreferences("settings",Context.MODE_PRIVATE)
 fun url(c:Context)=prefs(c).getString("url","")!!.trimEnd('/')
 fun token(c:Context)=prefs(c).getString("token","")!!
 fun configure(c:Context,url:String){prefs(c).edit().putString("url",url.trim().trimEnd('/')).remove("token").apply()}
 fun saveToken(c:Context,t:String){prefs(c).edit().putString("token",t).apply()}
 fun request(c:Context,path:String,body:JSONObject?=null):JSONObject {
  val conn=(URL(url(c)+path).openConnection() as HttpURLConnection)
  conn.connectTimeout=12000;conn.readTimeout=20000
  if(token(c).isNotEmpty()) conn.setRequestProperty("Authorization","Bearer "+token(c))
  if(body!=null){conn.requestMethod="POST";conn.doOutput=true;conn.setRequestProperty("Content-Type","application/json");conn.outputStream.use{it.write(body.toString().toByteArray())}}
  try {val status=conn.responseCode;val text=(if(status in 200..299)conn.inputStream else conn.errorStream).bufferedReader().use{it.readText()};if(status !in 200..299)throw IllegalStateException("HTTP $status: $text");return JSONObject(text)} finally {conn.disconnect()}
 }
 fun sync(c:Context):JSONObject {
  val result=request(c,"/api/device/config");val scene=result.optJSONObject("scene")
  if(scene!=null){
   val layers=scene.optJSONArray("layers")
   if(layers!=null) for(i in 0 until layers.length()) {
    val layer=layers.optJSONObject(i)?:continue
    val id=layer.optString("media_id")
    if(id.isNotEmpty() && (layer.optString("type")=="image" || layer.optString("type")=="video")) download(c,id)
   }
  }
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
