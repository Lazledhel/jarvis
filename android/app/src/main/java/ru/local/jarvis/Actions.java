package ru.local.jarvis;
import android.app.*;import android.content.*;import android.net.*;import android.os.*;import android.provider.Settings;import org.json.*;import java.util.*;
final class Actions{
 static class Item{JSONObject action;String session;long created=SystemClock.elapsedRealtime();Item(JSONObject a,String s){action=a;session=s;}}
 static final Map<String,Item> pending=new HashMap<>();
 static synchronized Item take(String id){Item item=pending.remove(id);return item!=null&&SystemClock.elapsedRealtime()-item.created<120000?item:null;}
 static void report(Context c,Item item,String result){new Thread(()->{try{Net.call(c,"/action-result",new JSONObject().put("conversation_id",item.session).put("action_id",item.action.optString("id")).put("result",result));}catch(Exception ignored){}}).start();}
 static boolean vpnActive(Context c){try{ConnectivityManager m=(ConnectivityManager)c.getSystemService(Context.CONNECTIVITY_SERVICE);NetworkCapabilities caps=m.getNetworkCapabilities(m.getActiveNetwork());return caps!=null&&caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN);}catch(Exception e){return false;}}
 static void offer(Context c,JSONObject action,String session)throws Exception{
  boolean en=action.optString("language").equals("en");String kind=action.optString("kind"),id=action.optString("id");if(!id.matches("[a-f0-9]{32}"))throw new Exception("Недопустимое действие");Item item=new Item(action,session);
  if(kind.equals("vpn")){
   if(!action.has("enabled"))throw new Exception("Не указано состояние VPN");boolean enable=action.getBoolean("enabled");
   if(vpnActive(c)==enable){Assistant.status=enable?(en?"VPN is already connected":"VPN уже подключён"):(en?"VPN is already disconnected":"VPN уже отключён");report(c,item,Assistant.status);return;}
   Bundle b=new Bundle();b.putBoolean("tasker_extra_bundle_switch",enable);b.putString("tasker_extra_bundle_guid","Default");c.sendBroadcast(new Intent("com.twofortyfouram.locale.intent.action.FIRE_SETTING").setComponent(new ComponentName("com.v2raytun.android","com.v2raytun.android.receiver.TaskerReceiver")).putExtra("com.twofortyfouram.locale.intent.extra.BUNDLE",b));
   boolean matched=false;int stable=0;for(int n=0;n<24;n++){Thread.sleep(350);stable=vpnActive(c)==enable?stable+1:0;if(stable>=3){matched=true;break;}}
   String result=matched?(enable?(en?"VPN connected":"VPN подключён"):(en?"VPN disconnected":"VPN отключён")):(en?"VPN command sent; state change was not confirmed":"Команда VPN отправлена, изменение состояния не подтверждено");Assistant.last+="\n\n"+result;Assistant.status=result;report(c,item,result);return;
  }
  if(!kind.equals("call")&&!kind.equals("route"))throw new Exception("Действие не поддерживается");
  synchronized(Actions.class){pending.clear();pending.put(id,item);}
  NotificationManager nm=c.getSystemService(NotificationManager.class);nm.createNotificationChannel(new NotificationChannel("actions","Джарвис · действия",NotificationManager.IMPORTANCE_HIGH));
  Intent intent=new Intent(c,ActionScreen.class).putExtra("id",id).putExtra("language",action.optString("language","ru")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
  PendingIntent pi=PendingIntent.getActivity(c,83,intent,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  String title=kind.equals("call")?(en?"Confirm call":"Подтвердить звонок"):(en?"Open directions":"Открыть маршрут");
  nm.notify(83,new Notification.Builder(c,"actions").setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle(title).setContentText(action.optString("target")).setContentIntent(pi).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).setTimeoutAfter(120000).build());
  if(Main.foreground||Settings.canDrawOverlays(c))try{c.startActivity(intent);}catch(Exception ignored){}
 }
 static Uri route(JSONObject a)throws Exception{
  String target=a.getString("target");if(target.isEmpty()||target.length()>300)throw new Exception("Нет пункта назначения");String mode=a.optString("transport","driving");if(!Arrays.asList("driving","walking","transit").contains(mode))throw new Exception("Неизвестный вид маршрута");
  if(a.optString("map_provider").equals("yandex")){if(!a.has("latitude")||!a.has("longitude"))throw new Exception("Координаты не определены");String m=mode.equals("walking")?"pd":mode.equals("transit")?"mt":"auto";return Uri.parse("yandexmaps://maps.yandex.ru/").buildUpon().appendQueryParameter("rtext","~"+a.getDouble("latitude")+","+a.getDouble("longitude")).appendQueryParameter("rtt",m).build();}
  return Uri.parse("https://www.google.com/maps/dir/").buildUpon().appendQueryParameter("api","1").appendQueryParameter("destination",target).appendQueryParameter("travelmode",mode).build();
 }
}
