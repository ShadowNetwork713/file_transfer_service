'use strict';

const el = (id) => document.getElementById(id);

let local = null;
let peer = null;
let busy = false;

const addr = el('peer-url');
addr.value = location.port === '8765'
  ? 'http://127.0.0.1:8766'
  : 'http://127.0.0.1:8765';

function tag(id, label, kind) {
  const node = el(id);
  node.textContent = label;
  node.className = `status-tag ${kind}`;
}

function putStatus(prefix, data, isPeer) {
  el(`${prefix}-name`).textContent = `Нода ${data.nodeId}`;
  el(`${prefix}-marker`).textContent = data.nodeId.slice(0, 1).toUpperCase();
  el(`${prefix}-height`).textContent = String(data.height);
  el(`${prefix}-tip`).textContent = data.tipHash;
  el(`${prefix}-network`).textContent = data.networkId;
  el(`${prefix}-version`).textContent = `v${data.protocolVersion}`;

  tag(
    `${prefix}-status`,
    data.chainValid ? 'Корректна' : 'Повреждена',
    data.chainValid ? 'ok' : 'error'
  );
}

function clearPeer(message, kind = 'idle') {
  peer = null;
  el('peer-marker').textContent = '·';
  el('peer-name').textContent = message;

  for (const name of ['height', 'tip', 'network', 'version']) {
    el(`peer-${name}`).textContent = '—';
  }

  tag(
    'peer-status',
    kind === 'checking' ? 'Загрузка…' : kind === 'error' ? 'Ошибка' : 'Нет данных',
    kind
  );

  comparison();
}

function comparison() {
  const title = el('compare-title');
  const details = el('compare-details');

  if (!local || !peer) {
    title.textContent = 'Ожидаем подключения';
    details.textContent = 'Для сравнения нужно получить сведения об обеих нодах.';
    el('compare-icon').textContent = '·';

  } else if (local.height === peer.height && local.tipHash === peer.tipHash) {
    title.textContent = 'Истории совпадают';
    details.textContent = `Высота ${local.height}, одинаковый хеш вершины у обеих нод.`;
    el('compare-icon').textContent = '✓';

  } else {
    title.textContent = 'Обнаружено различие';
    details.textContent = `Высоты: ${local.height} / ${peer.height}. Обмен блоками выполняется вручную.`;
    el('compare-icon').textContent = '≠';
  }
}

function feedback(title, details, kind) {
  el('result-text').textContent = title;
  el('result-details').textContent = details;
  el('result-time').textContent = new Date().toLocaleTimeString('ru-RU');
  el('result-indicator').className = `result-indicator ${kind}`;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 6000);

  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal
    });

    const body = await response.json();

    if (!response.ok) {
      const err = new Error(body.message || `HTTP ${response.status}`);
      err.code = body.code || `HTTP_${response.status}`;
      err.state = body.status || 'ERROR';
      throw err;
    }

    return body;

  } catch (error) {
    if (error.name === 'AbortError') {
      const e = new Error('Превышено время ожидания ответа API');
      e.code = 'UI_TIMEOUT';
      throw e;
    }

    throw error;

  } finally {
    clearTimeout(timeout);
  }
}

function jsonPost(path, data) {
  return api(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
}

function errorMessage(err) {
  return `${err.code || 'NETWORK_ERROR'} · ${err.message || 'Сбой соединения'}`;
}

function setBusy(value) {
  busy = value;

  for (const id of [
    'connect-btn',
    'refresh-btn',
    'pull-btn',
    'push-btn',
    'create-btn'
  ]) {
    el(id).disabled = value;
  }

  el('connect-btn-text').textContent = value
    ? 'Выполняется…'
    : 'Запросить состояние';
}

async function refreshLocal() {
  const data = await api('/api/v1/status');

  local = data;
  putStatus('local', data, false);
  comparison();
}

async function refreshPeer() {
  clearPeer('Подключение…', 'checking');

  const url = addr.value.trim();

  if (!url) {
    throw Object.assign(
      new Error('Введите адрес пира'),
      { code: 'BAD_PEER_URL' }
    );
  }

  const data = await api(
    `/api/v1/peers/status?url=${encodeURIComponent(url)}`
  );

  peer = data;
  putStatus('peer', data, true);
  comparison();
}

async function action(task) {
  if (busy) return;

  setBusy(true);
  feedback('Выполняется запрос…', 'Ожидаем ответ API.', 'checking');

  try {
    await task();

  } catch (err) {
    feedback(
      err.state === 'REJECTED' ? 'Блок отклонён' : 'Ошибка операции',
      errorMessage(err),
      'error'
    );

    if (err.peerFailure) {
      clearPeer('Нет данных', 'error');
    }

  } finally {
    setBusy(false);
  }
}

async function connect() {
  await action(async () => {
    try {
      await refreshPeer();
    } catch (e) {
      e.peerFailure = true;
      throw e;
    }

    feedback(
      'Состояние получено',
      `Пир ${peer.nodeId} · высота ${peer.height} · цепочка ${peer.chainValid ? 'валидна' : 'повреждена'}.`,
      'ok'
    );
  });
}


el('connect-btn').addEventListener('click', connect);

addr.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    connect();
  }
});


el('refresh-btn').addEventListener('click', () => action(async () => {
  await refreshLocal();

  if (peer) {
    try {
      await refreshPeer();
    } catch (e) {
      e.peerFailure = true;
      throw e;
    }
  }

  feedback(
    'Данные обновлены',
    'Локальная нода и известный пир опрошены повторно.',
    'ok'
  );
}));


el('create-btn').addEventListener('click', () => action(async () => {
  const result = await jsonPost('/api/v1/demo/blocks', {});

  await refreshLocal();

  feedback(
    'Блок создан',
    `Новый блок #${result.blockIndex}, хеш: ${result.blockHash}.`,
    'ok'
  );
}));


el('pull-btn').addEventListener('click', () => action(async () => {
  if (!addr.value.trim()) {
    throw Object.assign(
      new Error('Введите адрес пира'),
      { code: 'BAD_PEER_URL' }
    );
  }

  try {
    const result = await jsonPost(
      '/api/v1/peers/pull',
      { peerUrl: addr.value.trim() }
    );

    await refreshLocal();
    await refreshPeer();

    feedback(
      result.status === 'ACCEPTED'
        ? 'Блок успешно принят'
        : 'Обмен завершён',
      `${result.status} · ${result.message}${result.blockIndex !== undefined ? ` · блок #${result.blockIndex}` : ''}`,
      'ok'
    );

  } catch (err) {
    await refreshLocal().catch(() => {});

    if (err.code && err.code.startsWith('PEER_')) {
      clearPeer('Нет данных', 'error');
    } else {
      await refreshPeer().catch(() => {});
    }

    throw err;
  }
}));


el('push-btn').addEventListener('click', () => action(async () => {
  if (!addr.value.trim()) {
    throw Object.assign(
      new Error('Введите адрес пира'),
      { code: 'BAD_PEER_URL' }
    );
  }

  try {
    const result = await jsonPost(
      '/api/v1/peers/push',
      { peerUrl: addr.value.trim() }
    );

    await refreshLocal();
    await refreshPeer();

    feedback(
      result.status === 'ACCEPTED'
        ? 'Блок успешно отправлен'
        : 'Обмен завершён',
      `${result.status} · ${result.message}${result.blockIndex !== undefined ? ` · блок #${result.blockIndex}` : ''}`,
      'ok'
    );

  } catch (err) {
    await refreshLocal().catch(() => {});

    if (err.code && err.code.startsWith('PEER_')) {
      clearPeer('Нет данных', 'error');
    } else {
      await refreshPeer().catch(() => {});
    }

    throw err;
  }
}));

refreshLocal().catch((err) => {
  tag('local-status', 'Ошибка', 'error');

  feedback(
    'Локальная нода недоступна',
    errorMessage(err),
    'error'
  );
});
