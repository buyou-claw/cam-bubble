package dev.local.camstream;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.graphics.YuvImage;
import android.hardware.Camera;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * CamStream - 把前置摄像头变成局域网 MJPEG 流
 *
 *   http://<手机IP>:8088/          状态页（纯文本）
 *   http://<手机IP>:8088/video     multipart/x-mixed-replace MJPEG
 *   http://<手机IP>:8088/snapshot  单帧 JPEG
 *
 * 注意：本文件刻意不用匿名内部类、也不用 private 的被内部类访问的成员 ——
 * 本机 build-tools 里的 d8 8.2.2-dev 在处理「匿名类 + 合成访问器(access$N)」时会抛 NPE，
 * 用普通嵌套类 + 包级可见成员可以完全避开（见 tools/build 记录）。
 */
public class MainActivity extends Activity implements SurfaceHolder.Callback {

    static final String TAG = "CamStream";
    static final int PORT = 8088;
    static final int TARGET_W = 640;
    static final int TARGET_H = 480;

    Camera camera;
    SurfaceView surfaceView;
    TextView status;
    SurfaceHolder holder;
    final Handler mainHandler = new Handler(Looper.getMainLooper());
    final AtomicReference<byte[]> latestJpeg = new AtomicReference<byte[]>(null);
    volatile byte[] cbBuffer;
    volatile int previewW = TARGET_W;
    volatile int previewH = TARGET_H;
    volatile int orientation = 0;
    volatile boolean running = true;
    volatile boolean reopening = false;
    volatile long lastFrameAt = 0;
    volatile long lastOpenAttempt = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        FrameLayout root = new FrameLayout(this);
        surfaceView = new SurfaceView(this);
        root.addView(surfaceView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        status = new TextView(this);
        status.setTextSize(16);
        status.setPadding(32, 96, 32, 32);
        status.setText("CamStream\nport " + PORT + "\nstarting...");
        root.addView(status, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT));

        setContentView(root);
        surfaceView.getHolder().addCallback(this);

        startServer();

        Thread wd = new Thread(new Watchdog(this));
        wd.setDaemon(true);
        wd.start();

        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 1);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        // MIUI 可能在我们不在前台时把相机收回去；回前台就重开
        if (camera == null && holder != null) {
            scheduleReopen(200);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            setStatus("permission ok, waiting for surface");
        } else {
            setStatus("camera permission denied");
        }
    }

    // ---------------------------------------------------------------- 状态栏
    static class StatusTask implements Runnable {
        final MainActivity app;
        final String text;

        StatusTask(MainActivity app, String text) {
            this.app = app;
            this.text = text;
        }

        public void run() {
            app.status.setText("CamStream\nhttp://<ip>:" + PORT + "/video\n" + text);
        }
    }

    void setStatus(String s) {
        runOnUiThread(new StatusTask(this, s));
    }

    // ---------------------------------------------------------------- Surface
    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        this.holder = holder;
        startCamera(holder);
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        stopCamera();
    }

    int findFrontCamera() {
        int n = Camera.getNumberOfCameras();
        Camera.CameraInfo info = new Camera.CameraInfo();
        for (int i = 0; i < n; i++) {
            Camera.getCameraInfo(i, info);
            if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT) {
                return i;
            }
        }
        return 0;
    }

    // ---------------------------------------------------------------- 相机
    static class FrameTask implements Camera.PreviewCallback {
        final MainActivity app;

        FrameTask(MainActivity app) {
            this.app = app;
        }

        public void onPreviewFrame(byte[] data, Camera cam) {
            if (data == null) {
                return;
            }
            app.lastFrameAt = SystemClock.elapsedRealtime();
            try {
                int w = app.previewW;
                int h = app.previewH;
                YuvImage yuv = new YuvImage(data, ImageFormat.NV21, w, h, null);
                ByteArrayOutputStream out = new ByteArrayOutputStream(64 * 1024);
                yuv.compressToJpeg(new Rect(0, 0, w, h), 70, out);
                app.latestJpeg.set(out.toByteArray());
            } catch (Throwable ignored) {
            } finally {
                cam.addCallbackBuffer(data);
            }
        }
    }

    void startCamera(SurfaceHolder holder) {
        if (camera != null) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            setStatus("no camera permission");
            return;
        }
        try {
            int id = findFrontCamera();
            camera = Camera.open(id);
            Camera.Parameters p = camera.getParameters();
            p.setPreviewFormat(ImageFormat.NV21);

            List<Camera.Size> sizes = p.getSupportedPreviewSizes();
            if (sizes != null && !sizes.isEmpty()) {
                Camera.Size best = sizes.get(0);
                int bestScore = Math.abs(best.width - TARGET_W) + Math.abs(best.height - TARGET_H);
                for (Camera.Size s : sizes) {
                    int score = Math.abs(s.width - TARGET_W) + Math.abs(s.height - TARGET_H);
                    if (score < bestScore) {
                        best = s;
                        bestScore = score;
                    }
                }
                previewW = best.width;
                previewH = best.height;
                p.setPreviewSize(previewW, previewH);
            }
            try {
                List<String> focus = p.getSupportedFocusModes();
                if (focus != null && focus.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_VIDEO)) {
                    p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_VIDEO);
                }
            } catch (Throwable ignored) {
            }

            camera.setParameters(p);
            camera.setDisplayOrientation(90);
            camera.setPreviewDisplay(holder);
            camera.setErrorCallback(new ErrorTask(this));

            int size = previewW * previewH * ImageFormat.getBitsPerPixel(ImageFormat.NV21) / 8;
            cbBuffer = new byte[size];
            camera.addCallbackBuffer(cbBuffer);
            camera.setPreviewCallbackWithBuffer(new FrameTask(this));
            camera.startPreview();
            lastFrameAt = SystemClock.elapsedRealtime();

            Camera.CameraInfo ci = new Camera.CameraInfo();
            Camera.getCameraInfo(id, ci);
            orientation = ci.orientation;
            setStatus("front cam " + previewW + "x" + previewH + "  sensorRot=" + orientation + "  streaming");
        } catch (Throwable t) {
            setStatus("camera error: " + t);
            stopCamera();
            try {
                if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(new String[]{Manifest.permission.CAMERA}, 1);
                }
            } catch (Throwable ignored) {
            }
        }
    }

    void stopCamera() {
        try {
            if (camera != null) {
                camera.setPreviewCallbackWithBuffer(null);
                camera.setErrorCallback(null);
                camera.stopPreview();
                camera.release();
                camera = null;
            }
        } catch (Throwable ignored) {
        }
    }

    // ---------------------------------------------------------------- 自愈
    void scheduleReopen(int delayMs) {
        if (reopening) {
            return;
        }
        reopening = true;
        mainHandler.postDelayed(new ReopenTask(this), delayMs);
    }

    static class ReopenTask implements Runnable {
        final MainActivity app;

        ReopenTask(MainActivity app) {
            this.app = app;
        }

        public void run() {
            app.reopening = false;
            try {
                app.stopCamera();
            } catch (Throwable ignored) {
            }
            if (app.holder != null) {
                app.startCamera(app.holder);
            }
        }
    }

    static class ErrorTask implements Camera.ErrorCallback {
        final MainActivity app;

        ErrorTask(MainActivity app) {
            this.app = app;
        }

        public void onError(int error, Camera cam) {
            app.setStatus("camera error code " + error + ", reopening");
            app.scheduleReopen(300);
        }
    }

    /** 2.5 秒没收到预览帧就认为相机被系统/MIUI 收走了，重开一次 */
    static class Watchdog implements Runnable {
        final MainActivity app;

        Watchdog(MainActivity app) {
            this.app = app;
        }

        public void run() {
            while (app.running) {
                try {
                    Thread.sleep(1000);
                } catch (Throwable ignored) {
                }
                long now = SystemClock.elapsedRealtime();
                long last = app.lastFrameAt;
                if (app.camera == null) {
                    // 没相机（打开失败 / 被系统收回）：每 3 秒重试一次，权限一恢复就自己接上
                    if (now - app.lastOpenAttempt > 3000) {
                        app.lastOpenAttempt = now;
                        app.scheduleReopen(0);
                    }
                } else if (last > 0 && now - last > 2500) {
                    app.setStatus("preview stalled " + ((now - last) / 1000) + "s, reopening");
                    app.scheduleReopen(0);
                }
            }
        }
    }

    // ---------------------------------------------------------------- HTTP
    static class ServerTask implements Runnable {
        final MainActivity app;

        ServerTask(MainActivity app) {
            this.app = app;
        }

        public void run() {
            ServerSocket ss = null;
            try {
                ss = new ServerSocket(PORT);
                app.setStatus("server listening on " + PORT);
                while (app.running) {
                    Socket s = ss.accept();
                    try {
                        s.setTcpNoDelay(true);
                    } catch (Throwable ignored) {
                    }
                    Thread t = new Thread(new ClientTask(app, s));
                    t.setDaemon(true);
                    t.start();
                }
            } catch (Throwable t) {
                app.setStatus("server error: " + t);
            } finally {
                try {
                    if (ss != null) {
                        ss.close();
                    }
                } catch (Throwable ignored) {
                }
            }
        }
    }

    static class ClientTask implements Runnable {
        final MainActivity app;
        final Socket socket;

        ClientTask(MainActivity app, Socket s) {
            this.app = app;
            this.socket = s;
        }

        public void run() {
            try {
                InputStream in = socket.getInputStream();
                byte[] req = new byte[2048];
                int n = in.read(req);
                String path = "/";
                if (n > 0) {
                    String head = new String(req, 0, n, StandardCharsets.ISO_8859_1);
                    int sp1 = head.indexOf(' ');
                    int sp2 = sp1 > 0 ? head.indexOf(' ', sp1 + 1) : -1;
                    if (sp1 > 0 && sp2 > sp1) {
                        path = head.substring(sp1 + 1, sp2);
                    }
                }
                OutputStream out = socket.getOutputStream();

                if (path.startsWith("/video")) {
                    byte[] hdr = ("HTTP/1.1 200 OK\r\n"
                            + "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
                            + "Cache-Control: no-cache, no-store\r\n"
                            + "Pragma: no-cache\r\n"
                            + "Connection: close\r\n"
                            + "Access-Control-Allow-Origin: *\r\n\r\n").getBytes(StandardCharsets.US_ASCII);
                    out.write(hdr);
                    while (app.running) {
                        byte[] jpg = app.latestJpeg.get();
                        if (jpg == null) {
                            Thread.sleep(30);
                            continue;
                        }
                        out.write(("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                + jpg.length + "\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                        out.write(jpg);
                        out.write("\r\n".getBytes(StandardCharsets.US_ASCII));
                        out.flush();
                        Thread.sleep(45);
                    }
                } else if (path.startsWith("/snapshot")) {
                    byte[] jpg = app.latestJpeg.get();
                    if (jpg == null) {
                        byte[] msg = "no frame yet".getBytes(StandardCharsets.US_ASCII);
                        out.write(("HTTP/1.1 503 Service Unavailable\r\nContent-Length: "
                                + msg.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                        out.write(msg);
                    } else {
                        out.write(("HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                + jpg.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                        out.write(jpg);
                    }
                } else {
                    String body = "CamStream\nport=" + PORT + "\nsize=" + app.previewW + "x" + app.previewH
                            + "\nsensor_rotation=" + app.orientation + "\nendpoints: /video /snapshot\n";
                    byte[] b = body.getBytes(StandardCharsets.US_ASCII);
                    out.write(("HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: "
                            + b.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
                    out.write(b);
                }
                out.flush();
            } catch (Throwable ignored) {
            } finally {
                try {
                    socket.close();
                } catch (Throwable ignored) {
                }
            }
        }
    }

    void startServer() {
        Thread t = new Thread(new ServerTask(this));
        t.setDaemon(true);
        t.start();
    }
}
