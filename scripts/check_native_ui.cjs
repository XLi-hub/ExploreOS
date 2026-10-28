'use strict';
// Explicit zero-model browser smoke test on the owned ClawInstitute instance.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const {chromium} = require(path.join(root, '.runtime/browser/node_modules/playwright'));
let token = '';

(async () => {
  const record = JSON.parse(fs.readFileSync(path.join(root, '.runtime/service/process.json'), 'utf8'));
  assert(record.frontend_enabled, 'Start the owned service with its native frontend enabled');
  token = fs.readFileSync(path.join(root, '.runtime/service/home/token'), 'utf8').trim();
  const origin = `http://127.0.0.1:${record.frontend_port}`;
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    page.setDefaultTimeout(60000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + '/auth/login');
    await page.locator('input[type="password"]').fill(token);
    await page.getByRole('button', {name: /^(Log in|Sign in)$/}).click();
    await page.waitForFunction(() => Boolean(localStorage.getItem('moltbook_api_key')));
    await page.goto(origin + '/api/v1/exploreos/ui');
    await page.getByRole('button', {name: '＋ 新建探索', exact: true}).click();
    const name = 'ui_' + Date.now();
    await page.locator('[name="name"]').fill(name);
    await page.locator('[name="question"]').fill('怎样在改变问题后继续保留有用的分歧？');
    await page.getByRole('button', {name: '创建项目', exact: true}).click();
    await page.getByRole('heading', {name, exact: true}).waitFor();
    page.once('dialog', dialog => dialog.accept('simulated'));
    await page.getByRole('button', {name: '推进一轮', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 3);
    await page.getByRole('button', {name: '暂停', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#meta').textContent.includes('已暂停'));
    page.once('dialog', dialog => dialog.accept('现在重点检查新成员如何理解过去的异议。'));
    await page.getByRole('button', {name: '修改关注点', exact: true}).click();
    await page.getByRole('heading', {name: '现在重点检查新成员如何理解过去的异议。', exact: true}).waitFor();
    await page.getByRole('button', {name: '继续', exact: true}).click();
    page.once('dialog', dialog => dialog.accept('simulated'));
    await page.getByRole('button', {name: '推进一轮', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 6);
    const download = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出全部记录', exact: true}).click();
    const saved = await download;
    const exported = JSON.parse(fs.readFileSync(await saved.path(), 'utf8'));
    assert.equal(exported.state.question_revisions.length, 2);
    assert.equal(exported.kind, 'mechanical_fixture');
    assert(Object.values(exported.state.calls).every(call => call.backend === 'simulated'));
    await page.reload();
    await page.getByRole('heading', {name, exact: true}).waitFor();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 6);
    await page.locator('#projects button.selected').waitFor();
    const discussion = await page.locator('#native-discussion').getAttribute('href');
    assert(discussion.startsWith('/m/'));
    assert((await page.locator('#native-files').getAttribute('href')).startsWith('/workspace/'));
    await page.screenshot({path: path.join(root, '.runtime/native-exploration-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({path: path.join(root, '.runtime/native-exploration-mobile.png'), fullPage: true});
    await page.goto(origin + discussion);
    await page.getByRole('link', {name: 'Open exploration bootstrap', exact: false}).click();
    await page.getByRole('link', {name: 'ExploreOS 探索视图', exact: true}).click();
    await page.getByRole('heading', {name, exact: true}).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: native login, project controls, export/reopen, mobile layout and workshop entry (zero model calls).');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(token ? error.message.split(token).join('[redacted]') : error.message);
  process.exitCode = 1;
});
