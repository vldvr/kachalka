// Скриншоты для README на демонстрационных данных. Нужны Node 22+ и Google Chrome.
//   python -m kachalka --headless --port 8791 &
//   node scripts/screenshots.mjs
// Кадры: Big Buck Bunny, Sintel, Tears of Steel (Blender Foundation, CC BY 3.0),
// Elephants Dream (Blender Foundation, CC BY 2.5), Spring (CC0). Источник: Wikimedia Commons.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'docs');
const APP = process.env.KACHALKA_URL || 'http://127.0.0.1:8791/';
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const DEBUG_PORT = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const COMMONS = 'https://thumb.wikimedia.org/wikipedia/commons/thumb';
const STILLS = {
  bbb: 'https://upload.wikimedia.org/wikipedia/commons/6/69/Big_Buck_Bunny_-_forest.jpg',
  sintel: `${COMMONS}/c/cf/Durian_-_Sintel-wallpaper-sintel.jpg/960px-Durian_-_Sintel-wallpaper-sintel.jpg`,
  tos: `${COMMONS}/1/18/Tears_of_Steel_frame_01_2a.jpg/960px-Tears_of_Steel_frame_01_2a.jpg`,
  ed: `${COMMONS}/e/e4/Elephants_Dream_-_Emo_and_Proog.png/960px-Elephants_Dream_-_Emo_and_Proog.png`,
  spring: `${COMMONS}/3/30/Blender_Open_Movie_-_Spring_%282019%29.png/960px-Blender_Open_Movie_-_Spring_%282019%29.png`,
};

// Общая часть всех сцен: останавливаем опрос сервера и подставляем демо-данные.
const PRELUDE = `
  const T = ${JSON.stringify(STILLS)};
  clearTimeout(S.pollTimer);
  poll = async () => {};
  // Никаких настоящих данных на картинках: ни буфера обмена, ни путей, ни истории.
  checkClipboard = async () => {};
  $('#clip').hidden = true;
  S.home = '/Users/demo';
  S.settings.folder = '/Users/demo/Downloads/YouTube';
  const tool = (name, about, extra = {}) => ({ name, about, status: 'ready', source: 'own', done: 0, total: 0, step: 1, steps: 1, error: '', ...extra });
  const READY = { ready: true, installing: false, version: '2026.10.02', version_age: 14,
    update: { running: false, ok: null, log: '', auto: false },
    items: [tool('yt-dlp', 'Скачивает видео с сайтов'), tool('ffmpeg', 'Склеивает видео со звуком и меняет форматы'),
            tool('deno', 'Нужен YouTube, без него часть видео не скачать')] };
  let n = 0;
  const job = (o) => ({ id: 'demo' + (n++).toString().padStart(8, '0'), url: 'https://www.youtube.com/watch?v=demo', status: 'done',
    progress: 1, total: 0, downloaded: 0, speed: null, eta: null, stage: '', group: null, error: '', hint: '', raw_error: '',
    file: '/demo.mp4', file_exists: true, existed: false, thumb: null,
    ...o, opts: { mode: 'video', quality: '1080', container: 'mp4', audio: 'mp3', audio_label: '', start: '', end: '', ...(o.opts || {}) } });
  const waitImages = () => Promise.all([...document.images].map((img) => img.complete ? 0 : new Promise((r) => { img.onload = img.onerror = r; })));
`;

const SCENES = [
  {
    file: 'screenshot-main.png',
    scheme: 'dark',
    js: `
      renderTools(READY);
      S.settings.last = { ...S.settings.last, mode: 'video', quality: '1080', container: 'mp4', audio_lang: 'ru', audio_both: true };
      S.info = { kind: 'video', id: 'demo', url: 'https://www.youtube.com/watch?v=demo', title: 'Sintel', channel: 'Blender Studio',
        duration: 888, thumb: T.sintel, site: 'Youtube', live: false, has_subs: true, audio_size: 14e6,
        qualities: [
          { height: 2160, fps: 24, hdr: false, size_mp4: 1.9e9, size_mkv: 1.3e9 },
          { height: 1440, fps: 24, hdr: false, size_mp4: 860e6, size_mkv: 610e6 },
          { height: 1080, fps: 24, hdr: false, size_mp4: 412e6, size_mkv: 296e6 },
          { height: 720, fps: 24, hdr: false, size_mp4: 190e6, size_mkv: 140e6 }],
        audio_tracks: [
          { code: 'en', label: 'Английский', kind: 'original', default: true, size: 14e6 },
          { code: 'ru', label: 'Русский', kind: 'dub_auto', default: false, size: 14e6 },
          { code: 'de', label: 'Немецкий', kind: 'dub_auto', default: false, size: 14e6 }] };
      renderPreview();
      S.jobs = [
        job({ title: 'Big Buck Bunny', thumb: T.bbb, status: 'running', progress: 0.63, total: 512e6, downloaded: 322e6, speed: 8.4e6, eta: 23 }),
        job({ title: 'Elephants Dream', thumb: T.ed, status: 'queued', progress: 0, opts: { mode: 'audio', audio: 'mp3' } }),
        job({ title: 'Tears of Steel', thumb: T.tos, total: 734e6, opts: { quality: '2160', container: 'mkv' } }),
      ];
      renderJobs();
      document.title = '63% Качалка';
      $('#rec').classList.add('on');
    `,
  },
  {
    file: 'screenshot-playlist.png',
    scheme: 'light',
    js: `
      renderTools(READY);
      S.settings.last = { ...S.settings.last, mode: 'video', quality: '1080', container: 'mp4', audio_lang: '' };
      const movies = [['Big Buck Bunny', T.bbb, 596], ['Elephants Dream', T.ed, 654], ['Sintel', T.sintel, 888],
                      ['Tears of Steel', T.tos, 734], ['Spring', T.spring, 464]];
      S.info = { kind: 'playlist', url: 'https://www.youtube.com/playlist?list=demo', title: 'Открытые фильмы Blender',
        channel: 'Blender Studio', thumb: T.bbb,
        entries: movies.map(([title, thumb, duration], i) => ({ index: i + 1, id: 'm' + i, url: 'https://www.youtube.com/watch?v=m' + i, title, thumb, duration })) };
      renderPreview();
      document.querySelector('#plList input[data-index="5"]').click();
      S.jobs = [
        job({ title: 'Spring', thumb: T.spring, total: 318e6, group: 'Открытые фильмы Blender' }),
        job({ title: 'Tears of Steel', thumb: T.tos, total: 0, status: 'error', progress: 0, file: '', file_exists: false, opts: { mode: 'audio', audio: 'mp3' },
          error: 'YouTube просит подтвердить, что ты не бот. Включи в настройках куки браузера, где ты вошёл в YouTube.', hint: 'cookies' }),
      ];
      renderJobs();
    `,
  },
  {
    file: 'screenshot-setup.png',
    scheme: 'dark',
    height: 560,
    js: `
      renderTools({ ...READY, ready: false, installing: true, version: '',
        items: [READY.items[0], { ...READY.items[1], status: 'downloading', source: '', done: 31.4e6, total: 88.9e6 },
                { ...READY.items[2], status: 'missing', source: '' }] });
      S.jobs = [];
      renderJobs();
    `,
  },
];

async function connect() {
  const profile = mkdtempSync(join(tmpdir(), 'kachalka-shots-'));
  const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${profile}`,
    '--hide-scrollbars', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  let target;
  for (let i = 0; i < 60 && !target; i++) {
    try {
      target = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new?about:blank`, { method: 'PUT' })).json();
    } catch {
      await sleep(250);
    }
  }
  if (!target) throw new Error('Chrome не запустился');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r, { once: true }));
  let seq = 0;
  const pending = new Map();
  ws.addEventListener('message', (e) => {
    const msg = JSON.parse(e.data);
    const call = pending.get(msg.id);
    if (!call) return;
    pending.delete(msg.id);
    if (msg.error) call.reject(new Error(msg.error.message));
    else call.resolve(msg.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const close = async () => {
    ws.close();
    const exited = new Promise((r) => chrome.once('exit', r));
    chrome.kill();
    await exited;
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  };
  return { send, close };
}

async function evaluate(send, expression) {
  const { result, exceptionDetails } = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || exceptionDetails.text);
  return result.value;
}

const { send, close } = await connect();
try {
  mkdirSync(OUT, { recursive: true });
  for (const scene of SCENES) {
    await send('Emulation.setDeviceMetricsOverride', { width: 1120, height: 900, deviceScaleFactor: 2, mobile: false });
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scene.scheme },
      { name: 'prefers-reduced-motion', value: 'reduce' }] });
    await send('Page.navigate', { url: APP });
    for (let i = 0; i < 80; i++) {
      if (await evaluate(send, "document.readyState === 'complete' && !!(window.S && S.settings)")) break;
      await sleep(250);
    }
    await evaluate(send, `(async () => { ${PRELUDE} ${scene.js}; await document.fonts.ready; await waitImages(); })()`);
    await sleep(400);
    const height = scene.height || Math.min(await evaluate(send, 'document.documentElement.scrollHeight'), 1500);
    await send('Emulation.setDeviceMetricsOverride', { width: 1120, height, deviceScaleFactor: 2, mobile: false });
    await sleep(300);
    const { data } = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(OUT, scene.file), Buffer.from(data, 'base64'));
    console.log('готово:', scene.file, `${1120}x${height}`);
  }
} finally {
  await close();
}
