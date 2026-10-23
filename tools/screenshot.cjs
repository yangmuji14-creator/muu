#!/usr/bin/env node
/**
 * screenshot.js — 用 CDP 驱动本机 Chrome 给 WebUI 截图。
 *
 * 为什么不用 puppeteer/playwright：
 *   两者都要下载 ~150MB 的 Chromium，而这台机器已经有 Chrome。
 *   CDP 直接连本机 Chrome 的 remote debugging 端口即可，零额外二进制。
 *
 * 用法：
 *   node tools/screenshot.js --url http://127.0.0.1:8000/ --out docs/screenshots/x.png
 *   node tools/screenshot.js --url ... --out ... --theme dark --width 1440 --height 1000
 *   node tools/screenshot.js --url ... --out ... --hash '#/settings/model'
 *
 * 依赖 ws（仅用于 CDP WebSocket）。若 node_modules 里没有，脚本会提示：
 *   npm i -D ws
 */

const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  if (i === -1) return def;
  const v = process.argv[i + 1];
  return v && !v.startsWith('--') ? v : true;
}

const URL_ARG = arg('url', 'http://127.0.0.1:8000/');
const OUT = arg('out', 'shot.png');
const THEME = arg('theme', null);          // light | dark | null(不改)
const WIDTH = parseInt(arg('width', '1440'), 10);
const HEIGHT = parseInt(arg('height', '1000'), 10);
const HASH = arg('hash', null);
const WAIT = parseInt(arg('wait', '1800'), 10);
const PORT = parseInt(arg('port', '9333'), 10);
const EVAL = arg('eval', null);            // 截图前注入的 JS，用于 A/B 试验

const CHROME_CANDIDATES = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
];

function findChrome() {
  for (const p of CHROME_CANDIDATES) if (fs.existsSync(p)) return p;
  throw new Error('找不到 Chrome/Edge 可执行文件');
}

let WebSocket;
try {
  WebSocket = require('ws');
} catch {
  console.error('缺少依赖 ws。请先运行:  cd tools && npm i ws');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function httpJson(urlPath) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: '127.0.0.1', port: PORT, path: urlPath }, (res) => {
        let buf = '';
        res.on('data', (c) => (buf += c));
        res.on('end', () => {
          try {
            resolve(JSON.parse(buf));
          } catch (e) {
            reject(new Error('JSON 解析失败: ' + buf.slice(0, 200)));
          }
        });
      })
      .on('error', reject);
  });
}

/** 极简 CDP 客户端：一次连接、顺序发命令、按 id 匹配回包。 */
class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.on('message', (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error('CDP 超时: ' + method));
        }
      }, 30000);
    });
  }
}

async function main() {
  const chrome = findChrome();
  const userDataDir = path.join(
    process.env.TEMP || '/tmp',
    'cc-shot-' + Date.now()
  );

  const child = spawn(
    chrome,
    [
      '--headless=new',
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${userDataDir}`,
      `--window-size=${WIDTH},${HEIGHT}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
      '--hide-scrollbars',
      '--force-device-scale-factor=1',
      'about:blank',
    ],
    { stdio: 'ignore', detached: false }
  );

  // 等 CDP 端口就绪
  let target = null;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try {
      const list = await httpJson('/json/list');
      target = list.find((t) => t.type === 'page');
      if (target) break;
    } catch {
      /* 端口还没开 */
    }
  }
  if (!target) {
    child.kill();
    throw new Error('Chrome CDP 端口未就绪（' + PORT + '）');
  }

  const ws = new WebSocket(target.webSocketDebuggerUrl, {
    perMessageDeflate: false,
    maxPayload: 256 * 1024 * 1024,
  });
  await new Promise((res, rej) => {
    ws.once('open', res);
    ws.once('error', rej);
  });
  const cdp = new CDP(ws);

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: WIDTH,
    height: HEIGHT,
    deviceScaleFactor: 1,
    mobile: false,
  });

  // 主题要在导航前写进 localStorage，否则页面按默认值先渲染一帧
  if (THEME) {
    const origin = new URL(URL_ARG).origin;
    await cdp.send('Page.navigate', { url: origin + '/__theme_probe__' }).catch(() => {});
    await sleep(300);
    await cdp.send('Runtime.evaluate', {
      expression: `localStorage.setItem('cc-theme', ${JSON.stringify(THEME)})`,
    });
  }

  const fullUrl = URL_ARG + (HASH || '');
  await cdp.send('Page.navigate', { url: fullUrl });
  await sleep(WAIT);

  // 等字体与图片稳定，避免截到半渲染状态
  await cdp.send('Runtime.evaluate', {
    expression: 'document.fonts ? document.fonts.ready.then(()=>true) : true',
    awaitPromise: true,
  }).catch(() => {});
  await sleep(300);

  // A/B 试验注入：改 CSS 变量后必须等一帧，否则截到的是旧值
  if (EVAL) {
    const r = await cdp.send('Runtime.evaluate', {
      expression: String(EVAL),
      returnByValue: true,
      awaitPromise: true,
    });
    if (r.exceptionDetails) {
      throw new Error('--eval 抛错: ' + JSON.stringify(r.exceptionDetails.text));
    }
    if (r.result && r.result.value !== undefined) {
      console.log('eval →', JSON.stringify(r.result.value));
    }
    await sleep(600);
  }

  const shot = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });

  fs.mkdirSync(path.dirname(path.resolve(OUT)), { recursive: true });
  fs.writeFileSync(OUT, Buffer.from(shot.data, 'base64'));

  ws.close();
  child.kill();
  await sleep(200);
  try {
    fs.rmSync(userDataDir, { recursive: true, force: true });
  } catch {
    /* 临时目录清不掉不影响结果 */
  }

  const st = fs.statSync(OUT);
  console.log(`OK ${OUT}  ${WIDTH}x${HEIGHT}  ${(st.size / 1024).toFixed(0)}KB  theme=${THEME || 'default'}`);
}

main().catch((e) => {
  console.error('FAIL', e.message);
  process.exit(1);
});
