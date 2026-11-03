package ru.local.jarvis;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.ByteArrayInputStream;
import java.io.FilterInputStream;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

public final class Dashboard extends Activity {
    private static final String HOST = "jarvis.local";
    private static final String PAGE = "https://" + HOST + "/dashboard.html";
    private final ExecutorService requests = Executors.newFixedThreadPool(3);
    private WebView view;
    private volatile boolean closed;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        view = new WebView(this);
        view.getSettings().setJavaScriptEnabled(true);
        view.getSettings().setDomStorageEnabled(true);
        view.getSettings().setAllowFileAccess(false);
        view.getSettings().setAllowContentAccess(false);
        view.addJavascriptInterface(new Bridge(), "JarvisAndroid");
        view.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView web, WebResourceRequest request) {
                Uri url = request.getUrl();
                if (request.isForMainFrame() && request.hasGesture() && !HOST.equals(url.getHost())
                        && ("https".equals(url.getScheme()) || "http".equals(url.getScheme()))) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, url)); }
                    catch (android.content.ActivityNotFoundException ignored) {}
                }
                return true;
            }

            @Override public WebResourceResponse shouldInterceptRequest(WebView web, WebResourceRequest request) {
                Uri url = request.getUrl();
                if ("https".equals(url.getScheme()) && HOST.equals(url.getHost()) && "GET".equals(request.getMethod())) {
                    try {
                        if (request.isForMainFrame() && PAGE.equals(url.toString())) {
                            Map<String,String> headers = new HashMap<>();
                            headers.put("Content-Security-Policy",
                                "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src data: blob:; media-src data:; frame-src 'none'");
                            return new WebResourceResponse("text/html", "UTF-8", 200, "OK", headers,
                                getAssets().open("dashboard.html"));
                        }
                        if (url.getPath().matches("/dashboard/cameras/[0-9]+/live")) {
                            HttpsURLConnection connection = Net.open(Dashboard.this, url.getPath(), null);
                            try {
                                InputStream input = connection.getInputStream();
                                Map<String,String> headers = new HashMap<>();
                                for (String name : new String[]{"X-Camera-Rotation", "X-Camera-Mode"}) {
                                    String value = connection.getHeaderField(name);
                                    if (value != null) headers.put(name, value);
                                }
                                return new WebResourceResponse("application/octet-stream", null, 200, "OK", headers,
                                    new FilterInputStream(input) {
                                        @Override public void close() throws java.io.IOException {
                                            try { super.close(); } finally { connection.disconnect(); }
                                        }
                                    });
                            } catch (Exception error) { connection.disconnect(); }
                        }
                    } catch (Exception ignored) {}
                }
                return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                    null, new ByteArrayInputStream(new byte[0]));
            }
        });
        setContentView(view);
        view.loadUrl(PAGE);
    }

    private final class Bridge {
        @JavascriptInterface public void call(int id, String path, String json) {
            if (closed) return;
            requests.execute(() -> {
                JSONObject result;
                String error = null;
                try {
                    Uri url = Uri.parse(path);
                    String route = url.getPath();
                    if (url.isAbsolute() || url.getAuthority()!=null || route==null ||
                        !route.matches("/(?:developer/jobs|dashboard/(?:calendar(?:/month|/mail/[a-f0-9]+)?|day-brief|inbox|news|news-topics|background(?:/[a-f0-9-]+)?|cameras(?:/[0-9]+/processing|/recording)?|operations(?:/host|/restart|/offers|/decision/[a-f0-9]+|/draft/[a-f0-9]+)?))"))
                        throw new IllegalArgumentException("Недоступный маршрут");
                    result = Net.call(Dashboard.this, path, json == null ? null : new JSONObject(json));
                } catch (Exception failure) {
                    result = null;
                    error = Net.error(failure);
                }
                String script = "window.jarvisAndroidResult(" + id + "," +
                    (result == null ? "null" : JSONObject.quote(result.toString())) + "," +
                    (error == null ? "null" : JSONObject.quote(error)) + ")";
                runOnUiThread(() -> { if (!closed) view.evaluateJavascript(script, null); });
            });
        }
    }

    @Override protected void onDestroy() {
        closed = true;
        requests.shutdownNow();
        view.removeJavascriptInterface("JarvisAndroid");
        view.destroy();
        super.onDestroy();
    }
}
