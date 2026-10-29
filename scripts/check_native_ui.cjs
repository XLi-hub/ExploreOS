'use strict';
// Explicit zero-model browser smoke test on the owned ClawInstitute instance.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const {chromium} = require(path.join(root, '.runtime/browser/node_modules/playwright'));
let token = '';

(async () => {
  const record = JSON.parse(fs.readFileSync(path.join(root, '.runtime/service/process.json'), 'utf8'));
  assert(record.frontend_enabled, 'Start the owned service with its native frontend enabled');
  token = fs.readFileSync(path.join(root, '.runtime/service/home/token'), 'utf8').trim();
  const origin = `http://127.0.0.1:${record.frontend_port}`;
  const failedName = 'ui_fail_' + Date.now();
  execFileSync(path.join(root, '.venv/bin/python'), ['-c', `
import sys
from explore.engine import Project
from explore.models import SimulatedBackend
from explore.store import Client
p=Project.create(Client(),sys.argv[1],mode="single",question="Can a corrected mechanical attempt resume?",sources=[])
class Failed(SimulatedBackend):
    def call(self,*args,**kwargs):
        raise TimeoutError("Explicit zero-model browser recovery fixture")
try:
    p.advance(Failed())
except RuntimeError:
    pass
assert len(p.file.read()[0]["calls"]) == 1
`, failedName], {cwd: root, stdio: ['ignore', 'pipe', 'pipe']});
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
    await page.locator('#create-form [name="backend"]').selectOption('simulated');
    await page.locator('[name="question"]').fill('怎样在改变问题后继续保留有用的分歧？');
    await page.getByRole('button', {name: '创建项目', exact: true}).click();
    await page.locator('#create-dialog').waitFor({state: 'hidden'});
    await page.locator('#question').filter({hasText: '怎样在改变问题后继续保留有用的分歧？'}).waitFor();
    const name = new URL(page.url()).hash.slice(1);
    assert(/^q_[a-f0-9]{16}$/.test(name));
    await page.getByRole('button', {name: '添加材料', exact: true}).click();
    await page.locator('#source-file').setInputFiles({name: 'field-notes.md', mimeType: 'text/markdown',
      buffer: Buffer.from('初次访谈不能代表所有使用者。\n记录仍未解决的解释分歧。\n')});
    await page.locator('#source-form [name="title"]').fill('访谈片段');
    await page.getByRole('button', {name: '保存材料', exact: true}).click();
    await page.getByRole('heading', {name: '访谈片段', exact: true}).waitFor();
    assert((await page.locator('#content').innerText()).includes('1: 初次访谈不能代表所有使用者。'));
    await page.getByRole('button', {name: '发现与分歧', exact: true}).click();
    await page.getByRole('button', {name: '推进一轮', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 3);
    await page.locator('.project-controls summary').click();
    await page.getByRole('button', {name: '暂停', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#meta').textContent.includes('已暂停'));
    await page.getByRole('button', {name: '修改关注点', exact: true}).click();
    await page.locator('#control-form [name="value"]').fill('现在重点检查新成员如何理解过去的异议。');
    await page.locator('#control-form [type="submit"]').click();
    await page.getByRole('heading', {name: '现在重点检查新成员如何理解过去的异议。', exact: true}).waitFor();
    await page.getByRole('button', {name: '继续', exact: true}).click();
    await page.getByRole('button', {name: '推进一轮', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 6);
    await page.getByRole('button', {name: '追加轮次', exact: true}).click();
    await page.locator('#control-form [name="value"]').fill('1');
    await page.locator('#control-form [type="submit"]').click();
    await page.waitForFunction(() => document.querySelector('#meta').textContent.includes('2/3 轮'));
    await page.getByRole('button', {name: '推进一轮', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 9);
    const download = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出全部记录', exact: true}).click();
    const saved = await download;
    const exported = JSON.parse(fs.readFileSync(await saved.path(), 'utf8'));
    assert.equal(exported.state.question_revisions.length, 2);
    assert.equal(exported.kind, 'mechanical_fixture');
    assert.equal(exported.state.max_rounds, 3);
    assert.equal(Object.keys(exported.state.sources).length, 1);
    assert(Object.values(exported.state.calls).every(call => call.backend === 'simulated'));
    const briefDownload = page.waitForEvent('download');
    await page.getByRole('button', {name: '下载阶段简报', exact: true}).click();
    const brief = await briefDownload;
    const briefText = fs.readFileSync(await brief.path(), 'utf8');
    assert(briefText.includes('## 当前发现'));
    assert(briefText.includes('## 历史发现'));
    assert(briefText.includes('mechanical_fixture'));
    await page.reload();
    await page.getByRole('button', {name: '阶段成果', exact: true}).waitFor();
    await page.getByRole('heading', {name: '当前发现', exact: true}).waitFor();
    assert((await page.locator('#content').innerText()).includes('机械演示成果'));
    await page.getByRole('button', {name: '发现与分歧', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 9);
    await page.locator('#projects button.selected').waitFor();
    const discussion = await page.locator('#native-discussion').getAttribute('href');
    assert(discussion.startsWith('/m/'));
    assert((await page.locator('#native-files').getAttribute('href')).startsWith('/workspace/'));
    await page.screenshot({path: path.join(root, '.runtime/native-exploration-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({path: path.join(root, '.runtime/native-exploration-mobile.png'), fullPage: true});
    await page.getByRole('button', {name: '＋ 新建探索', exact: true}).click();
    const linkedName = 'ui_ref_' + Date.now();
    await page.locator('#create-form details summary').click();
    await page.locator('[name="name"]').fill(linkedName);
    await page.locator('#create-form [name="backend"]').selectOption('simulated');
    await page.locator('#create-form [name="question"]').fill('另一课题怎样使用有条件的旧发现？');
    await page.getByRole('button', {name: '创建项目', exact: true}).click();
    await page.locator('#question').filter({hasText: '另一课题怎样使用有条件的旧发现？'}).waitFor();
    await page.getByRole('button', {name: '跨课题记忆', exact: true}).click();
    await page.getByRole('button', {name: '引用其他课题发现', exact: true}).click();
    await page.locator('#memory-form [name="origin_name"]').selectOption(name);
    await page.waitForFunction(() => !document.querySelector('#memory-form [name="post_id"]').disabled);
    await page.locator('#memory-form [name="conditions"]').fill('仅适用于原来的访谈范围。');
    await page.locator('#memory-form [name="reason"]').fill('帮助检查新课题的适用边界。');
    await page.getByRole('button', {name: '保存带条件的引用', exact: true}).click();
    await page.getByText('适用条件：仅适用于原来的访谈范围。', {exact: true}).waitFor();
    assert.equal(await page.getByRole('link', {name: '打开来源课题', exact: true}).count(), 1);
    await page.screenshot({path: path.join(root, '.runtime/native-linked-memory-mobile.png'), fullPage: true});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.goto(origin + discussion);
    await page.getByRole('link', {name: /^Question/}).click();
    await page.getByRole('link', {name: 'Open exploration bootstrap', exact: false}).click();
    await page.getByRole('link', {name: 'ExploreOS 探索视图', exact: true}).click();
    await page.locator('#question').filter({hasText: '现在重点检查新成员如何理解过去的异议。'}).waitFor();
    await page.goto(origin + '/api/v1/exploreos/ui#' + failedName);
    await page.locator('#question').filter({hasText: 'Can a corrected mechanical attempt resume?'}).waitFor();
    await page.getByRole('button', {name: '运行状态', exact: true}).click();
    await page.getByRole('button', {name: '核对中断执行', exact: true}).click();
    await page.getByText('已保存', {exact: true}).waitFor();
    page.once('dialog', dialog => dialog.accept('机械替身已经修正，授权一次新的尝试。'));
    await page.getByRole('button', {name: '授权修正后重试', exact: true}).click();
    await page.getByRole('button', {name: '授权修正后重试', exact: true}).waitFor({state: 'detached'});
    await page.getByRole('button', {name: '推进一轮', exact: true}).click();
    await page.locator('#execution-form [type="submit"]').click();
    await page.getByRole('button', {name: '发现与分歧', exact: true}).click();
    await page.waitForFunction(() => document.querySelectorAll('#content article').length === 1);
    assert.deepEqual(errors, []);
    console.log('PASS: question-only creation, saved zero-model mode, material ingestion, focus/extra-round forms, readable brief download/reopen, qualified memory, legacy failure recovery, native workshop entry and mobile layout (zero model calls).');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(token ? error.message.split(token).join('[redacted]') : error.message);
  process.exitCode = 1;
});
