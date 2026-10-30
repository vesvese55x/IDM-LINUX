<?php
/**
 * IDM-Linux v2.9.1 — Uzak Teşhis Log Sunucusu (tek dosya)
 * Kurulum: bu dosyayı sitenize yükleyin (örn. https://siteniz.com/idmlog/index.php),
 * aşağıda TOKEN'i belirleyin; klasör yazılabilir olsun (logs/ otomatik oluşur).
 * Sonra Linux tarafında ~/.config/idm-linux/config.json:
 *   "remote_log_url": "https://siteniz.com/idmlog/index.php",
 *   "remote_log_token": "AYNI_TOKEN"
 * GUI > Doktor > "📡 Uzak Log'a Gönder" anında yollar; daemon 20 sn'de bir kendisi de basar.
 * Web'den "Logları İzle" butonu canlı takip eder (3 sn otomatik yenileme).
 */
define('TOKEN', 'IDM_LINUX_2091_DIAG');   // <-- BURAYI DEĞİŞTİRİN
define('LOGDIR', __DIR__ . '/logs');

header('Content-Type: application/json; charset=utf-8');
if (!is_dir(LOGDIR)) { @mkdir(LOGDIR, 0775, true); }

$action = $_GET['action'] ?? 'ingest';

// 1) Daemon/GUI/eklenti log yutar
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $in = json_decode(file_get_contents('php://input'), true);
    if (!$in || ($in['token'] ?? '') !== TOKEN) {
        http_response_code(403);
        echo json_encode(['ok' => false, 'error' => 'bad token']);
        exit;
    }
    $src = preg_replace('/[^a-z0-9_-]/i', '', $in['source'] ?? 'daemon') ?: 'daemon';
    $lines = is_array($in['lines'] ?? null) ? $in['lines'] : [];
    $f = LOGDIR . '/' . $src . '.log';
    $fh = fopen($f, 'a');
    if ($fh) {
        $ts = date('Y-m-d H:i:s');
        foreach ($lines as $ln) {
            fwrite($fh, "[$ts] " . str_replace(["\r", "\n"], ' ', substr((string)$ln, 0, 500)) . "\n");
        }
        fclose($fh);
        // 2 MB üstü kırpp
        if (filesize($f) > 2 * 1024 * 1024) {
            $tail = file($f); $tail = array_slice($tail, -3000);
            file_put_contents($f, implode('', $tail));
        }
    }
    echo json_encode(['ok' => true, 'stored' => count($lines)]);
    exit;
}

// 2) Web arayüzü: Logları İzle
if ($action === 'view') {
    header('Content-Type: text/html; charset=utf-8');
    $tok = $_GET['token'] ?? '';
    if ($tok !== TOKEN) { http_response_code(403); exit('bad token'); }
    $src = preg_replace('/[^a-z0-9_-]/i', '', $_GET['src'] ?? 'daemon') ?: 'daemon';
    $f = LOGDIR . '/' . $src . '.log';
    $lines = is_file($f) ? array_slice(file($f), -400) : [];
    echo '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="3">
    <title>IDM-Linux Uzak Log</title>
    <style>body{background:#0b1120;color:#e2e8f0;font:12px monospace;padding:16px}
    h1{color:#38bdf8;font:16px sans-serif}a{color:#34d399}
    pre{white-space:pre-wrap;background:#131c31;padding:10px;border-radius:8px}</style></head><body>
    <h1>📡 IDM-Linux Uzak Teşhis — kaynak: ' . htmlspecialchars($src) . '</h1>
    <p>Kaynaklar: ';
    foreach (glob(LOGDIR . '/*.log') ?: [] as $g) {
        $n = basename($g, '.log');
        echo '<a href="?action=view&token=' . urlencode($tok) . '&src=' . urlencode($n) . '">' . htmlspecialchars($n) . '</a> ';
    }
    echo ' | <a href="?action=view&token=' . urlencode($tok) . '&src=' . urlencode($src) . '">🔄 Yenile</a></p>
    <pre>' . htmlspecialchars(implode('', $lines)) . '</pre></body></html>';
    exit;
}

// 3) JSON tail (scriptlerle tüketim)
$src = preg_replace('/[^a-z0-9_-]/i', '', $_GET['src'] ?? 'daemon') ?: 'daemon';
$tok = $_GET['token'] ?? '';
if ($tok !== TOKEN) { http_response_code(403); echo json_encode(['ok' => false]); exit; }
$f = LOGDIR . '/' . $src . '.log';
echo json_encode(['ok' => true, 'lines' => is_file($f) ? array_slice(file($f), -200) : []]);
