'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createQueryRunner } = require('../retry.js');

test('成功查询返回 registered 结果', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 5, backoffMs: 1 });
  const r = await runner.run('861234', async () => [{ exists: true, jid: '861234@s.whatsapp.net' }]);
  assert.equal(r.registered, true);
  assert.equal(r.jid, '861234@s.whatsapp.net');
  assert.equal(runner.isThrottled(), false);
});

test('未注册号码返回 registered:false', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 5, backoffMs: 1 });
  const r = await runner.run('861234', async () => []);
  assert.equal(r.registered, false);
  assert.equal(r.jid, null);
});

test('失败一次后重连成功 → 返回结果且失败计数清零', async () => {
  let calls = 0;
  let reconnects = 0;
  const runner = createQueryRunner({
    maxRetries: 2, throttleThreshold: 5, backoffMs: 1,
    sleep: async () => {},
    reconnect: async () => { reconnects++; },
  });
  const query = async () => {
    calls++;
    if (calls === 1) throw new Error('Connection Closed');
    return [{ exists: false, jid: null }];
  };
  const r = await runner.run('861234', query);
  assert.equal(calls, 2);
  assert.equal(reconnects, 1);
  assert.equal(r.registered, false);
  assert.equal(runner.isThrottled(), false);
});

test('重试耗尽 → 返回 error 且 registered:null，未判风控', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 5, backoffMs: 1 });
  const r = await runner.run('861234', async () => { throw new Error('Connection Closed'); });
  assert.equal(r.registered, null);
  assert.ok(r.error.includes('Connection Closed'));
  assert.equal(runner.isThrottled(), false);
});

test('连续失败达阈值 → 风控中止，后续号码短路', async () => {
  const runner = createQueryRunner({ maxRetries: 2, throttleThreshold: 3, backoffMs: 1 });
  const query = async () => { throw new Error('Connection Closed'); };
  const r = await runner.run('1', query);
  assert.ok(r.error.includes('风控'));
  assert.equal(runner.isThrottled(), true);
  const r2 = await runner.run('2', query);
  assert.ok(r2.error.includes('风控'));
});

test('重连失败 → 中止本批', async () => {
  const runner = createQueryRunner({
    maxRetries: 2, throttleThreshold: 5, backoffMs: 1,
    sleep: async () => {},
    reconnect: async () => { throw new Error('已登出'); },
  });
  const r = await runner.run('861234', async () => { throw new Error('Connection Closed'); });
  assert.ok(r.error.includes('重连失败'));
  assert.equal(runner.isThrottled(), true);
});
