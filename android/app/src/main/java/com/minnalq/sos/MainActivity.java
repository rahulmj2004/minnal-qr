package com.minnalq.sos;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.media.AudioAttributes;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import java.util.Locale;

/**
 * Minnal SOS: a thin native shell around the Minnal-Q /sos screen.
 * The QAOA solver runs on the laptop server; this app sends the phone's GPS (read natively,
 * so it works over plain http on the local network) and shows the dispatch result.
 */
public class MainActivity extends Activity {
    private static final String DEFAULT_SERVER = "http://192.168.13.105:8077";
    private static final int REQ_LOCATION = 7;
    private static final int REQ_MEDIA = 8;
    private PermissionRequest pendingMedia;

    private WebView web;
    private SharedPreferences prefs;
    private Location last;
    private TextToSpeech tts;
    private boolean ttsReady;
    private Ringtone ringtone;

    private final LocationListener listener = new LocationListener() {
        @Override public void onLocationChanged(Location loc) { push(loc); }
        @Override public void onStatusChanged(String p, int s, Bundle b) {}
        @Override public void onProviderEnabled(String p) {}
        @Override public void onProviderDisabled(String p) {}
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("minnal", MODE_PRIVATE);
        getWindow().setStatusBarColor(Color.parseColor("#0B0F1A"));

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0B0F1A"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Bridge(), "MinnalApp");
        web.setWebChromeClient(new WebChromeClient() {
            // JeevaFlow vitals (camera pulse, stroke check, speech) ask for camera/microphone.
            @Override public void onPermissionRequest(final PermissionRequest req) {
                runOnUiThread(() -> {
                    if (Build.VERSION.SDK_INT >= 23 && (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
                            || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)) {
                        pendingMedia = req;
                        requestPermissions(new String[]{Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO}, REQ_MEDIA);
                    } else {
                        req.grant(req.getResources());
                    }
                });
            }
        });
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView v, String url) { if (last != null) push(last); }
            @Override public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) askServer("Could not reach the Minnal-Q server. Check the address and that the phone is on the same Wi-Fi as the laptop.");
            }
        });
        setContentView(web);

        tts = new TextToSpeech(this, status -> {
            if (status != TextToSpeech.SUCCESS) return;
            ttsReady = true;
            if (tts.isLanguageAvailable(new Locale("en", "IN")) >= TextToSpeech.LANG_AVAILABLE) tts.setLanguage(new Locale("en", "IN"));
            else tts.setLanguage(Locale.UK);
            tts.setSpeechRate(0.98f);
            tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String id) {}
                @Override public void onDone(String id) { speechDone(id); }
                @Override public void onError(String id) { speechDone(id); }
            });
        });

        askServer(null);
        startLocation();
    }

    /** Ask for the laptop server address (it changes with the Wi-Fi network). */
    private void askServer(String problem) {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(prefs.getString("server", DEFAULT_SERVER));
        new AlertDialog.Builder(this)
                .setTitle("Connect to Minnal-Q server")
                .setMessage(problem != null ? problem : "Laptop address shown by the dispatcher (same Wi-Fi):")
                .setView(input)
                .setCancelable(false)
                .setPositiveButton("Connect", (d, w) -> {
                    String url = input.getText().toString().trim();
                    if (!url.startsWith("http")) url = "http://" + url;
                    while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
                    prefs.edit().putString("server", url).apply();
                    web.loadUrl(url + "/sos");
                })
                .show();
    }

    private void startLocation() {
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_LOCATION);
            return;
        }
        LocationManager lm = (LocationManager) getSystemService(LOCATION_SERVICE);
        try {
            for (String p : new String[]{LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER}) {
                if (lm.isProviderEnabled(p)) {
                    Location l = lm.getLastKnownLocation(p);
                    if (l != null && (last == null || l.getTime() > last.getTime())) last = l;
                    lm.requestLocationUpdates(p, 2000, 0, listener);
                }
            }
            if (last != null) push(last);
        } catch (SecurityException ignored) { }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (code == REQ_LOCATION && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) startLocation();
        if (code == REQ_MEDIA && pendingMedia != null) {
            boolean ok = results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED;
            if (ok) pendingMedia.grant(pendingMedia.getResources()); else pendingMedia.deny();
            pendingMedia = null;
        }
    }

    private void push(Location loc) {
        last = loc;
        String js = "window.minnalNativeLocation && window.minnalNativeLocation(" + loc.getLatitude() + ","
                + loc.getLongitude() + "," + loc.getAccuracy() + ")";
        runOnUiThread(() -> web.evaluateJavascript(js, null));
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    private void speechDone(String id) {
        runOnUiThread(() -> web.evaluateJavascript("window.minnalSpeechDone && window.minnalSpeechDone('" + id + "')", null));
    }

    private void vibrate(long[] pattern) {
        Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
        if (v == null) return;
        v.cancel();
        if (pattern.length == 0) return;
        if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createWaveform(pattern, -1)); else v.vibrate(pattern, -1);
    }

    @Override
    protected void onDestroy() {
        if (tts != null) tts.shutdown();
        if (ringtone != null) ringtone.stop();
        try { ((LocationManager) getSystemService(LOCATION_SERVICE)).removeUpdates(listener); } catch (Exception ignored) { }
        super.onDestroy();
    }

    /** Exposed to the page as window.MinnalApp. */
    public class Bridge {
        @JavascriptInterface public String server() { return prefs.getString("server", DEFAULT_SERVER); }
        @JavascriptInterface public void changeServer() { runOnUiThread(() -> askServer(null)); }

        /** Incoming-call ringtone: the phone's own ringtone, with vibration. */
        @JavascriptInterface public void ring(boolean on) {
            runOnUiThread(() -> {
                if (ringtone != null) { ringtone.stop(); ringtone = null; }
                vibrate(new long[0]);
                if (!on) return;
                ringtone = RingtoneManager.getRingtone(MainActivity.this, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE));
                if (ringtone == null) return;
                if (Build.VERSION.SDK_INT >= 28) ringtone.setLooping(true);
                ringtone.setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                ringtone.play();
                vibrate(new long[]{0, 800, 400, 800, 400, 800, 400, 800, 400, 800});
            });
        }

        /** Speak one line of the automated call; calls window.minnalSpeechDone(id) when finished. */
        @JavascriptInterface public boolean speak(String id, String text) {
            if (!ttsReady) return false;
            tts.speak(text, TextToSpeech.QUEUE_ADD, null, id);
            return true;
        }

        @JavascriptInterface public void stopSpeech() { if (tts != null) tts.stop(); }

        @JavascriptInterface public void vibrateMs(int ms) { runOnUiThread(() -> vibrate(ms > 0 ? new long[]{0, ms} : new long[0])); }
    }
}
