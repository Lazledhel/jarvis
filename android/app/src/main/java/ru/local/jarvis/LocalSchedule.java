package ru.local.jarvis;
import android.app.*;import android.content.*;import android.os.*;import android.provider.Settings;import org.json.*;import java.util.*;import java.time.*;

/** Durable device-local schedules; no cloud polling or continuously running service. */
public final class LocalSchedule extends BroadcastReceiver {
 static final String PREF="local_schedules", CHANNEL="jarvis_reminders";
 static android.content.SharedPreferences prefs(Context c){return c.getSharedPreferences(PREF,0);}
 static int boot(Context c){return Settings.Global.getInt(c.getContentResolver(),Settings.Global.BOOT_COUNT,0);}
 static boolean canExact(Context c){if(Build.VERSION.SDK_INT<31)return true;try{return (Boolean)AlarmManager.class.getMethod("canScheduleExactAlarms").invoke(c.getSystemService(AlarmManager.class));}catch(Exception e){return false;}}
 static PendingIntent pending(Context c,String id){return PendingIntent.getBroadcast(c,0,new Intent(c,LocalSchedule.class).setAction("ru.local.jarvis.SCHEDULE").setData(android.net.Uri.parse("jarvis://schedule/"+id)).putExtra("id",id),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
 static void channel(Context c){NotificationManager n=c.getSystemService(NotificationManager.class);NotificationChannel ch=new NotificationChannel(CHANNEL,"Джарвис · таймеры и напоминания",NotificationManager.IMPORTANCE_HIGH);ch.enableVibration(true);ch.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);n.createNotificationChannel(ch);}
 static synchronized JSONArray list(Context c){JSONArray result=new JSONArray();for(Map.Entry<String,?> entry:prefs(c).getAll().entrySet())try{result.put(new JSONObject((String)entry.getValue()));}catch(Exception ignored){}return result;}
 static JSONObject context(Context c)throws Exception{return new JSONObject().put("version",1).put("timezone",TimeZone.getDefault().getID()).put("schedules",list(c));}
 static void arm(Context c,JSONObject item)throws Exception{
  AlarmManager manager=c.getSystemService(AlarmManager.class);
  if(!canExact(c))throw new Exception("Разрешите точные напоминания в настройках Джарвиса");
  boolean elapsed=item.optString("type").equals("timer")&&item.optInt("boot",-1)==boot(c);
  long due=elapsed?item.getLong("elapsed_due"):item.getLong("due_ms");long now=elapsed?SystemClock.elapsedRealtime():System.currentTimeMillis();
  manager.setExactAndAllowWhileIdle(elapsed?AlarmManager.ELAPSED_REALTIME_WAKEUP:AlarmManager.RTC_WAKEUP,Math.max(now+100,due),pending(c,item.getString("id")));
 }
 static synchronized String apply(Context c,JSONObject action)throws Exception{
  String id=action.getString("id");if(!id.matches("[a-f0-9]{32}"))throw new Exception("Недопустимый ID");
  if(action.optString("operation").equals("cancel")){
   String target=action.getString("target_id");if(!prefs(c).contains(target))return "Таймер или напоминание уже отсутствует";
   c.getSystemService(AlarmManager.class).cancel(pending(c,target));prefs(c).edit().remove(target).commit();return "Таймер или напоминание отменено";
  }
  if(!action.optString("operation").equals("create"))throw new Exception("Неизвестная операция");
  if(prefs(c).contains(id))return "Это напоминание уже установлено";
  if(prefs(c).getAll().size()>=100)throw new Exception("Достигнут предел: 100 напоминаний");
  channel(c);NotificationManager manager=c.getSystemService(NotificationManager.class);
  if(!manager.areNotificationsEnabled()||manager.getNotificationChannel(CHANNEL).getImportance()==NotificationManager.IMPORTANCE_NONE)throw new Exception("Разрешите уведомления Джарвиса, иначе сигнал не будет виден");
  long duration=action.optLong("duration_seconds",0);if(duration<0||duration>366L*86400)throw new Exception("Недопустимая длительность");
  long due=duration>0?System.currentTimeMillis()+duration*1000:action.getLong("due_ms"),remaining=due-System.currentTimeMillis();
  if(remaining < -60000||remaining>366L*86400000)throw new Exception("Недопустимое время напоминания");
  String label=action.getString("label"),type=action.getString("type"),repeat=action.optString("repeat","once");
  if(label.isEmpty()||label.length()>200||!Arrays.asList("timer","reminder").contains(type)||!Arrays.asList("once","daily","weekly").contains(repeat))throw new Exception("Недопустимые параметры напоминания");
  ZoneId.of(action.getString("timezone"));
  JSONObject item=new JSONObject(action.toString()).put("due_ms",due).put("boot",boot(c)).put("elapsed_due",SystemClock.elapsedRealtime()+Math.max(0,remaining));
  arm(c,item);
  if(!prefs(c).edit().putString(id,item.toString()).commit()){c.getSystemService(AlarmManager.class).cancel(pending(c,id));throw new Exception("Не удалось сохранить напоминание");}
  return (type.equals("timer")?"Таймер установлен: ":"Напоминание установлено: ")+label+" · "+Instant.ofEpochMilli(due).atZone(ZoneId.of(item.getString("timezone"))).toString();
 }
 static synchronized void restore(Context c){for(int i=0;i<list(c).length();i++)try{arm(c,list(c).getJSONObject(i));}catch(Exception e){android.util.Log.w("JarvisSchedule","restore_failed_"+e.getClass().getSimpleName());}}
 public void onReceive(Context c,Intent intent){
  if(!"ru.local.jarvis.SCHEDULE".equals(intent.getAction())){restore(c);return;}
  String id=intent.getStringExtra("id");if(id==null||!prefs(c).contains(id))return;
  synchronized(LocalSchedule.class){try{
   JSONObject item=new JSONObject(prefs(c).getString(id,"{}"));String repeat=item.optString("repeat","once");
   if(!repeat.equals("once")){
    ZonedDateTime next=Instant.ofEpochMilli(item.getLong("due_ms")).atZone(ZoneId.of(item.getString("timezone")));
    do{next=next.plusDays(repeat.equals("weekly")?7:1);}while(next.toInstant().toEpochMilli()<=System.currentTimeMillis());
    item.put("due_ms",next.toInstant().toEpochMilli());prefs(c).edit().putString(id,item.toString()).commit();try{arm(c,item);}catch(Exception e){android.util.Log.w("JarvisSchedule","repeat_restore_failed");}
   }else prefs(c).edit().remove(id).commit();
   channel(c);PendingIntent open=PendingIntent.getActivity(c,0,new Intent(c,Main.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
   c.getSystemService(NotificationManager.class).notify(id,52,new Notification.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.ic_lock_idle_alarm).setContentTitle(item.optString("type").equals("timer")?"Джарвис · таймер завершён":"Джарвис · напоминание").setContentText(item.getString("label")).setStyle(new Notification.BigTextStyle().bigText(item.getString("label"))).setContentIntent(open).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).build());
  }catch(Exception e){android.util.Log.w("JarvisSchedule","delivery_failed_"+e.getClass().getSimpleName());}}
 }
}
