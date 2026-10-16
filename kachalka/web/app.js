'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

const ACTIVE = new Set(['starting', 'running', 'processing']);
const FINISHED = new Set(['done', 'canceled', 'error']);
const DEFAULT_OPTS = { mode: 'video', quality: '1080', container: 'mp4', audio: 'mp3', subs: false, thumb: true, sponsor: false, start: '', end: '' };
const PLAYLIST_QUALITIES = [
  ['best', 'Лучшее', 'максимум'], ['2160', '2160p', '4K'], ['1440', '1440p', '2K'],
  ['1080', '1080p', 'Full HD'], ['720', '720p', 'HD'], ['480', '480p', ''], ['360', '360p', ''],
];
const AUDIO_NOTES = {
  mp3: 'Играет везде. Перекодируется из оригинала с максимальным качеством.',
  m4a: 'AAC, обычно без перекодирования. Удобно для iPhone и «Музыки».',
  opus: 'Оригинальная дорожка YouTube, самая компактная.',
  best: 'Дорожка ровно в том виде, в каком её отдаёт сайт.',
};
const TEMPLATE_EXAMPLES = {
  title: 'Название видео.mp4',
  title_id: 'Название видео [aBcD3fGh1jK].mp4',
  channel_title: 'Канал - Название видео.mp4',
  date_title: '2026-08-19 Название видео.mp4',
};
const TRACK_KINDS = { original: 'оригинал', dub_auto: 'автодубляж', dub: 'дубляж', desc: 'тифлокомментарий' };
const PLAYLIST_LANGS = [['', 'Оригинал'], ['ru', 'Русский'], ['en', 'Английский']];
const COOKIES_HELP = {
  mac: 'Нужны, когда YouTube просит войти, считает тебя ботом или видео 18+. В выбранном браузере ты должен быть залогинен в YouTube. Для Chrome и похожих браузеров macOS спросит доступ к ключу «Safe Storage»: «Разрешить» спросит снова в следующий раз, «Разрешить всегда» удобнее, но тогда любая программа на Маке сможет без спроса расшифровать куки и пароли этого браузера. Надёжнее держать для YouTube отдельный браузер с отдельным аккаунтом.',
  win: 'Нужны, когда YouTube просит войти, считает тебя ботом или видео 18+. В Windows лучше всего работает Firefox: Chrome и Edge шифруют куки так, что другие программы их не прочитают. Войди в YouTube в Firefox и выбери его здесь. Надёжнее завести для этого отдельный аккаунт.',
  linux: 'Нужны, когда YouTube просит войти, считает тебя ботом или видео 18+. В выбранном браузере ты должен быть залогинен в YouTube. Надёжнее держать для этого отдельный аккаунт.',
};
const TIME_RE = /^\d{1,3}(:\d{1,2}){0,2}(\.\d+)?$/;
// Подсказку из буфера показываем только для видеосайтов, чтобы не мелькала на любой ссылке.
const VIDEO_HOSTS = /(^|\.)(youtube\.com|youtu\.be|vimeo\.com|twitch\.tv|tiktok\.com|instagram\.com|x\.com|twitter\.com|vk\.com|vkvideo\.ru|rutube\.ru|dailymotion\.com|reddit\.com|soundcloud\.com|bilibili\.com|archive\.org|facebook\.com|ok\.ru|kick\.com|bandcamp\.com)$/i;

const S = {
  settings: null, home: '', platform: 'mac', repo: '', appVersion: '', tools: null, updateAuto: false,
  info: null, infoUrl: '', infoCtl: null, opts: { ...DEFAULT_OPTS }, moreOpen: false,
  selected: new Set(), lastPick: null, shift: false,
  jobs: [], rows: new Map(), firstRender: true,
  pollTimer: 0, offline: false, updateRunning: false,
  clipHidden: new Set(), returnFocus: null,
};

const urlInput = $('#url');

/* ------------------------------------------------------------- форматирование */

const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

function bytes(n) {
  if (!n || n <= 0) return '';
  const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${(n < 10 || i >= 3 ? nf1 : nf0).format(n)} ${units[i]}`;
}

function clock(sec) {
  if (sec == null || !Number.isFinite(sec)) return '';
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (x) => String(x).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function hours(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.round((sec % 3600) / 60);
  return h ? `${h} ч ${m} мин` : `${Math.max(m, 1)} мин`;
}

function seconds(text) {
  if (!text) return null;
  return text.split(':').reduce((acc, part) => acc * 60 + parseFloat(part), 0);
}

function plural(n, one, few, many) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function cut(text, n) {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

function tildify(path) {
  return S.home && path.startsWith(S.home) ? `~${path.slice(S.home.length)}` : path;
}

function shortPath(path) {
  const p = tildify(path);
  if (p.length <= 42) return p;
  return `…/${p.split('/').filter(Boolean).slice(-2).join('/')}`;
}

function withScheme(u) {
  return /^https?:\/\//i.test(u) ? u : `https://${u}`;
}

function hostOf(u) {
  try { return new URL(withScheme(u)).hostname; } catch { return ''; }
}

function isYouTube(u) {
  return /(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$/i.test(hostOf(u));
}

function looksLikeUrl(text) {
  const t = text.trim();
  return /^(https?:\/\/)?[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/i.test(t) || /^[\w-]{11}$/.test(t);
}

function videoInPlaylist(u) {
  try {
    const x = new URL(withScheme(u.trim()));
    return x.searchParams.has('list') && (x.searchParams.has('v') || /youtu\.be$/i.test(x.hostname));
  } catch { return false; }
}

function shortUrl(u) {
  return u.replace(/^https?:\/\/(www\.)?/i, '');
}

/* ------------------------------------------------------------- сеть */

async function api(path, body, signal) {
  const init = { signal };
  if (body !== undefined) {
    init.method = 'POST';
    init.headers = { 'Content-Type': 'application/json', 'X-Kachalka': '1' };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { /* пустой ответ */ }
  if (!res.ok) {
    const err = new Error(data.error || `Сервер ответил кодом ${res.status}`);
    err.hint = data.hint || '';
    err.raw = data.raw || '';
    throw err;
  }
  return data;
}

let toastTimer = 0;
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.hidden = false;
  el.classList.remove('enter');
  void el.offsetWidth;
  el.classList.add('enter');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3400);
}

function setOffline(on) {
  if (S.offline === on) return;
  S.offline = on;
  $('#offline').hidden = !on;
  if (!on) loadSettings();
}

/* ------------------------------------------------------------- ссылка */

function updatePlaylistSwitch() {
  const show = videoInPlaylist(urlInput.value);
  $('#playlistSwitch').hidden = !show;
  if (!show) $('#wholePlaylist').checked = false;
}

function hideIntakeError() {
  $('#intakeError').hidden = true;
}

function hintButton(hint) {
  if (hint === 'cookies') {
    return '<button type="button" class="btn ghost small" data-act="cookies"><i class="ph ph-cookie" aria-hidden="true"></i>Включить куки</button>';
  }
  if (hint === 'update') {
    return '<button type="button" class="btn ghost small" data-act="update"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i>Обновить yt-dlp</button>';
  }
  if (hint === 'tools') {
    return '<button type="button" class="btn ghost small" data-act="tools"><i class="ph ph-wrench" aria-hidden="true"></i>Проверить компоненты</button>';
  }
  return '';
}

function showIntakeError(err) {
  const box = $('#intakeError');
  const firstSentence = (err.raw || '').split(/(?<=\.)\s/)[0];
  const raw = err.raw && err.raw !== err.message
    ? `<span class="alert-raw" title="${esc(err.raw)}">Ответ yt-dlp: ${esc(cut(firstSentence, 180))}</span>`
    : '';
  box.innerHTML = `<i class="ph ph-warning-circle" aria-hidden="true"></i><span class="alert-text">${esc(err.message)}</span>${hintButton(err.hint)}${raw}`;
  box.hidden = false;
}

function setFinding(on) {
  const btn = $('#findBtn');
  btn.disabled = on;
  btn.textContent = on ? 'Ищу…' : 'Найти';
}

async function lookup() {
  const url = urlInput.value.trim();
  if (!url) { urlInput.focus(); return; }
  hideIntakeError();
  $('#clip').hidden = true;
  updatePlaylistSwitch();
  if (S.infoCtl) S.infoCtl.abort();
  const ctl = new AbortController();
  S.infoCtl = ctl;
  const playlist = $('#playlistSwitch').hidden ? true : $('#wholePlaylist').checked;
  renderSkeleton();
  setFinding(true);
  try {
    const info = await api('/api/info', { url, playlist }, ctl.signal);
    if (ctl !== S.infoCtl) return;
    S.info = info;
    S.infoUrl = url;
    renderPreview();
  } catch (err) {
    if (err.name === 'AbortError') return;
    closePreview();
    showIntakeError(err);
  } finally {
    if (ctl === S.infoCtl) { setFinding(false); S.infoCtl = null; }
  }
}

$('#intake').addEventListener('submit', (e) => { e.preventDefault(); lookup(); });

urlInput.addEventListener('paste', () => {
  setTimeout(() => { if (looksLikeUrl(urlInput.value)) lookup(); }, 0);
});
urlInput.addEventListener('input', () => { updatePlaylistSwitch(); hideIntakeError(); });
$('#wholePlaylist').addEventListener('change', () => { if (urlInput.value.trim()) lookup(); });

$('#pasteBtn').addEventListener('click', async () => {
  try {
    const { url } = await api('/api/clipboard');
    if (!url) { showIntakeError({ message: 'В буфере обмена нет ссылки. Скопируй адрес видео в браузере.' }); return; }
    urlInput.value = url;
    lookup();
  } catch (err) { toast(err.message); }
});

// ⌘V в любом месте окна, даже если поле не в фокусе.
document.addEventListener('paste', (e) => {
  const t = e.target;
  if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t.isContentEditable) return;
  const text = (e.clipboardData?.getData('text') || '').trim();
  if (!text) return;
  e.preventDefault();
  urlInput.value = text;
  lookup();
});

// Ссылку можно перетащить из браузера прямо на окно.
window.addEventListener('dragover', (e) => {
  const types = Array.from(e.dataTransfer?.types || []);
  if (types.includes('text/uri-list') || types.includes('text/plain')) {
    e.preventDefault();
    document.body.classList.add('dropping');
  }
});
window.addEventListener('dragleave', (e) => {
  if (!e.relatedTarget) document.body.classList.remove('dropping');
});
window.addEventListener('drop', (e) => {
  document.body.classList.remove('dropping');
  const raw = e.dataTransfer?.getData('text/uri-list') || e.dataTransfer?.getData('text/plain') || '';
  const link = raw.split(/\r?\n/).map((l) => l.trim()).find((l) => l && !l.startsWith('#'));
  if (!link) return;
  e.preventDefault();
  urlInput.value = link;
  lookup();
});

async function checkClipboard() {
  if (document.hidden || S.offline) return;
  try {
    const { url } = await api('/api/clipboard');
    const clip = $('#clip');
    const current = urlInput.value.trim();
    const known = S.jobs.some((j) => j.url === url);
    if (!url || !VIDEO_HOSTS.test(hostOf(url)) || url === current || url === S.infoUrl || S.clipHidden.has(url) || known) {
      clip.hidden = true;
      return;
    }
    $('#clipUrl').textContent = shortUrl(url);
    clip.dataset.url = url;
    clip.hidden = false;
  } catch { /* сервер недоступен: покажет баннер */ }
}

window.addEventListener('focus', checkClipboard);
$('#clipUse').addEventListener('click', () => {
  urlInput.value = $('#clip').dataset.url || '';
  lookup();
});
$('#clipHide').addEventListener('click', () => {
  S.clipHidden.add($('#clip').dataset.url);
  $('#clip').hidden = true;
});

/* ------------------------------------------------------------- превью */

function showPreview() {
  const p = $('#preview');
  const wasHidden = p.hidden;
  p.hidden = false;
  if (wasHidden) {
    p.classList.remove('enter');
    void p.offsetWidth;
    p.classList.add('enter');
  }
}

function closePreview() {
  if (S.infoCtl) { S.infoCtl.abort(); S.infoCtl = null; setFinding(false); }
  S.info = null;
  const p = $('#preview');
  p.hidden = true;
  p.innerHTML = '';
}

function renderSkeleton() {
  $('#preview').innerHTML = `
    <div class="pv skel" aria-busy="true">
      <div class="pv-media"></div>
      <div>
        <div class="skel-line" style="width:84%;height:20px"></div>
        <div class="skel-line" style="width:42%"></div>
        <div class="skel-line" style="width:56%;height:40px;margin-top:24px"></div>
        <div class="skel-line" style="width:92%;height:52px"></div>
        <p class="skel-note">Узнаю, что по ссылке. Обычно это пара секунд, длинные плейлисты дольше.</p>
      </div>
    </div>`;
  showPreview();
}

function pickQuality(qualities, wanted) {
  if (!qualities.length) return 'best';
  const heights = qualities.map((q) => q.height);
  if (wanted === 'best') return String(heights[0]);
  const target = parseInt(wanted, 10) || 1080;
  const fit = heights.find((h) => h <= target);
  return String(fit ?? heights[heights.length - 1]);
}

function baseLang(code) {
  return (code || '').split('-')[0].toLowerCase();
}

function trackValue(t) {
  return t.code === S.opts.audio_orig ? '' : t.code;
}

function pickTrack(tracks) {
  const o = S.opts;
  const orig = tracks.find((t) => t.kind === 'original') || tracks.find((t) => t.default) || tracks[0];
  const want = baseLang(o.audio_lang);
  o.audio_orig = orig ? orig.code : '';
  const match = want && tracks.find((t) => t.kind !== 'desc' && baseLang(t.code) === want);
  o.audio_lang = match && match.code !== o.audio_orig ? match.code : '';
}

function trackPicker(info, o) {
  const tracks = info.audio_tracks;
  const note = (t) => (TRACK_KINDS[t.kind] ? `<small>${TRACK_KINDS[t.kind]}</small>` : '');
  let control;
  if (tracks.length <= 6) {
    control = `<div class="seg" role="radiogroup" aria-labelledby="tLabel" data-opt="audio_lang">${tracks.map((t) => (
      `<button type="button" role="radio" aria-checked="${trackValue(t) === o.audio_lang}" data-value="${esc(trackValue(t))}">${esc(t.label)}${note(t)}</button>`
    )).join('')}</div>`;
  } else {
    // На популярных роликах бывает два десятка автодубляжей: кнопками это не уместить.
    control = `<select class="track-select" id="trackSelect" aria-labelledby="tLabel">${tracks.map((t) => (
      `<option value="${esc(trackValue(t))}"${trackValue(t) === o.audio_lang ? ' selected' : ''}>${esc(t.label)}${TRACK_KINDS[t.kind] ? ` (${TRACK_KINDS[t.kind]})` : ''}</option>`
    )).join('')}</select>`;
  }
  const both = o.mode === 'video' && o.audio_lang
    ? check('audio_both', 'Добавить оригинал второй дорожкой', 'Переключается в плеере: QuickTime, IINA, VLC.', o.audio_both)
    : '';
  return `<div><span class="opt-label" id="tLabel">Звуковая дорожка</span>${control}${both}</div>`;
}

function playlistLangPicker(o) {
  if (!PLAYLIST_LANGS.some(([v]) => v === o.audio_lang)) o.audio_lang = '';
  return `
    <div>
      <span class="opt-label" id="tLabel">Звуковая дорожка</span>
      <div class="seg" role="radiogroup" aria-labelledby="tLabel" data-opt="audio_lang">
        ${PLAYLIST_LANGS.map(([v, l]) => radio(v, l, o.audio_lang)).join('')}
      </div>
      <p class="seg-note">Если у видео нет такой дорожки, будет оригинал.</p>
    </div>`;
}

function actionsHtml(label) {
  return `
    <div class="pv-actions">
      <button class="btn primary" id="startBtn" type="button"><i class="ph ph-download-simple" aria-hidden="true"></i><span>${label}</span></button>
      <span class="pv-est" id="estimate"></span>
      <span class="spacer"></span>
      <button class="btn quiet" id="closePreview" type="button">Отмена</button>
    </div>`;
}

function renderPreview() {
  const info = S.info;
  const p = $('#preview');
  S.opts = { ...DEFAULT_OPTS, ...(S.settings?.last || {}), start: '', end: '' };

  if (info.kind === 'video') {
    S.opts.quality = pickQuality(info.qualities, S.opts.quality);
    pickTrack(info.audio_tracks || []);
    const site = info.site && !/youtube/i.test(info.site) ? info.site : '';
    const meta = [info.channel, site].filter(Boolean).join(', ');
    p.innerHTML = `
      <div class="pv">
        <div class="pv-media">
          ${info.thumb ? `<img src="${esc(info.thumb)}" alt="">` : '<i class="ph ph-film-strip" aria-hidden="true"></i>'}
          ${info.duration ? `<span class="pv-dur">${clock(info.duration)}</span>` : ''}
        </div>
        <div class="pv-body">
          <h3 class="pv-title">${esc(info.title)}</h3>
          <p class="pv-meta">${esc(meta) || '&nbsp;'}</p>
          ${info.live ? '<p class="pv-live">Сейчас идёт трансляция: запись продлится, пока она не закончится.</p>' : ''}
          <div class="opts" id="opts"></div>
          ${actionsHtml('Скачать')}
        </div>
      </div>`;
  } else {
    S.selected = new Set(info.entries.map((e) => e.index));
    S.lastPick = null;
    const total = info.entries.reduce((sum, e) => sum + (e.duration || 0), 0);
    const count = info.entries.length;
    const meta = [info.channel, `${count} видео`, total ? hours(total) : ''].filter(Boolean).join(', ');
    p.innerHTML = `
      <div class="pl">
        <div class="pl-head">
          <div>
            <h3 class="pv-title">${esc(info.title)}</h3>
            <p class="pv-meta">${esc(meta)}</p>
          </div>
          <button class="btn ghost small" id="toggleAll" type="button">Снять все</button>
        </div>
        <ul class="pl-list" id="plList">
          ${info.entries.map((e) => `
            <li class="pl-item" data-index="${e.index}">
              <label>
                <input type="checkbox" checked data-index="${e.index}" aria-label="${esc(e.title)}">
                <span class="thumb">${e.thumb ? `<img src="${esc(e.thumb)}" alt="" loading="lazy">` : ''}</span>
                <span class="t" title="${esc(e.title)}">${esc(e.title)}</span>
                <span class="d">${clock(e.duration)}</span>
              </label>
            </li>`).join('')}
        </ul>
        <div class="opts" id="opts"></div>
        ${actionsHtml('Скачать')}
      </div>`;
  }
  renderOpts();
  showPreview();
}

function radio(value, label, current) {
  return `<button type="button" role="radio" aria-checked="${value === current}" data-value="${value}">${label}</button>`;
}

function check(key, label, note, checked, disabled = false) {
  return `
    <label class="check${disabled ? ' disabled' : ''}">
      <input type="checkbox" data-opt="${key}"${checked ? ' checked' : ''}${disabled ? ' disabled' : ''}>
      <span>${label}${note ? `<small>${esc(note)}</small>` : ''}</span>
    </label>`;
}

function qualityChips(info, o) {
  if (info.kind === 'video') {
    return info.qualities.map((q) => {
      const size = o.container === 'mp4' ? q.size_mp4 : q.size_mkv;
      const label = `${q.height}p${q.fps > 30 ? q.fps : ''}`;
      const sub = [size ? `≈ ${bytes(size)}` : '', q.hdr ? 'HDR' : ''].filter(Boolean).join(', ');
      return `<button type="button" class="q" role="radio" aria-checked="${String(q.height) === o.quality}" data-value="${q.height}"><b>${label}</b><small>${sub || '&nbsp;'}</small></button>`;
    }).join('');
  }
  return PLAYLIST_QUALITIES.map(([value, label, sub]) => (
    `<button type="button" class="q" role="radio" aria-checked="${value === o.quality}" data-value="${value}"><b>${label}</b><small>${sub || '&nbsp;'}</small></button>`
  )).join('');
}

function renderOpts(focusKey) {
  const info = S.info;
  const o = S.opts;
  const isVideo = info.kind === 'video';
  const audio = o.mode === 'audio';
  let html = `
    <div>
      <span class="opt-label" id="modeLabel">Что скачать</span>
      <div class="seg" role="radiogroup" aria-labelledby="modeLabel" data-opt="mode">
        ${radio('video', '<i class="ph ph-film-strip" aria-hidden="true"></i>Видео', o.mode)}
        ${radio('audio', '<i class="ph ph-music-notes" aria-hidden="true"></i>Только звук', o.mode)}
      </div>
    </div>`;
  if (isVideo && info.audio_tracks?.length) html += trackPicker(info, o);
  else if (!isVideo && isYouTube(info.url)) html += playlistLangPicker(o);

  if (!audio) {
    if (!isVideo && !PLAYLIST_QUALITIES.some(([v]) => v === o.quality)) o.quality = '1080';
    const hasChips = !isVideo || info.qualities.length > 0;
    if (hasChips) {
      html += `
        <div>
          <span class="opt-label" id="qLabel">${isVideo ? 'Качество' : 'Качество, не выше'}</span>
          <div class="q-grid" role="radiogroup" aria-labelledby="qLabel" data-opt="quality">${qualityChips(info, o)}</div>
        </div>`;
    }
    html += `
      <div>
        <span class="opt-label" id="cLabel">Файл</span>
        <div class="seg" role="radiogroup" aria-labelledby="cLabel" data-opt="container">
          ${radio('mp4', 'MP4', o.container)}${radio('mkv', 'MKV', o.container)}
        </div>
        <p class="seg-note">${o.container === 'mp4'
          ? 'Откроется везде: QuickTime, телефон, Telegram.'
          : 'Самые новые кодеки без оглядки на совместимость. Смотреть в IINA или VLC.'}</p>
      </div>`;
  } else {
    html += `
      <div>
        <span class="opt-label" id="aLabel">Формат звука</span>
        <div class="seg" role="radiogroup" aria-labelledby="aLabel" data-opt="audio">
          ${radio('mp3', 'MP3', o.audio)}${radio('m4a', 'M4A', o.audio)}${radio('opus', 'Opus', o.audio)}${radio('best', 'Как есть', o.audio)}
        </div>
        <p class="seg-note">${AUDIO_NOTES[o.audio]}</p>
      </div>`;
  }

  const subsAvailable = !audio && (isVideo ? info.has_subs : true);
  const langs = S.settings?.subs_langs || 'ru.*,en.*';
  const parts = [check('thumb', 'Встроить обложку в файл', '', o.thumb)];
  if (!audio) {
    parts.push(check('subs', 'Субтитры', subsAvailable
      ? `Языки: ${langs}. Меняются в настройках.`
      : 'У этого видео субтитров нет.', o.subs && subsAvailable, !subsAvailable));
  }
  if (isYouTube(info.url)) {
    parts.push(check('sponsor', 'Вырезать рекламные вставки', 'По базе SponsorBlock: реклама спонсоров, самопиар и просьбы подписаться.', o.sponsor));
  }
  if (isVideo && !info.live) {
    parts.push(`
      <div class="cut">
        <span>Только кусок: с</span>
        <input id="cutStart" type="text" inputmode="numeric" placeholder="0:00" value="${esc(o.start)}" aria-label="Начало куска">
        <span>до</span>
        <input id="cutEnd" type="text" inputmode="numeric" placeholder="${clock(info.duration) || 'конца'}" value="${esc(o.end)}" aria-label="Конец куска">
      </div>`);
  }
  html += `
    <details class="more"${S.moreOpen ? ' open' : ''}>
      <summary><i class="ph ph-caret-right" aria-hidden="true"></i>Ещё настройки</summary>
      <div class="more-body">${parts.join('')}</div>
    </details>`;

  $('#opts').innerHTML = html;
  if (focusKey) {
    const el = $(`#opts [data-opt="${focusKey}"] [aria-checked="true"]`);
    if (el) el.focus();
  }
  updateEstimate();
}

function estimateSize() {
  const info = S.info;
  const o = S.opts;
  let size = 0;
  const track = (info.audio_tracks || []).find((t) => trackValue(t) === o.audio_lang);
  const orig = (info.audio_tracks || []).find((t) => t.code === o.audio_orig);
  if (o.mode === 'audio') {
    size = o.audio === 'mp3' && info.duration ? (info.duration * 245000) / 8 : (track?.size || info.audio_size);
  } else {
    const q = info.qualities.find((x) => String(x.height) === o.quality);
    if (q) size = o.container === 'mp4' ? q.size_mp4 : q.size_mkv;
    if (size && o.audio_lang && o.audio_both && orig) size += orig.size;
  }
  if (size && info.duration && (o.start || o.end) && TIME_RE.test(o.start || '0') && TIME_RE.test(o.end || '0')) {
    const from = seconds(o.start) || 0;
    const to = Math.min(seconds(o.end) || info.duration, info.duration);
    size *= Math.max(to - from, 0) / info.duration;
  }
  return size;
}

function updateEstimate() {
  const info = S.info;
  if (!info) return;
  const est = $('#estimate');
  const btn = $('#startBtn');
  const folder = esc(shortPath(S.settings?.folder || ''));
  est.title = S.settings?.folder || '';
  if (info.kind === 'video') {
    const size = estimateSize();
    est.innerHTML = size ? `<b>≈ ${bytes(size)}</b> в папку ${folder}` : `В папку ${folder}`;
    btn.disabled = false;
    return;
  }
  const n = S.selected.size;
  $('span', btn).textContent = n ? `Скачать ${n} видео` : 'Ничего не выбрано';
  btn.disabled = n === 0;
  est.innerHTML = `В папку ${folder}/${esc(cut(info.title, 40))}`;
  $('#toggleAll').textContent = n === info.entries.length ? 'Снять все' : 'Выбрать все';
}

function syncSelection() {
  S.selected = new Set($$('#plList input:checked').map((i) => Number(i.dataset.index)));
  $$('#plList .pl-item').forEach((li) => li.classList.toggle('off', !S.selected.has(Number(li.dataset.index))));
  updateEstimate();
}

function validateCut(input) {
  const ok = !input.value.trim() || TIME_RE.test(input.value.trim());
  input.classList.toggle('bad', !ok);
  return ok;
}

const preview = $('#preview');

preview.addEventListener('click', (e) => {
  const opt = e.target.closest('[role="radio"]');
  const group = opt?.closest('[data-opt]');
  if (opt && group) {
    const key = group.dataset.opt;
    if (S.opts[key] !== opt.dataset.value) {
      S.opts[key] = opt.dataset.value;
      renderOpts(key);
    }
    return;
  }
  if (e.target.closest('#startBtn')) startDownload();
  else if (e.target.closest('#closePreview')) closePreview();
  else if (e.target.closest('#toggleAll')) {
    const all = S.selected.size !== S.info.entries.length;
    $$('#plList input').forEach((i) => { i.checked = all; });
    syncSelection();
  }
});

preview.addEventListener('change', (e) => {
  const t = e.target;
  if (t.matches('input[type="checkbox"][data-opt]')) {
    S.opts[t.dataset.opt] = t.checked;
    updateEstimate();
  } else if (t.id === 'trackSelect') {
    S.opts.audio_lang = t.value;
    renderOpts();
    $('#trackSelect')?.focus();
  } else if (t.matches('#plList input')) {
    const idx = Number(t.dataset.index);
    if (S.shift && S.lastPick != null) {
      const order = S.info.entries.map((x) => x.index);
      const [a, b] = [order.indexOf(S.lastPick), order.indexOf(idx)].sort((x, y) => x - y);
      order.slice(a, b + 1).forEach((i) => { $(`#plList input[data-index="${i}"]`).checked = t.checked; });
    }
    S.lastPick = idx;
    syncSelection();
  }
});

preview.addEventListener('input', (e) => {
  const t = e.target;
  if (t.id === 'cutStart' || t.id === 'cutEnd') {
    S.opts[t.id === 'cutStart' ? 'start' : 'end'] = t.value.trim();
    validateCut(t);
    updateEstimate();
  }
});

// Событие toggle не всплывает, поэтому ловим его на погружении.
preview.addEventListener('toggle', (e) => {
  if (e.target.matches('details.more')) S.moreOpen = e.target.open;
}, true);

window.addEventListener('keydown', (e) => { S.shift = e.shiftKey; });
window.addEventListener('keyup', (e) => { S.shift = e.shiftKey; });

async function startDownload() {
  const info = S.info;
  if (!info) return;
  const o = { ...S.opts };
  const bad = $$('#cutStart, #cutEnd').filter((i) => !validateCut(i));
  if (bad.length) {
    S.moreOpen = true;
    $('details.more').open = true;
    bad[0].focus();
    toast('Время куска пишется так: 1:30 или 1:02:15.');
    return;
  }
  let items;
  let group = null;
  let prefLang = S.settings?.last?.audio_lang || '';
  if (info.kind === 'video') {
    items = [{ url: info.url, title: info.title, thumb: info.thumb, duration: info.duration, channel: info.channel }];
    const tracks = info.audio_tracks || [];
    const track = tracks.find((t) => trackValue(t) === o.audio_lang);
    if (tracks.length) {
      // Выбор на видео с несколькими дорожками становится новым пожеланием по языку.
      prefLang = baseLang(o.audio_lang);
      o.audio_both = Boolean(o.audio_lang && o.audio_both && o.mode === 'video');
      o.audio_label = o.audio_lang && track ? `${track.label}${o.audio_both ? ' и оригинал' : ''}` : '';
    } else {
      Object.assign(o, { audio_lang: '', audio_orig: '', audio_both: false, audio_label: '' });
    }
  } else {
    prefLang = o.audio_lang;
    o.audio_label = (PLAYLIST_LANGS.find(([v]) => v === o.audio_lang && v) || [])[1] || '';
    Object.assign(o, { audio_orig: '', audio_both: false });
    items = info.entries.filter((e) => S.selected.has(e.index)).map((e) => ({
      url: e.url, title: e.title, thumb: e.thumb, duration: e.duration, channel: e.channel || info.channel, index: e.index,
    }));
    group = info.title;
    o.start = '';
    o.end = '';
  }
  const btn = $('#startBtn');
  btn.disabled = true;
  try {
    await api('/api/download', { items, group, opts: o, pref_lang: prefLang });
    if (S.settings) S.settings.last = { ...o, audio_lang: prefLang };
    toast(items.length > 1 ? `Добавил в очередь ${items.length} видео` : `Качаю «${cut(info.title, 60)}»`);
    closePreview();
    urlInput.value = '';
    updatePlaylistSwitch();
    poll();
  } catch (err) {
    btn.disabled = false;
    toast(err.message);
  }
}

/* ------------------------------------------------------------- очередь */

function optsSummary(o) {
  if (!o) return '';
  let text;
  if (o.mode === 'audio') text = o.audio === 'best' ? 'звук как есть' : `звук ${o.audio.toUpperCase()}`;
  else text = `${o.quality === 'best' ? 'лучшее качество' : `${o.quality}p`} ${o.container.toUpperCase()}`;
  if (o.audio_label) text += `, дорожка: ${o.audio_label.charAt(0).toLowerCase()}${o.audio_label.slice(1)}`;
  if (o.start || o.end) text += `, кусок ${o.start || '0:00'}-${o.end || 'конец'}`;
  return text;
}

function statusText(j) {
  switch (j.status) {
    case 'queued': return 'В очереди';
    case 'starting': return j.stage || 'Подключаюсь';
    case 'running': {
      const parts = [];
      if (j.total) parts.push(`${Math.floor(j.progress * 100)}% из ${bytes(j.total)}`);
      else if (j.downloaded) parts.push(`скачано ${bytes(j.downloaded)}`);
      if (j.speed) parts.push(`${bytes(j.speed)}/с`);
      if (j.eta > 0) parts.push(`ещё ${clock(j.eta)}`);
      return parts.join(', ') || 'Качаю';
    }
    case 'processing': return j.stage || 'Обрабатываю файл';
    case 'done':
      if (j.file && !j.file_exists) return 'Готово, но файл уже переместили или удалили';
      if (j.existed) return 'Файл с таким именем уже был в папке, заново не качал';
      return j.total ? `Готово, ${bytes(j.total)}` : 'Готово';
    case 'error': return j.error || 'Не получилось скачать';
    case 'canceled': return 'Отменено';
    case 'interrupted': return 'Прервано: Качалку закрыли во время загрузки';
    default: return '';
  }
}

function actionButton(act, icon, label) {
  return `<button type="button" class="btn quiet square" data-job-act="${act}" aria-label="${label}" title="${label}"><i class="ph ph-${icon}" aria-hidden="true"></i></button>`;
}

function actionsFor(j) {
  if (j.status === 'queued') return actionButton('cancel', 'x', 'Отменить');
  if (ACTIVE.has(j.status)) return actionButton('cancel', 'x-circle', 'Остановить');
  if (j.status === 'done') {
    const own = j.file && j.file_exists;
    return (own ? actionButton('open', 'play', 'Открыть') : '')
      + actionButton('reveal', 'folder-open', own ? 'Показать в Finder' : 'Открыть папку')
      + (j.existed ? actionButton('redo', 'arrow-clockwise', 'Скачать заново и заменить файл') : '')
      + actionButton('remove', 'x', 'Убрать из списка');
  }
  const retry = j.status === 'interrupted' ? 'Продолжить' : 'Повторить';
  return actionButton('retry', 'arrow-clockwise', retry) + actionButton('remove', 'x', 'Убрать из списка');
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

function setHtml(el, html) {
  if (el.dataset.html !== html) {
    el.dataset.html = html;
    el.innerHTML = html;
  }
}

function fallbackThumb(box, mode) {
  $$('img', box).forEach((img) => img.remove());
  if (!$('.fallback', box)) {
    box.insertAdjacentHTML('afterbegin', `<i class="ph ph-${mode === 'audio' ? 'music-notes' : 'film-strip'} fallback" aria-hidden="true"></i>`);
  }
}

function createRow(j) {
  const li = document.createElement('li');
  li.className = S.firstRender ? 'job' : 'job enter';
  li.dataset.id = j.id;
  const src = esc(j.thumb || '');
  li.innerHTML = `
    <div class="job-thumb">
      ${j.thumb ? `<img class="gray" src="${src}" alt=""><img class="color" src="${src}" alt="">` : ''}
      <span class="badge"><i class="ph ph-check" aria-hidden="true"></i></span>
    </div>
    <div class="job-body">
      <p class="job-title"></p>
      <p class="job-status"></p>
      <p class="job-sub"></p>
      <div class="job-hint"></div>
    </div>
    <div class="job-actions"></div>`;
  const box = $('.job-thumb', li);
  if (!j.thumb) fallbackThumb(box, j.opts?.mode);
  $$('img', li).forEach((img) => img.addEventListener('error', () => fallbackThumb(box, j.opts?.mode), { once: true }));
  return li;
}

function updateRow(row, j) {
  row.dataset.status = j.status;
  const p = j.status === 'done' || j.status === 'processing' ? 1 : j.progress || 0;
  $('.job-thumb', row).style.setProperty('--p', p.toFixed(3));
  const title = $('.job-title', row);
  setText(title, j.title || j.url);
  title.title = j.title || j.url;
  const status = $('.job-status', row);
  setText(status, statusText(j));
  status.title = j.status === 'error' && j.raw_error ? `yt-dlp: ${j.raw_error}` : '';
  const sub = [j.group ? `«${j.group}»` : '', optsSummary(j.opts)].filter(Boolean).join(', ');
  setText($('.job-sub', row), sub);
  setHtml($('.job-hint', row), j.status === 'error' ? hintButton(j.hint) : '');
  setHtml($('.job-actions', row), actionsFor(j));
}

function renderJobs() {
  const list = $('#jobs');
  const seen = new Set();
  let prev = null;
  for (const j of S.jobs) {
    seen.add(j.id);
    let row = S.rows.get(j.id);
    if (!row) {
      row = createRow(j);
      S.rows.set(j.id, row);
    }
    updateRow(row, j);
    const spot = prev ? prev.nextSibling : list.firstChild;
    if (spot !== row) list.insertBefore(row, spot);
    prev = row;
  }
  for (const [id, row] of S.rows) {
    if (!seen.has(id)) { row.remove(); S.rows.delete(id); }
  }

  const active = S.jobs.filter((j) => ACTIVE.has(j.status));
  const queued = S.jobs.filter((j) => j.status === 'queued');
  const parts = [];
  if (active.length) parts.push(`${active.length} ${plural(active.length, 'качается', 'качаются', 'качаются')}`);
  if (queued.length) parts.push(`${queued.length} в очереди`);
  setText($('#queueSum'), parts.join(', '));
  $('#emptyQueue').hidden = S.jobs.length > 0;
  $('#clearDone').hidden = !S.jobs.some((j) => FINISHED.has(j.status));
  $('#rec').classList.toggle('on', active.length > 0);

  const pending = [...active, ...queued];
  if (pending.length) {
    const avg = pending.reduce((sum, j) => sum + (j.status === 'processing' ? 1 : j.progress || 0), 0) / pending.length;
    document.title = `${Math.floor(avg * 100)}% Качалка`;
  } else {
    document.title = 'Качалка';
  }
}

async function jobAction(id, act) {
  try {
    if (act === 'remove') {
      S.rows.get(id)?.remove();
      S.rows.delete(id);
    }
    if (act === 'redo') await api(`/api/jobs/${id}/retry`, { force: true });
    else await api(`/api/jobs/${id}/${act}`, {});
  } catch (err) {
    toast(err.message);
  }
  poll();
}

$('#jobs').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-job-act]');
  if (!btn) return;
  jobAction(btn.closest('.job').dataset.id, btn.dataset.jobAct);
});

$('#jobs').addEventListener('dblclick', (e) => {
  const row = e.target.closest('.job');
  if (row && row.dataset.status === 'done' && !e.target.closest('button')) jobAction(row.dataset.id, 'open');
});

$('#clearDone').addEventListener('click', async () => {
  try { await api('/api/jobs/clear', {}); } catch (err) { toast(err.message); }
  poll();
});

async function poll() {
  clearTimeout(S.pollTimer);
  try {
    const data = await api('/api/jobs');
    setOffline(false);
    S.jobs = data.jobs;
    renderJobs();
    renderTools(data.tools);
  } catch {
    setOffline(true);
  }
  const busy = S.jobs.some((j) => ACTIVE.has(j.status) || j.status === 'queued') || S.updateRunning || !S.tools?.ready;
  let delay = busy ? 700 : 2000;
  if (S.offline) delay = 3000;
  else if (document.hidden && !busy) delay = 6000;
  S.pollTimer = setTimeout(poll, delay);
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

/* ------------------------------------------------------------- настройки */

function applySettings(data) {
  S.settings = data.settings;
  S.home = data.home || S.home;
  S.platform = data.platform || S.platform;
  S.repo = data.repo || S.repo;
  S.appVersion = data.version || S.appVersion;
  fillSettings();
  renderTools(data.tools);
  updateEstimate();
}

async function loadSettings() {
  try { applySettings(await api('/api/settings')); } catch { /* офлайн */ }
}

function ageText(days) {
  if (days == null) return '';
  if (days <= 0) return 'вышла сегодня';
  if (days === 1) return 'вышла вчера';
  return `вышла ${days} ${plural(days, 'день', 'дня', 'дней')} назад`;
}

function fillSettings() {
  const s = S.settings;
  if (!s) return;
  const active = document.activeElement;
  for (const el of $$('#drawer [data-key]')) {
    if (el !== active) el.value = s[el.dataset.key] ?? '';
  }
  $$('#sParallel [role="radio"]').forEach((b) => b.setAttribute('aria-checked', String(Number(b.dataset.value) === s.parallel)));
  $('#templateExample').innerHTML = `Например: <code>${esc(TEMPLATE_EXAMPLES[s.template] || '')}</code>. В плейлистах перед именем ставится номер, а сами файлы идут в папку плейлиста.`;
  $('#cookiesHelp').textContent = COOKIES_HELP[S.platform] || COOKIES_HELP.linux;
  $('#sCookies option[value="safari"]').hidden = S.platform !== 'mac';
  $('#modKey').textContent = S.platform === 'mac' ? '⌘' : 'Ctrl';
  $('#aboutLine').textContent = `Качалка ${S.appVersion}. Свободная программа, исходный код открыт.`;
  $('#aboutField').hidden = !S.repo;
}

function toolStatus(t) {
  if (t.status === 'ready') return t.source === 'own' ? 'готово' : 'взят из системы';
  if (t.status === 'downloading') {
    const pct = t.total ? `${Math.floor((t.done / t.total) * 100)}% из ${bytes(t.total)}` : `скачано ${bytes(t.done) || '0 Б'}`;
    return `скачиваю: ${pct}${t.steps > 1 ? `, часть ${t.step} из ${t.steps}` : ''}`;
  }
  if (t.status === 'error') return t.error;
  if (t.status === 'checking') return 'проверяю';
  return 'жду очереди';
}

function toolIcon(t) {
  if (t.status === 'ready') return 'check-circle';
  if (t.status === 'error') return 'warning-circle';
  if (t.status === 'downloading') return 'download-simple';
  return 'circle-notch';
}

function renderTools(tools) {
  if (!tools) return;
  S.tools = tools;
  const failed = tools.items.some((t) => t.status === 'error');
  const setup = $('#setup');
  // Экран установки виден, пока чего-то не хватает: при первом запуске или после ошибки.
  setup.hidden = tools.ready && !failed;
  if (!setup.hidden) {
    setHtml($('#setupList'), tools.items.map((t) => `
      <li class="setup-item" data-status="${t.status}">
        <i class="ph ph-${toolIcon(t)}" aria-hidden="true"></i>
        <div><b>${esc(t.name)}</b><span>${esc(t.about)}</span></div>
        <span class="setup-state">${esc(t.status === 'error' ? 'не скачалось' : toolStatus(t))}</span>
      </li>`).join('') + (failed && !tools.installing
      ? '<li class="setup-retry"><button type="button" class="btn ghost small" data-act="tools"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i>Повторить</button></li>'
      : ''));
    $('#setupText').textContent = failed && !tools.installing
      ? 'Не всё получилось скачать. Проверь интернет и нажми «Повторить».'
      : 'Один раз скачиваю программы, которые делают всю работу. Это около 150 МБ, дальше всё запускается сразу.';
  }
  const find = $('#findBtn');
  if (!S.infoCtl) {
    find.disabled = !tools.ready;
    find.textContent = tools.ready ? 'Найти' : 'Готовлю…';
  }

  setHtml($('#toolList'), tools.items.map((t) => `
    <li data-status="${t.status}"><i class="ph ph-${toolIcon(t)}" aria-hidden="true"></i><b>${esc(t.name)}</b><span>${esc(toolStatus(t))}</span></li>`).join(''));
  const line = $('#ytdlpVersion');
  if (tools.version) {
    const old = tools.version_age != null && tools.version_age > 60;
    line.textContent = `yt-dlp ${tools.version}, ${ageText(tools.version_age)}.${old ? ' Пора обновить.' : ''}`;
    line.classList.toggle('old', old);
  } else {
    line.textContent = tools.ready ? 'Не получилось узнать версию yt-dlp.' : '';
  }
  $('#checkTools').disabled = tools.installing;
  renderUpdate(tools.update);
}

function flash(key, text, ok) {
  const msg = $(`.field-msg[data-for="${key}"]`);
  if (!msg) return;
  msg.textContent = text;
  msg.className = `field-msg ${ok ? 'ok' : 'bad'}`;
  clearTimeout(msg._timer);
  if (ok) msg._timer = setTimeout(() => { msg.textContent = ''; }, 1800);
}

async function saveSetting(patch, key) {
  try {
    applySettings(await api('/api/settings', patch));
    flash(key, 'Сохранено', true);
  } catch (err) {
    flash(key, err.message, false);
  }
}

$('#drawer').addEventListener('change', (e) => {
  const el = e.target.closest('[data-key]');
  if (el) saveSetting({ [el.dataset.key]: el.value }, el.dataset.key);
});

$('#drawer').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.target.matches('input[data-key]')) e.target.blur();
});

$('#sParallel').addEventListener('click', (e) => {
  const b = e.target.closest('[role="radio"]');
  if (b) saveSetting({ parallel: Number(b.dataset.value) }, 'parallel');
});

$('#pickFolder').addEventListener('click', async () => {
  const btn = $('#pickFolder');
  btn.disabled = true;
  btn.textContent = 'Жду выбора…';
  try {
    applySettings(await api('/api/pick-folder', {}));
  } catch (err) {
    flash('folder', err.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Выбрать…';
  }
});

$('#openFolder').addEventListener('click', () => api('/api/open-folder', {}).catch((err) => toast(err.message)));

function renderUpdate(up) {
  if (!up) return;
  const wasRunning = S.updateRunning;
  S.updateRunning = up.running;
  const btn = $('#updateBtn');
  btn.disabled = up.running;
  $('span', btn).textContent = up.running ? 'Обновляю…' : 'Обновить yt-dlp';
  const log = $('#updateLog');
  log.hidden = !up.log;
  if (log.textContent !== up.log) log.textContent = up.log || '';
  // Тихое автообновление при запуске не отвлекает тостом, если всё прошло хорошо.
  if (wasRunning && !up.running && !(up.auto && up.ok)) {
    toast(up.ok ? `yt-dlp обновлён, версия ${S.tools?.version || ''}` : 'Не получилось обновить yt-dlp. Подробности в настройках.');
  }
}

async function startUpdate() {
  try {
    const data = await api('/api/update', {});
    renderTools(data.tools);
    poll();
  } catch (err) {
    toast(err.message);
  }
}

$('#updateBtn').addEventListener('click', startUpdate);

async function checkTools() {
  try {
    renderTools((await api('/api/tools/install', {})).tools);
    poll();
  } catch (err) {
    toast(err.message);
  }
}

$('#checkTools').addEventListener('click', checkTools);

// Страница проекта и форма обращения открываются в обычном браузере.
$$('[data-open]').forEach((b) => b.addEventListener('click', () => {
  api('/api/open-url', { url: S.repo + b.dataset.open }).catch((err) => toast(err.message));
}));

function openSettings(focusSel) {
  fillSettings();
  const drawer = $('#drawer');
  const scrim = $('#scrim');
  if (drawer.hidden) {
    S.returnFocus = document.activeElement;
    drawer.hidden = false;
    scrim.hidden = false;
    for (const el of [drawer, scrim]) {
      el.classList.remove('enter');
      void el.offsetWidth;
      el.classList.add('enter');
    }
  }
  ($(focusSel || '#sFolder') || drawer).focus();
}

function closeSettings() {
  $('#drawer').hidden = true;
  $('#scrim').hidden = true;
  if (S.returnFocus && document.contains(S.returnFocus)) S.returnFocus.focus();
}

$('#openSettings').addEventListener('click', () => openSettings());
$('#closeSettings').addEventListener('click', closeSettings);
$('#scrim').addEventListener('click', closeSettings);

// Кнопки-подсказки в ошибках: «Включить куки», «Обновить yt-dlp».
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-act]');
  if (!b) return;
  if (b.dataset.act === 'cookies') openSettings('#sCookies');
  if (b.dataset.act === 'update') { openSettings('#updateBtn'); startUpdate(); }
  if (b.dataset.act === 'tools') checkTools();
});

// Переключатели с ролью radiogroup: стрелки двигают выбор, как в нативных контролах.
document.addEventListener('keydown', (e) => {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
  const current = e.target.closest('[role="radio"]');
  const group = current?.closest('[role="radiogroup"]');
  if (!group) return;
  const radios = $$('[role="radio"]', group);
  const step = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1;
  const next = radios[(radios.indexOf(current) + step + radios.length) % radios.length];
  e.preventDefault();
  next.click();
  // После клика блок мог перерисоваться: ищем кнопку заново по значению.
  const fresh = group.isConnected ? next : $(`[data-opt="${group.dataset.opt}"] [data-value="${next.dataset.value}"]`);
  fresh?.focus();
});

document.addEventListener('keydown', (e) => {
  const drawerOpen = !$('#drawer').hidden;
  if (e.key === 'Escape') {
    if (drawerOpen) closeSettings();
    else if (!$('#preview').hidden) closePreview();
    return;
  }
  if (e.key === 'Tab' && drawerOpen) {
    const items = $$('#drawer button, #drawer input, #drawer select').filter((el) => !el.disabled && el.offsetParent);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

/* ------------------------------------------------------------- старт */

(async function init() {
  await loadSettings();
  await poll();
  S.firstRender = false;
  urlInput.focus();
  checkClipboard();
})();
