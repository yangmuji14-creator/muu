#!/usr/bin/env node
/** probe.cjs — 用 CDP 在页面里跑一段 JS 并把结果打回来。用于验证样式是否真的生效。 */
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

function arg(n, d) {
  const i = process.argv.indexOf('--' + n);
  if (i === -1) return d;
  const v = process.argv[i + 1];
  return v && !v.startsWith('--') ? v : true;
}

const URL_ARG = arg('url', 'http://127.0.0.1:8000/');
const EXPR = arg('expr', '1+1');
const THEME = arg('theme', 'light');
const PORT = parseInt(arg('port', '9334'), 10);

let WebSocket;
try { WebSocket = require('ws'); } catch { console.error('need ws'); process.exit(2); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function httpJson(p) {
  return new Promise((res, rej) => {
    http.get({ host: '127.0.0.1', port: PORT, path: p }, (r) => {
      let b = ''; r.on('data', (c) => (b += c)); r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
    }).on('error', rej);
  });
}

async function main() {
  const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
  const udd = path.join(process.env.TEMP || '/tmp', 'cc-probe-' + Date.now());
  const child = spawn(chrome, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${udd}`,
    '--window-size=1440,1000', '--no-first-run', '--disable-gpu', 'about:blank'], { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try { target = (await httpJson('/json/list')).find((t) => t.type === 'page'); if (target) break; } catch {}
  }
  if (!target) { child.kill(); throw new Error('CDP 未就绪'); }

  const ws = new WebSocket(target.webSocketDebuggerUrl, { perMessageDeflate: false, maxPayload: 256 * 1024 * 1024 });
  await new Promise((res, rej) => { ws.once('open', res); ws.once('error', rej); });

  let id = 0; const pend = new Map();
  ws.on('message', (raw) => {
    const m = JSON.parse(raw.toString());
    if (m.id && pend.has(m.id)) { const { resolve, reject } = pend.get(m.id); pend.delete(m.id); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const i = ++id; pend.set(i, { resolve, reject }); ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pend.has(i)) { pend.delete(i); reject(new Error('timeout ' + method)); } }, 30000);
  });

  await send('Page.enable'); await send('Runtime.enable');
  const origin = new URL(URL_ARG).origin;
  await send('Page.navigate', { url: origin + '/__probe__' }).catch(() => {});
  await sleep(400);
  await send('Runtime.evaluate', { expression: `localStorage.setItem('cc-theme', ${JSON.stringify(THEME)})` });
  await send('Page.navigate', { url: URL_ARG });
  await sleep(2000);

  const r = await send('Runtime.evaluate', { expression: String(EXPR), returnByValue: true, awaitPromise: true });
  console.log(JSON.stringify(r.result.value, null, 2));

  ws.close(); child.kill(); await sleep(150);
  try { fs.rmSync(udd, { recursive: true, force: true }); } catch {}
}
main().catch((e) => { console.error('FAIL', e.message); process.exit(1); });
