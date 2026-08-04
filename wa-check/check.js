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

const AUTH_DIR = path.join(__dirname, 'auth_info');

function collectNumbers(argv) {
  const args = argv.slice(2);
  if (args.length === 0) {
    console.error('用法: node check.js <号码1> [号码2 ...] 或 node check.js <号码文件.txt>');
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
          const png = path.join(__dirname, 'qr.png');
          QRCode.toFile(png, qr, { width: 512 }).then(() => {
            console.log(`\n二维码已保存为图片: ${png}（可用手机扫码）\n`);
          });
        }
        if (connection === 'open') resolve({ ok: true });
        if (connection === 'close') {
          const code = lastDisconnect?.error?.output?.statusCode;
          if (code === DisconnectReason.loggedOut) {
            resolve({ ok: false, fatal: `已登出 (code=${code})。请删除 auth_info 目录后重新扫码登录。` });
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

  const sock = await connectWithRetry(state, saveCreds, version);
  console.log('已连接，开始查询...\n');

  const results = [];
  // 逐个查询并加延时，降低触发风控的概率
  for (const num of numbers) {
    try {
      const res = await sock.onWhatsApp(num);
      const hit = res && res[0];
      results.push({
        number: num,
        registered: !!hit?.exists,
        jid: hit?.jid || null,
      });
      console.log(`${num}\t${hit?.exists ? '✅ 已注册' : '❌ 未注册'}${hit?.jid ? `\t${hit.jid}` : ''}`);
    } catch (e) {
      results.push({ number: num, registered: null, error: String(e.message || e) });
      console.log(`${num}\t⚠️ 查询失败: ${e.message || e}`);
    }
    await new Promise((r) => setTimeout(r, 1500));
  }

  const out = process.env.WA_RESULTS || path.join(__dirname, 'results.json');
  fs.writeFileSync(out, JSON.stringify({ checkedAt: new Date().toISOString(), results }, null, 2));
  console.log(`\n完成，共 ${results.length} 个号码。结果已保存: ${out}`);

  sock.end();
  process.exit(0);
}

main().catch((e) => {
  console.error('错误:', e.message || e);
  process.exit(1);
});
