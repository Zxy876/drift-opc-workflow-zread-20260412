const mineflayer = require('mineflayer');

const host = process.env.MC_HOST || '127.0.0.1';
const port = Number(process.env.MC_PORT || 25565);
const username = process.env.MC_USERNAME || 'DriftBotLocal';
const auth = process.env.MC_AUTH || 'offline';
const version = process.env.MC_VERSION || false;
const timeoutMs = Number(process.env.MC_CONNECT_TIMEOUT_MS || 20000);

const startedAt = Date.now();
let settled = false;

function done(code, message) {
  if (settled) return;
  settled = true;
  const cost = Date.now() - startedAt;
  console.log(`[bot-smoke] ${message} (elapsed=${cost}ms)`);
  process.exit(code);
}

console.log(`[bot-smoke] connecting host=${host} port=${port} username=${username} auth=${auth} version=${version || 'auto'}`);

const bot = mineflayer.createBot({
  host,
  port,
  username,
  auth,
  version,
  connectTimeout: timeoutMs,
});

bot.once('login', () => {
  console.log('[bot-smoke] login event received');
});

bot.once('spawn', () => {
  console.log('[bot-smoke] spawn event received; bot joined world');
  setTimeout(() => {
    try {
      bot.quit('bot smoke test complete');
    } catch (err) {
      console.log(`[bot-smoke] quit error: ${String(err && err.message ? err.message : err)}`);
    }
    done(0, 'join success');
  }, 3000);
});

bot.on('kicked', (reason) => {
  done(2, `kicked: ${typeof reason === 'string' ? reason : JSON.stringify(reason)}`);
});

bot.on('end', (reason) => {
  if (!settled) {
    done(3, `connection ended before spawn: ${String(reason || 'unknown')}`);
  }
});

bot.on('error', (err) => {
  done(4, `error: ${String(err && err.message ? err.message : err)}`);
});

setTimeout(() => {
  done(5, 'timeout waiting for spawn');
}, timeoutMs + 5000);
