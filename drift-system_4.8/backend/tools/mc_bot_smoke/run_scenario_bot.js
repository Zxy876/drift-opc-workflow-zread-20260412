const fs = require('fs');
const path = require('path');
const mineflayer = require('mineflayer');

const host = process.env.MC_HOST || '127.0.0.1';
const port = Number(process.env.MC_PORT || 25565);
const username = process.env.MC_USERNAME || 'DriftScenarioBot';
const auth = process.env.MC_AUTH || 'offline';
const version = process.env.MC_VERSION || false;
const timeoutMs = Number(process.env.MC_CONNECT_TIMEOUT_MS || 30000);
const actionDelayMs = Number(process.env.MC_ACTION_DELAY_MS || 2500);
const settleMs = Number(process.env.MC_SETTLE_MS || 5000);
const defaultExpectTimeoutMs = Number(process.env.MC_EXPECT_TIMEOUT_MS || 4500);
const messageHistoryLimit = Number(process.env.MC_MESSAGE_HISTORY_LIMIT || 400);
const backendBase = process.env.MC_BACKEND_BASE || 'http://127.0.0.1:8000/world';
const backendTimeoutMs = Number(process.env.MC_BACKEND_TIMEOUT_MS || 12000);
const scenarioFile = process.env.MC_SCENARIO_FILE || '';

if (!scenarioFile) {
  console.error('[bot-scenario] missing MC_SCENARIO_FILE');
  process.exit(10);
}

const scenarioPath = path.resolve(scenarioFile);
if (!fs.existsSync(scenarioPath)) {
  console.error(`[bot-scenario] scenario file not found: ${scenarioPath}`);
  process.exit(11);
}

function asBool(value, fallback = false) {
  if (value === undefined || value === null || value === '') {
    return fallback;
  }
  const token = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(token)) return true;
  if (['0', 'false', 'no', 'off'].includes(token)) return false;
  return fallback;
}

function toStringList(raw) {
  if (Array.isArray(raw)) {
    return raw
      .map((item) => String(item || '').trim())
      .filter((item) => item.length > 0);
  }
  if (typeof raw === 'string') {
    const text = raw.trim();
    return text ? [text] : [];
  }
  return [];
}

function resolveTemplateString(value) {
  const text = String(value || '');
  return text
    .replaceAll('{{player}}', username)
    .replaceAll('{{username}}', username)
    .replaceAll('{{host}}', host)
    .replaceAll('{{port}}', String(port));
}

function resolveTemplateValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => resolveTemplateValue(item));
  }
  if (value && typeof value === 'object') {
    const out = {};
    for (const [key, item] of Object.entries(value)) {
      out[key] = resolveTemplateValue(item);
    }
    return out;
  }
  if (typeof value === 'string') {
    return resolveTemplateString(value);
  }
  return value;
}

let actions;
let scenarioConfig = {};
try {
  const raw = fs.readFileSync(scenarioPath, 'utf8');
  const parsed = JSON.parse(raw);
  if (Array.isArray(parsed)) {
    actions = parsed;
    scenarioConfig = {};
  } else if (parsed && typeof parsed === 'object') {
    actions = Array.isArray(parsed.actions) ? parsed.actions : [];
    scenarioConfig = parsed;
  } else {
    actions = [];
    scenarioConfig = {};
  }
} catch (err) {
  console.error(`[bot-scenario] failed to parse scenario: ${String(err && err.message ? err.message : err)}`);
  process.exit(12);
}

if (actions.length === 0) {
  console.error('[bot-scenario] scenario is empty');
  process.exit(13);
}

const startedAt = Date.now();
let settled = false;
let sent = 0;
let received = 0;
let strictUnknownCommand = asBool(
  scenarioConfig.failOnUnknownCommand,
  asBool(process.env.MC_FAIL_ON_UNKNOWN_COMMAND, true)
);
const messageLog = [];

function elapsed() {
  return Date.now() - startedAt;
}

function done(code, message) {
  if (settled) return;
  settled = true;
  console.log(`[bot-scenario] ${message} (sent=${sent} received=${received} elapsed=${elapsed()}ms)`);
  process.exit(code);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pushMessage(source, text) {
  const normalized = String(text || '').trim();
  if (!normalized) return;
  messageLog.push({
    source,
    text: normalized,
    lower: normalized.toLowerCase(),
    at: Date.now(),
  });
  if (messageLog.length > messageHistoryLimit) {
    messageLog.splice(0, messageLog.length - messageHistoryLimit);
  }
}

function containsAny(messages, tokens) {
  for (const token of tokens) {
    const needle = String(token || '').trim().toLowerCase();
    if (!needle) continue;
    if (messages.some((row) => row.lower.includes(needle))) {
      return token;
    }
  }
  return null;
}

function tailMessages(startIndex, limit = 6) {
  const rows = messageLog.slice(Math.max(0, startIndex));
  return rows.slice(Math.max(0, rows.length - limit)).map((row) => row.text);
}

function getByPath(payload, path) {
  if (!path || typeof path !== 'string') return undefined;
  const segments = path.split('.').map((item) => item.trim()).filter(Boolean);
  let current = payload;

  for (const seg of segments) {
    const match = seg.match(/^([^[\]]+)(?:\[(\d+)\])?$/);
    if (!match) return undefined;

    const key = match[1];
    if (current == null || typeof current !== 'object' || !(key in current)) {
      return undefined;
    }
    current = current[key];

    if (match[2] !== undefined) {
      const idx = Number(match[2]);
      if (!Array.isArray(current) || Number.isNaN(idx) || idx < 0 || idx >= current.length) {
        return undefined;
      }
      current = current[idx];
    }
  }

  return current;
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function assertJsonMap(action, responsePayload, stepIndex, stepTotal) {
  const expectedMapRaw = action.expectJson;
  if (!expectedMapRaw || typeof expectedMapRaw !== 'object' || Array.isArray(expectedMapRaw)) {
    return;
  }

  const expectedMap = resolveTemplateValue(expectedMapRaw);
  for (const [pathExpr, expected] of Object.entries(expectedMap)) {
    const actual = getByPath(responsePayload, pathExpr);
    if (!deepEqual(actual, expected)) {
      throw new Error(
        `step ${stepIndex + 1}/${stepTotal} expectJson failed: ${pathExpr} expected=${JSON.stringify(expected)} actual=${JSON.stringify(actual)}`
      );
    }
  }
}

async function backendRequest(method, rawPath, payload) {
  if (typeof fetch !== 'function') {
    throw new Error('global fetch is unavailable; Node.js >=18 is required for backend_* actions');
  }

  const resolvedPath = resolveTemplateString(rawPath || '');
  if (!resolvedPath) {
    throw new Error('backend action missing path');
  }

  const targetUrl = resolvedPath.startsWith('http://') || resolvedPath.startsWith('https://')
    ? resolvedPath
    : `${backendBase.replace(/\/$/, '')}/${resolvedPath.replace(/^\//, '')}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), backendTimeoutMs);

  const options = {
    method,
    headers: {
      'content-type': 'application/json',
    },
    signal: controller.signal,
  };

  if (method !== 'GET' && payload !== undefined) {
    options.body = JSON.stringify(resolveTemplateValue(payload));
  }

  try {
    const resp = await fetch(targetUrl, options);
    const text = await resp.text();
    let parsed;
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch {
      parsed = { _raw: text };
    }

    if (!resp.ok) {
      throw new Error(`backend ${method} ${targetUrl} failed: status=${resp.status} body=${text.slice(0, 300)}`);
    }

    return { url: targetUrl, payload: parsed };
  } finally {
    clearTimeout(timer);
  }
}

async function waitForActionExpectations(action, stepIndex, stepTotal, delayMs, startIndex) {
  const expectAny = toStringList(action.expectAny || action.expect);
  const rejectAny = toStringList(action.rejectAny);
  if (expectAny.length === 0 && rejectAny.length === 0) {
    return;
  }

  const expectTimeoutMs = Number(
    action.expectTimeoutMs ||
      action.expectTimeout ||
      defaultExpectTimeoutMs ||
      Math.max(1500, delayMs)
  );
  const deadline = Date.now() + Math.max(300, expectTimeoutMs);

  while (Date.now() < deadline) {
    const rows = messageLog.slice(Math.max(0, startIndex));

    if (rejectAny.length > 0) {
      const hit = containsAny(rows, rejectAny);
      if (hit) {
        throw new Error(`step ${stepIndex + 1}/${stepTotal} hit rejected text: ${hit}`);
      }
    }

    if (expectAny.length === 0) {
      return;
    }

    const matched = containsAny(rows, expectAny);
    if (matched) {
      console.log(`[bot-scenario] step=${stepIndex + 1}/${stepTotal} expectation matched: ${matched}`);
      return;
    }

    await sleep(120);
  }

  const tail = tailMessages(startIndex);
  throw new Error(
    `step ${stepIndex + 1}/${stepTotal} expectation timeout; expected any of ${JSON.stringify(expectAny)}; recent=${JSON.stringify(tail)}`
  );
}

console.log(`[bot-scenario] connecting host=${host} port=${port} username=${username} auth=${auth} scenario=${scenarioPath}`);
console.log(`[bot-scenario] strictUnknownCommand=${strictUnknownCommand}`);
console.log(`[bot-scenario] backendBase=${backendBase}`);

const bot = mineflayer.createBot({
  host,
  port,
  username,
  auth,
  version,
  connectTimeout: timeoutMs,
});

bot.on('messagestr', (msg) => {
  received += 1;
  pushMessage('messagestr', msg);
  console.log(`[server] ${msg}`);
  if (strictUnknownCommand && /unknown command/i.test(String(msg || ''))) {
    done(21, `unknown command detected: ${msg}`);
  }
});

bot.on('chat', (name, msg) => {
  received += 1;
  pushMessage('chat', `<${name}> ${msg}`);
  console.log(`[chat] <${name}> ${msg}`);
});

bot.once('login', () => {
  console.log('[bot-scenario] login event');
});

bot.once('spawn', async () => {
  console.log('[bot-scenario] spawn event');
  try {
    for (let i = 0; i < actions.length; i += 1) {
      const action = actions[i] || {};
      const type = String(action.type || 'chat').toLowerCase();
      const delay = Number(action.delayMs || action.delay || actionDelayMs);
      const stepStartIndex = messageLog.length;

      if (type === 'wait') {
        const ms = Number(action.ms || delay || actionDelayMs);
        console.log(`[bot-scenario] step=${i + 1}/${actions.length} wait ${ms}ms`);
        await sleep(ms);
        await waitForActionExpectations(action, i, actions.length, ms, stepStartIndex);
        continue;
      }

      if (type !== 'chat') {
        if (type === 'backend_post' || type === 'backend_get') {
          const method = type === 'backend_get' ? 'GET' : 'POST';
          const path = String(action.path || '').trim();
          const body = action.body;
          console.log(`[bot-scenario] step=${i + 1}/${actions.length} ${type}: ${path}`);
          const backendResp = await backendRequest(method, path, body);
          console.log(`[bot-scenario] step=${i + 1}/${actions.length} backend ok url=${backendResp.url}`);
          assertJsonMap(action, backendResp.payload, i, actions.length);
          await waitForActionExpectations(action, i, actions.length, delay, stepStartIndex);
          await sleep(delay);
          continue;
        }

        console.log(`[bot-scenario] step=${i + 1}/${actions.length} skip unsupported type=${type}`);
        await sleep(delay);
        await waitForActionExpectations(action, i, actions.length, delay, stepStartIndex);
        continue;
      }

      const text = String(action.text || '').trim();
      if (!text) {
        console.log(`[bot-scenario] step=${i + 1}/${actions.length} skip empty chat text`);
        await sleep(delay);
        await waitForActionExpectations(action, i, actions.length, delay, stepStartIndex);
        continue;
      }

      console.log(`[bot-scenario] step=${i + 1}/${actions.length} chat: ${text}`);
      bot.chat(text);
      sent += 1;
      await waitForActionExpectations(action, i, actions.length, delay, stepStartIndex);
      await sleep(delay);
    }

    await sleep(settleMs);
    try {
      bot.quit('scenario complete');
    } catch (err) {
      console.log(`[bot-scenario] quit error: ${String(err && err.message ? err.message : err)}`);
    }
    done(0, 'scenario complete');
  } catch (err) {
    done(20, `scenario execution failed: ${String(err && err.message ? err.message : err)}`);
  }
});

bot.on('kicked', (reason) => {
  done(2, `kicked: ${typeof reason === 'string' ? reason : JSON.stringify(reason)}`);
});

bot.on('end', (reason) => {
  if (!settled) {
    done(3, `connection ended before scenario complete: ${String(reason || 'unknown')}`);
  }
});

bot.on('error', (err) => {
  done(4, `error: ${String(err && err.message ? err.message : err)}`);
});

setTimeout(() => {
  done(5, 'timeout waiting for scenario completion');
}, timeoutMs + Math.max(settleMs, actions.length * actionDelayMs) + 15000);
