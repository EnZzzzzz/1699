'use strict';

// 单号查询重试器：查询失败时按退避重连重试，连续失败达到阈值判定风控并中止本批。
// 依赖注入（query / reconnect / sleep）便于单测；check.js 传入真实 Baileys socket。
function createQueryRunner({
  maxRetries = 2,
  throttleThreshold = 5,
  backoffMs = 3000,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  reconnect = async () => {},
} = {}) {
  let consecutiveFails = 0;
  let throttled = false;

  async function run(num, query) {
    if (throttled) {
      return { number: num, registered: null, error: '批次已风控中止' };
    }
    for (let attempt = 0; ; attempt++) {
      try {
        const res = await query(num);
        consecutiveFails = 0;
        const hit = res && res[0];
        return { number: num, registered: !!hit?.exists, jid: hit?.jid || null };
      } catch (e) {
        consecutiveFails += 1;
        if (consecutiveFails >= throttleThreshold) {
          throttled = true;
          return { number: num, registered: null,
                   error: `Connection Closed×${consecutiveFails} 疑似风控，中止本批` };
        }
        if (attempt < maxRetries) {
          try {
            await sleep(backoffMs * (attempt + 1));
            await reconnect();
          } catch (re) {
            throttled = true;
            return { number: num, registered: null,
                     error: `重连失败，中止本批: ${re.message || re}` };
          }
        } else {
          return { number: num, registered: null, error: String(e.message || e) };
        }
      }
    }
  }

  return { run, isThrottled: () => throttled };
}

module.exports = { createQueryRunner };
