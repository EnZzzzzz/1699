// wa-check: 输入手机号，返回是否注册过 WhatsApp
// 用法:
//   node check.js 8613800138000 14155552671 ...
//   node check.js numbers.txt        # 文件每行一个号码
// 首次运行会在终端显示二维码，用手机 WhatsApp「已链接的设备」扫码登录。
// 会话保存在 ./auth_info，之后无需再扫码。

const fs = require('fs');
const path = require('path');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const { createQueryRunner } = require('./retry.js');

// 多账号支持：每个账号一个独立会话目录，凭证完全隔离
//   默认:            auth_info/
//   --auth=<名字>:   auth_info-<名字>/       （CLI 便捷方式）
//   WA_AUTH_DIR:     任意目录（绝对路径，或相对 wa-check 目录；Python 原子用）
function resolveAuthDir(argv) {
  const envDir = process.env.WA_AUTH_DIR;
  if (envDir) return path.isAbsolute(envDir) ? envDir : path.join(__dirname, envDir);
  const flag = argv.find((a) => a.startsWith('--auth='));
  if (flag) {
    const name = flag.slice('--auth='.length).trim();
    if (name) return path.join(__dirname, `auth_info-${name}`);
  }
  return path.join(__dirname, 'auth_info');
}

const AUTH_DIR = resolveAuthDir(process.argv);

// 单号查询失败重试：重试次数 / 连续失败风控阈值 / 退避基值（可 env 覆盖）
const MAX_RETRIES        = parseInt(process.env.WA_QUERY_RETRIES        || '2');
const THROTTLE_THRESHOLD = parseInt(process.env.WA_THROTTLE_THRESHOLD  || '5');
const RETRY_BACKOFF_MS   = 3000;

function collectNumbers(argv) {
  const args = argv.slice(2).filter((a) => !a.startsWith('--auth='));
  if (args.length === 0) {
    console.error('用法: node check.js [--auth=<名字>] <号码1> [号码2 ...] 或 node check.js <号码文件.txt>');
    process.exit(1);
  }
  let raw = [];
  if (args.length === 1 && fs.existsSync(args[0])) {
    raw = fs.readFileSync(args[0], 'utf8').split(/\r?\n/);
  } else {
    raw = args;
  }
  // 规范化为纯数字（E.164，不带 + ）
  return raw
    .map((s) => s.replace(/\D/g, ''))
    .filter((s) => s.length >= 8 && s.length <= 15);
}

async function connectWithRetry(state, saveCreds, version, maxRetries = 5) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const sock = makeWASocket({
      version,
      auth: state,
      printQRInTerminal: false,
      browser: ['wa-check', 'CLI', '1.0.0'],
    });
    sock.ev.on('creds.update', saveCreds);

    const result = await new Promise((resolve) => {
      sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
          console.log('\n请用手机 WhatsApp → 设置 → 已链接的设备 → 链接设备，扫描下方二维码：\n');
          qrcode.generate(qr, { small: true });
          // 按账号隔离二维码文件，多账号并发登录互不覆盖
          const suffix = AUTH_DIR === path.join(__dirname, 'auth_info')
            ? '' : `-${path.basename(AUTH_DIR)}`;
          const png = path.join(__dirname, `qr${suffix}.png`);
          QRCode.toFile(png, qr, { width: 512 }).then(() => {
            console.log(`\n二维码已保存为图片: ${png}（可用手机扫码）\n`);
          });
        }
        if (connection === 'open') resolve({ ok: true });
        if (connection === 'close') {
          const code = lastDisconnect?.error?.output?.statusCode;
          if (code === DisconnectReason.loggedOut) {
            resolve({ ok: false, fatal: `已登出 (code=${code})。请删除 ${AUTH_DIR} 目录后重新扫码登录。` });
          } else {
            resolve({ ok: false, retry: true, code });
          }
        }
      });
    });

    if (result.ok) return sock;
    if (result.fatal) throw new Error(result.fatal);
    console.log(`连接中断 (code=${result.code})，第 ${attempt}/${maxRetries} 次重连...`);
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error('多次重连失败，请稍后重试。');
}

async function main() {
  const numbers = collectNumbers(process.argv);
  if (numbers.length === 0) {
    console.error('没有有效号码（需为带国家代码的国际格式，纯数字 8-15 位）');
    process.exit(1);
  }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  let sock = await connectWithRetry(state, saveCreds, version);
  console.log('已连接，开始查询...\n');

  const results = [];
  // 逐个查询并加随机延时（WA_DELAY_MIN/WA_DELAY_MAX，秒，缺省固定 1.5s），
  // 降低触发风控的概率；最后一个号码后不再等待
  const delayMin = parseFloat(process.env.WA_DELAY_MIN || '1.5');
  const delayMax = parseFloat(process.env.WA_DELAY_MAX || String(delayMin));
  const randDelay = () =>
    delayMax > delayMin
      ? (delayMin + Math.random() * (delayMax - delayMin)) * 1000
      : delayMin * 1000;
  // 单号失败：退避→重连→重试；连续失败 ≥THROTTLE_THRESHOLD 判定风控中止本批
  const runner = createQueryRunner({
    maxRetries: MAX_RETRIES,
    throttleThreshold: THROTTLE_THRESHOLD,
    backoffMs: RETRY_BACKOFF_MS,
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    reconnect: async () => {
      sock.end();
      sock = await connectWithRetry(state, saveCreds, version, 3);
    },
  });

  for (const [i, num] of numbers.entries()) {
    const r = await runner.run(num, (n) => sock.onWhatsApp(n));
    results.push(r);
    if (r.error) {
      console.log(`${num}\t⚠️ ${r.error}`);
    } else {
      console.log(`${num}\t${r.registered ? '✅ 已注册' : '❌ 未注册'}${r.jid ? `\t${r.jid}` : ''}`);
    }
    if (i < numbers.length - 1) {
      await new Promise((r2) => setTimeout(r2, randDelay()));
    }
  }

  const out = process.env.WA_RESULTS || path.join(__dirname, 'results.json');
  fs.writeFileSync(out, JSON.stringify({
    checkedAt: new Date().toISOString(), results,
    throttled: runner.isThrottled(),
  }, null, 2));
  console.log(`\n完成，共 ${results.length} 个号码。结果已保存: ${out}`);

  sock.end();
  process.exit(0);
}

main().catch((e) => {
  console.error('错误:', e.message || e);
  process.exit(1);
});
