package org.openwallpaper.client

import android.graphics.*
import android.media.MediaPlayer
import android.os.Handler
import android.os.HandlerThread
import android.service.wallpaper.WallpaperService
import android.view.SurfaceHolder
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

class Wallpaper:WallpaperService(){
 override fun onCreateEngine():Engine=Renderer()
 inner class Renderer:Engine(){
  private val worker=HandlerThread("wallpaper-render").apply{start()}
  private val handler=Handler(worker.looper)
  private var visible=false
  private var scene:JSONObject?=null
  private var player:MediaPlayer?=null
  private var videoId:String?=null
  private val paint=Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
  private val tick=object:Runnable{override fun run(){if(!visible)return;draw();handler.postDelayed(this,1000)}}
  private val refresh=object:Runnable{override fun run(){if(!visible)return;thread{try{Server.sync(this@Wallpaper);handler.post{load()}}catch(_:Exception){}};handler.postDelayed(this,60000)}}
  override fun onVisibilityChanged(v:Boolean){visible=v;if(v){load();handler.removeCallbacks(tick);handler.post(tick);handler.post(refresh);player?.start()}else{handler.removeCallbacks(tick);handler.removeCallbacks(refresh);player?.pause()}}
  override fun onSurfaceChanged(h:SurfaceHolder,f:Int,w:Int,he:Int){super.onSurfaceChanged(h,f,w,he);handler.post{load();draw()}}
  private fun load(){try{scene=JSONObject(File(filesDir,"scene.json").readText()).optJSONObject("scene")}catch(_:Exception){scene=null};setupVideo()}
  private fun setupVideo(){val layers=scene?.optJSONArray("layers");var id:String?=null;if(layers!=null)for(i in 0 until layers.length()){val layer=layers.optJSONObject(i)?:continue;if(layer.optString("type")=="video"){id=layer.optString("media_id");break}}
   if(id==videoId)return;player?.release();player=null;videoId=id
   if(id!=null)try{val file=File(filesDir,"media/$id");if(file.exists()){player=MediaPlayer().apply{setDataSource(file.absolutePath);setSurface(surfaceHolder.surface);isLooping=true;prepare();if(visible)start()}}}catch(_:Exception){player?.release();player=null}
  }
  private fun draw(){if(!surfaceHolder.surface.isValid)return
   // A video scene uses the video surface directly; do not overwrite its frames with Canvas.
   if(player!=null)return
   var canvas:Canvas?=null
   try{canvas=surfaceHolder.lockCanvas();val c=canvas?:return;c.drawColor(Color.rgb(12,20,34));val layers=scene?.optJSONArray("layers")
    if(layers==null){paint.color=Color.WHITE;paint.textSize=42f;c.drawText("Open Wallpaper: assign and sync a scene",30f,c.height/2f,paint);return}
    val sorted=(0 until layers.length()).mapNotNull{layers.optJSONObject(it)}.sortedBy{it.optInt("zIndex",0)}
    for(layer in sorted){when(layer.optString("type")){
     "image"->{val file=File(filesDir,"media/"+layer.optString("media_id"));if(!file.exists())continue
      val bitmap=BitmapFactory.decodeFile(file.absolutePath)?:continue
      try{val scale=maxOf(c.width.toFloat()/bitmap.width,c.height.toFloat()/bitmap.height);val w=bitmap.width*scale;val h=bitmap.height*scale;paint.alpha=(layer.optDouble("opacity",1.0).coerceIn(0.0,1.0)*255).toInt();c.drawBitmap(bitmap,null,RectF((c.width-w)/2,(c.height-h)/2,(c.width+w)/2,(c.height+h)/2),paint)}finally{bitmap.recycle()}
     }
     "clock"->{paint.color=Color.WHITE;paint.alpha=255;paint.textAlign=Paint.Align.CENTER;paint.textSize=64f;val clock=SimpleDateFormat("HH:mm",Locale.getDefault()).format(Date());c.drawText(clock,c.width/2f,c.height*0.2f,paint);paint.textAlign=Paint.Align.LEFT}
    }}
   }catch(_:Exception){}finally{if(canvas!=null)try{surfaceHolder.unlockCanvasAndPost(canvas)}catch(_:Exception){}}
  }
  override fun onDestroy(){visible=false;handler.removeCallbacksAndMessages(null);player?.release();worker.quitSafely();super.onDestroy()}
 }
}
