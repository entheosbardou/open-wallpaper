package org.openwallpaper.client

import android.app.Activity
import android.app.WallpaperManager
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.graphics.Color
import android.view.Gravity
import android.widget.*
import org.json.JSONObject
import android.net.Uri
import com.google.zxing.integration.android.IntentIntegrator
import com.google.zxing.integration.android.IntentResult
import kotlin.concurrent.thread

class MainActivity:Activity(){
 private val main=Handler(Looper.getMainLooper())
 private lateinit var status:TextView
 private lateinit var code:TextView
 private var pairingCode=""
 private var waiting=false
 override fun onCreate(savedInstanceState:Bundle?){super.onCreate(savedInstanceState)
  val layout=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(32,36,32,24);setBackgroundColor(Color.rgb(14,22,37))}
  fun label(t:String,size:Float=16f)=TextView(this).apply{text=t;textSize=size;setTextColor(Color.WHITE);setPadding(0,8,0,8)}
  fun button(t:String,action:()->Unit)=Button(this).apply{text=t;setOnClickListener{action()}}
  layout.addView(label("Open Wallpaper",28f));layout.addView(label("Connect to your self-hosted server. Your device must be able to reach its address."))
  val address=EditText(this).apply{setSingleLine();setText(Server.url(this@MainActivity));hint="http://192.168.1.20:8080";setTextColor(Color.WHITE);setHintTextColor(Color.LTGRAY);inputType=android.text.InputType.TYPE_TEXT_VARIATION_URI}
  layout.addView(address)
  status=label(if(Server.token(this).isNotEmpty())"Paired. Ready to sync." else "Not paired")
  code=label("",20f)
  layout.addView(button("Scan pairing QR code") {
   IntentIntegrator(this).apply{setDesiredBarcodeFormats(IntentIntegrator.QR_CODE);setPrompt("Scan QR code from your Open Wallpaper dashboard");setBeepEnabled(false);setOrientationLocked(false)}.initiateScan()
  })
  layout.addView(label("Or pair manually using a code:",14f))
  layout.addView(button("1. Connect and get pairing code"){
   val url=address.text.toString().trim();if(!url.startsWith("http://")&&!url.startsWith("https://")){status.text="Enter an http:// or https:// URL";return@button}
   Server.configure(this,url);status.text="Connecting…"
   runAsync { val obj=Server.request(this,"/api/pairing",JSONObject().put("name",android.os.Build.MANUFACTURER+" "+android.os.Build.MODEL));pairingCode=obj.getString("code");main.post{code.text="Pairing code: $pairingCode";status.text="Approve this code in the server dashboard (expires in 10 minutes)."};waiting=true;poll() }
  })
  layout.addView(code);layout.addView(status)
  layout.addView(button("2. Check pairing approval") {if(pairingCode.isNotEmpty())poll() else status.text="Request a pairing code first."})
  layout.addView(button("3. Sync assigned scene") {runAsync{val result=Server.sync(this);main.post{status.text=if(result.isNull("scene") && result.isNull("playlist"))"Paired, but no wallpaper assigned. Assign a scene or playlist in the dashboard." else "Wallpaper synced and cached."}}})
  layout.addView(button("4. Set live wallpaper") {startActivity(Intent(WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER).putExtra(WallpaperManager.EXTRA_LIVE_WALLPAPER_COMPONENT,android.content.ComponentName(this,Wallpaper::class.java)))})
  layout.addView(label("Tip: use the server's LAN IP, not localhost. HTTP is intended for trusted LANs only; use HTTPS for remote access.",13f))
  setContentView(ScrollView(this).apply{addView(layout)})
 }
 private fun runAsync(job:()->Unit){thread{try{job()}catch(e:Exception){main.post{status.text="Error: ${e.message}"}}}}
 override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
  val scan=IntentIntegrator.parseActivityResult(requestCode,resultCode,data)
  if(scan!=null){
   val contents=scan.contents
   if(contents.isNullOrEmpty()){status.text="QR scan cancelled";return}
   try{
    val uri=Uri.parse(contents)
    if(uri.scheme!="openwallpaper" || uri.host!="pair")throw IllegalArgumentException("Not an Open Wallpaper pairing QR")
    val server=uri.getQueryParameter("server")?:throw IllegalArgumentException("Missing server")
    val token=uri.getQueryParameter("token")?:throw IllegalArgumentException("Missing token")
    if(!server.startsWith("http://")&&!server.startsWith("https://"))throw IllegalArgumentException("Invalid server address")
    Server.configure(this,server);status.text="Pairing with $server…"
    runAsync{
     val result=Server.request(this,"/api/pairing/qr/claim",JSONObject().put("token",token).put("name",android.os.Build.MANUFACTURER+" "+android.os.Build.MODEL))
     Server.saveToken(this,result.getString("token"))
     main.post{waiting=false;status.text="Paired! Assign a scene or playlist in the dashboard, then sync."}
    }
   }catch(e:Exception){status.text="Invalid QR: ${e.message}"}
   return
  }
  super.onActivityResult(requestCode,resultCode,data)
 }
 private fun poll(){
  if(!waiting || pairingCode.isEmpty())return
  runAsync{
   val result=Server.request(this,"/api/pairing/claim",JSONObject().put("code",pairingCode))
   if(!result.optBoolean("pending",true)){
    Server.saveToken(this,result.getString("token"));waiting=false
    main.post{status.text="Paired! Assign a scene or playlist, then sync."}
   }else main.post{status.text="Awaiting approval…";if(waiting)main.postDelayed({poll()},2500)}
  }
 }
}
