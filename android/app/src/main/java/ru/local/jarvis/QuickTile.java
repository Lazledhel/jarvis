package ru.local.jarvis;
import android.service.quicksettings.*;import android.content.Intent;
public class QuickTile extends TileService{public void onStartListening(){getQsTile().setState(Tile.STATE_ACTIVE);getQsTile().updateTile();}public void onClick(){startActivityAndCollapse(new Intent(this,Main.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("listen",true));}}
