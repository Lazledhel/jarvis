package ru.local.jarvis;

import android.app.Activity;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import java.io.DataInputStream;
import javax.net.ssl.HttpsURLConnection;
import android.widget.*;
import org.json.*;

public class Cameras extends Activity {
    private LinearLayout layout;
    private volatile int generation;
    private volatile boolean visible;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        setContentView(layout);
    }

    @Override protected void onResume() {
        super.onResume();
        visible = true;
        load();
    }

    @Override protected void onPause() {
        visible = false;
        generation++;
        super.onPause();
    }

    private void button(String label, Runnable action) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(view -> action.run());
        layout.addView(button);
    }

    private void load() {
        final int request = ++generation;
        layout.removeAllViews();
        new Thread(() -> {
            try {
                JSONObject data = Net.call(this, "/dashboard/cameras", null);
                runOnUiThread(() -> {
                    if (request != generation) return;
                    boolean recording = data.optBoolean("recording");
                    button(recording ? "Остановить запись" : "Запустить запись", () -> setRecording(!recording));
                    JSONArray cameras = data.optJSONArray("cameras");
                    if (cameras == null) return;
                    for (int i = 0; i < cameras.length(); i++) {
                        JSONObject camera = cameras.optJSONObject(i);
                        if (camera != null) button(camera.optString("name"), () -> watch(camera.optInt("id")));
                    }
                });
            } catch (Exception error) { report(request, error); }
        }, "JarvisCameraList").start();
    }

    private void setRecording(boolean enabled) {
        final int request = ++generation;
        layout.removeAllViews();
        new Thread(() -> {
            try {
                Net.call(this, "/dashboard/cameras/recording", new JSONObject().put("enabled", enabled));
                runOnUiThread(() -> { if (request == generation) load(); });
            } catch (Exception error) {
                report(request, error);
                runOnUiThread(() -> { if (request == generation) button("Назад к камерам", this::load); });
            }
        }, "JarvisRecording").start();
    }

    private void watch(int id) {
        final int request = ++generation;
        layout.removeAllViews();
        button("Назад к камерам", this::load);
        ImageView image = new ImageView(this);
        image.setAdjustViewBounds(true);
        layout.addView(image);
        new Thread(() -> {
            HttpsURLConnection connection = null;
            try {
                connection = Net.open(this, "/dashboard/cameras/" + id + "/live", null);
                connection.setReadTimeout(9000);
                if (connection.getResponseCode() != 200) throw new java.io.IOException("Камера недоступна");
                String angle = connection.getHeaderField("X-Camera-Rotation");
                int rotation = angle == null ? 0 : Integer.parseInt(angle);
                try (DataInputStream input = new DataInputStream(connection.getInputStream())) {
                    while (visible && request == generation) {
                        int size = input.readInt();
                        if (size < 4 || size > 2097152) throw new java.io.IOException("Некорректный кадр");
                        byte[] bytes = new byte[size];
                        input.readFully(bytes);
                        android.graphics.Bitmap frame = BitmapFactory.decodeByteArray(bytes, 0, size);
                        runOnUiThread(() -> {
                            if (request == generation) { image.setImageBitmap(frame); image.setRotation(rotation); }
                        });
                    }
                }
            } catch (Exception error) { report(request, error); }
            finally { if (connection != null) connection.disconnect(); }
        }, "JarvisCameraPreview").start();
    }

    private void report(int request, Exception error) {
        runOnUiThread(() -> {
            if (request == generation) Toast.makeText(this, Net.error(error), Toast.LENGTH_LONG).show();
        });
    }
}
