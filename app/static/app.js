const $ = s => document.querySelector(s);
let current = null;
let librarySources = new Map();
const show = (el, on = true) => el.classList.toggle('hidden', !on);

function notice(message, error = false) {
  const n = $('#notice');
  n.textContent = message;
  n.style.borderColor = error ? '#b3261e' : '#ed5b37';
  show(n, !!message);
}
function errorMessage(e) {
  return e?.detail?.message || e?.error?.message || e?.detail?.[0]?.msg || 'Ocorreu um erro inesperado.';
}
async function api(url, options = {}) {
  const headers = options.body instanceof FormData ? {} : {'Content-Type': 'application/json'};
  const r = await fetch(url, {...options, headers: {...headers, ...options.headers}});
  if (!r.ok) { let e = {}; try { e = await r.json(); } catch {} throw e; }
  return r.status === 204 ? null : r.json();
}
function fmt(seconds) {
  seconds = Math.round(seconds);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function sourceMode(local, reset = true) {
  show($('#analyze-form'), !local);
  show($('#upload-form'), local);
  $('#source-youtube').setAttribute('aria-pressed', String(!local));
  $('#source-local').setAttribute('aria-pressed', String(local));
  if (reset) {
    current = null;
    show($('#video'), false);
    show($('#job-form'), false);
    notice('');
  }
}
$('#source-youtube').onclick = () => sourceMode(false);
$('#source-local').onclick = () => sourceMode(true);

function setCurrent(source, reuse = false) {
  current = source;
  const local = source.source_type === 'local';
  sourceMode(local, false);
  $('#title').textContent = source.title;
  $('#duration').textContent = `${fmt(source.duration)} · ${local ? 'Arquivo do computador' : 'YouTube'}`;
  $('#thumb').src = source.thumbnail || '';
  show($('#thumb'), !!source.thumbnail);
  $('#quality').replaceChildren(new Option('Melhor disponível', ''));
  (source.resolutions || []).slice().reverse().forEach(x => $('#quality').add(new Option(`${x}p`, x)));
  $('#audio-format').value = local ? 'mp3' : 'm4a';
  $('#audio-clip').checked = false;
  $('#remove-music').checked = false;
  $('#reduce-noise').checked = false;
  $('#start').value = '';
  $('#end').value = '';
  document.querySelector(`[name=kind][value=${local ? 'audio' : reuse ? 'clip' : 'video'}]`).checked = true;
  show($('#output-modes'), !local);
  show($('#video'));
  show($('#job-form'));
  updateOptions();
}
$('#analyze-form').addEventListener('submit', async e => {
  e.preventDefault();
  notice('Analisando vídeo…');
  show($('#job-form'), false);
  try {
    setCurrent(await api('/api/analyze', {method: 'POST', body: JSON.stringify({url: $('#url').value})}));
    notice('');
  } catch (err) { notice(errorMessage(err), true); }
});
$('#upload-form').addEventListener('submit', async e => {
  e.preventDefault();
  const file = $('#local-file').files[0];
  if (!file) return;
  const data = new FormData();
  data.append('file', file);
  $('#upload-button').disabled = true;
  show($('#job-form'), false);
  notice('Importando e verificando o áudio…');
  try {
    setCurrent(await api('/api/sources/upload', {method: 'POST', body: data}));
    notice('Arquivo pronto. Escolha as opções e adicione à fila para converter em MP3.');
    loadLibrary();
  } catch (err) { notice(errorMessage(err), true); }
  finally { $('#upload-button').disabled = false; }
});
function updateOptions() {
  const kind = document.querySelector('[name=kind]:checked').value;
  const trim = kind === 'clip' || (kind === 'audio' && $('#audio-clip').checked);
  show($('#clip-options'), trim);
  $('#start').required = trim;
  $('#end').required = trim;
  show($('#audio-clip-label'), kind === 'audio');
  show($('#audio-label'), kind === 'audio');
  show($('#audio-ai-options'), kind === 'audio');
  show($('#quality-label'), kind !== 'audio');
}
document.querySelectorAll('[name=kind]').forEach(x => x.addEventListener('change', updateOptions));
$('#audio-clip').addEventListener('change', updateOptions);
$('#job-form').addEventListener('submit', async e => {
  e.preventDefault();
  if (!current) return;
  const kind = document.querySelector('[name=kind]:checked').value;
  const body = {kind, source_id: current.id, audio_format: $('#audio-format').value};
  if (kind === 'audio') {
    body.remove_music = $('#remove-music').checked;
    body.reduce_noise = $('#reduce-noise').checked;
  }
  if (kind !== 'audio' && $('#quality').value) body.resolution = Number($('#quality').value);
  if (kind === 'clip' || (kind === 'audio' && $('#audio-clip').checked)) {
    body.start = $('#start').value;
    body.end = $('#end').value;
  }
  try {
    const job = await api('/api/jobs', {method: 'POST', body: JSON.stringify(body)});
    notice('');
    show($('#progress'));
    show($('#download'), false);
    poll(job.id);
  } catch (err) { notice(errorMessage(err), true); }
});
async function poll(id) {
  try {
    const j = await api(`/api/jobs/${id}`);
    $('#progress-message').textContent = j.error_detail || j.message;
    $('#progress-value').textContent = `${Math.round(j.progress)}%`;
    $('#progress-bar').style.width = `${j.progress}%`;
    if (j.status === 'completed') { $('#download').href = j.download_url; show($('#download')); loadLibrary(); return; }
    if (j.status === 'failed') { notice(j.error_detail || 'Falha no processamento.', true); return; }
    setTimeout(() => poll(id), 1000);
  } catch (err) { notice(errorMessage(err), true); }
}
async function loadLibrary() {
  try {
    const data = await api('/api/library');
    librarySources = new Map(data.sources.map(s => [s.id, s]));
    const results = data.results.map(r => `<div class="item"><div><h3>${escapeHtml(r.filename)}</h3><p>${escapeHtml(r.kind)} · ${(r.size / 1048576).toFixed(1)} MB</p></div><div class="actions"><a href="/api/files/${encodeURIComponent(r.id)}">Baixar</a><button data-action="remove-file" data-id="${escapeHtml(r.id)}">Excluir</button></div></div>`);
    const sources = data.sources.map(s => `<div class="item"><div><h3>${escapeHtml(s.title)}</h3><p>${s.source_type === 'local' ? 'Arquivo do computador' : 'Fonte ' + (s.status === 'ready' ? 'armazenada' : 'catalogada')} · ${fmt(s.duration)}</p></div><div class="actions"><button data-action="use-source" data-id="${escapeHtml(s.id)}">${s.source_type === 'local' ? 'Converter áudio' : 'Novo corte'}</button><button data-action="remove-source" data-id="${escapeHtml(s.id)}">Excluir</button></div></div>`);
    $('#library-list').innerHTML = [...results, ...sources].join('') || '<div class="empty">Sua biblioteca ainda está vazia.</div>';
  } catch (err) { notice(errorMessage(err), true); }
}
$('#library-list').addEventListener('click', async e => {
  const button = e.target.closest('button[data-action]');
  if (!button) return;
  const {action, id} = button.dataset;
  if (action === 'use-source') {
    const source = librarySources.get(id);
    if (source) { setCurrent(source, true); notice(''); scrollTo({top: 0, behavior: 'smooth'}); }
    return;
  }
  const isFile = action === 'remove-file';
  if (!confirm(isFile ? 'Excluir este arquivo?' : 'Excluir esta fonte da biblioteca? O arquivo original do seu computador é preservado.')) return;
  try {
    await api(`/api/${isFile ? 'files' : 'sources'}/${encodeURIComponent(id)}`, {method: 'DELETE'});
    loadLibrary();
    if (!isFile && current?.id === id) sourceMode(current.source_type === 'local');
  } catch (err) { notice(errorMessage(err), true); }
});
function escapeHtml(value) {
  return String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}
$('#refresh').onclick = loadLibrary;
loadLibrary();
api('/api/health').then(h => { if (!h.ok) notice('FFmpeg/FFprobe não foram encontrados. Instale-os antes de processar arquivos.', true); }).catch(e => notice(errorMessage(e), true));
