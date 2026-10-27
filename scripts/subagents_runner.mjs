// One foreground leaf through pi-subagents' public structured delegation API.
import fs from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';

process.umask(0o077);
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const modules = resolve(root, '.runtime/subagents/node_modules');
const load = relative => import(pathToFileURL(resolve(modules, relative)).href);
const requireRuntime = createRequire(resolve(root, '.runtime/subagents/package.json'));
const pluginApi = specifier => import(pathToFileURL(requireRuntime.resolve(specifier)).href);
for (const [name, version] of Object.entries({
  '@earendil-works/pi-coding-agent': '1.4.0', '@earendil-works/pi-ai': '1.4.0',
  '@earendil-works/pi-agent-core': '1.4.0', 'pi-subagents': '0.82.0',
})) {
  if (JSON.parse(fs.readFileSync(resolve(modules, name, 'package.json'))).version !== version) {
    throw new Error('Subagent dependency differs from the pinned runtime');
  }
}
if (process.argv.includes('--check')) {
  process.stdout.write(JSON.stringify({ pi: '1.4.0', subagents: '0.82.0', model_requests: 0 }) + '\n');
  process.exit(0);
}
let input = '';
for await (const chunk of process.stdin) {
  input += chunk;
  if (Buffer.byteLength(input) > 100_000) throw new Error('Bounded invocation input exceeded');
}
const request = JSON.parse(input);
const endpoint = new URL(request.base_url);
if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1') throw new Error('Only loopback relay is allowed');
const hostDir = resolve(request.host_dir);
const receiptPath = resolve(request.receipt_path);
if (!receiptPath.startsWith(dirname(hostDir) + '/')) throw new Error('Receipt must stay in this invocation directory');
fs.mkdirSync(hostDir, { recursive: true, mode: 0o700 });
process.env.PI_CODING_AGENT_DIR = hostDir;
process.env.PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT = resolve(modules, '@earendil-works/pi-coding-agent');
const identity = { requestId: request.request_id, ownerRunId: request.owner_run_id, nodeId: request.node_id };
let receipt = { version: 1, backend: 'pi-subagents', call_id: request.call_id, ...identity,
  state: 'preparing', emitted: false, provider_requests: 0, pi_version: '1.4.0', plugin_version: '0.82.0' };
// Exclusive creation is intentional: a retained identity never authorizes redispatch.
const initial = fs.openSync(receiptPath, 'wx', 0o600);
fs.writeFileSync(initial, JSON.stringify(receipt));
fs.fsyncSync(initial);
fs.closeSync(initial);
function save(values) {
  receipt = { ...receipt, ...values };
  const temporary = receiptPath + '.pending';
  const fd = fs.openSync(temporary, 'w', 0o600);
  fs.writeFileSync(fd, JSON.stringify(receipt));
  fs.fsyncSync(fd);
  fs.closeSync(fd);
  fs.renameSync(temporary, receiptPath);
  const directory = fs.openSync(dirname(receiptPath), 'r');
  try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
}
let bus, session, cancelled = false, settled = false, ceiling;
let cancelEvent;
const abort = () => {
  cancelled = true;
  if (bus && receipt.emitted && !settled) bus.emit(cancelEvent, identity);
};
process.on('SIGTERM', abort);
process.on('SIGINT', abort);
try {
  const sdk = await load('@earendil-works/pi-coding-agent/dist/index.js');
  const { InMemoryCredentialStore } = await load('@earendil-works/pi-ai/dist/index.js');
  const { stream } = await load('@earendil-works/pi-ai/dist/api/anthropic-messages.js');
  const { default: plugin } = await pluginApi('pi-subagents');
  const { registerSubagentCapabilityCeiling, resolveCurrentSubagentCapabilityCeiling } = await pluginApi('pi-subagents/capability-ceiling');
  const { resolveSubagentLaunchContract } = await pluginApi('pi-subagents/preflight');
  const delegation = await pluginApi('pi-subagents/delegation');
  cancelEvent = delegation.SUBAGENT_DELEGATION_CANCEL_EVENT;
  const provider = 'exploreos-relay';
  const modelConfig = { id: 'deepseek-flash', name: 'Authorized relay model', api: 'anthropic-messages',
    reasoning: false, input: ['text'], contextWindow: 32_000, maxTokens: 900,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } };
  const runtime = await sdk.ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    modelsStorePath: resolve(hostDir, 'model-cache.json'), allowModelNetwork: false, refreshOnCreate: false });
  runtime.registerProvider(provider, { api: 'anthropic-messages', apiKey: request.gateway_token,
    baseUrl: endpoint.href, models: [modelConfig], streamSimple: (model, context, options) => {
      if (receipt.provider_requests >= 1) throw new Error('Only one supplier request per leaf');
      save({ provider_requests: receipt.provider_requests + 1 });
      return stream(model, context, { ...options, apiKey: request.gateway_token, maxRetries: 0,
        maxTokens: 900, thinkingEnabled: false, cacheRetention: 'none', timeoutMs: 60_000 });
    } });
  // The child factory reads these same isolated settings; nothing comes from user config.
  fs.writeFileSync(resolve(hostDir, 'settings.json'), JSON.stringify({
    retry: { enabled: false, maxRetries: 0 }, compaction: { enabled: false },
    defaultTools: [], extensions: [], skills: [],
  }), { mode: 0o600 });
  const configDir = resolve(hostDir, 'extensions/subagent');
  fs.mkdirSync(configDir, { recursive: true, mode: 0o700 });
  fs.writeFileSync(resolve(configDir, 'config.json'), JSON.stringify({
    scheduledRuns: { enabled: false }, missions: { enabled: false }, watchdog: { enabled: false },
    maxSubagentSpawnsPerRun: 1, maxSubagentSpawnsPerSession: 1,
    intercomBridge: { mode: 'off' }, defaultSubagentContext: 'fresh',
  }), { mode: 0o600 });
  let api;
  const bridge = pi => { api = pi; bus = pi.events; };
  const settings = sdk.SettingsManager.create(process.cwd(), hostDir, { projectTrusted: false });
  const loader = new sdk.DefaultResourceLoader({ cwd: process.cwd(), agentDir: hostDir,
    settingsManager: settings, noExtensions: true, extensionFactories: [plugin, bridge],
    noSkills: true, noContextFiles: true, noPromptTemplates: true, noThemes: true,
    systemPrompt: 'ExploreOS delegation host; this parent never calls a model.' });
  await loader.reload();
  if (loader.getExtensions().errors.length) throw new Error('Required host extension failed to load');
  ({ session } = await sdk.createAgentSession({ cwd: process.cwd(), agentDir: hostDir,
    modelRuntime: runtime, model: runtime.getModel(provider, 'deepseek-flash'), thinkingLevel: 'off',
    tools: [], resourceLoader: loader, sessionManager: sdk.SessionManager.inMemory(), settingsManager: settings }));
  const startupErrors = [];
  await session.bindExtensions({ mode: 'print', onError: error => startupErrors.push(String(error.error)) });
  if (startupErrors.length) throw new Error('Host extension startup failed: ' + startupErrors.join('; '));
  save({ parent_session_id: session.sessionManager.getSessionId() });
  const definition = {
    name: 'exploreos-leaf', description: 'Bounded ExploreOS exploration participant',
    systemPromptMode: 'replace', tools: [], excludeTools: ['*'], allowNestedSubagents: false,
    inheritProjectContext: false, inheritGlobalContext: false, inheritSkills: false,
    defaultContext: 'fresh', async: false, model: `${provider}/deepseek-flash`, thinking: 'off',
    extensions: [], skills: [], outputMode: 'inline',
  };
  const agentDirectory = resolve(hostDir, 'agents');
  fs.mkdirSync(agentDirectory, { recursive: true, mode: 0o700 });
  fs.writeFileSync(resolve(agentDirectory, 'exploreos-leaf.md'),
    '---\n' + Object.entries(definition).map(([key, value]) => key + ': ' + (Array.isArray(value) ? value.join(', ') : String(value))).join('\n') +
    '\n---\n\n' + request.system_prompt + '\n', { mode: 0o600 });
  ceiling = registerSubagentCapabilityCeiling({ sessionId: session.sessionManager.getSessionId(),
    source: 'exploreos', ceiling: { allowedAgents: ['exploreos-leaf'], allowedTools: [], denyExtensions: true } });
  const task = 'EXPLOREOS_TASK_BEGIN\n' + JSON.stringify(request.messages) + '\nEXPLOREOS_TASK_END';
  const preflight = await resolveSubagentLaunchContract({ agent: 'exploreos-leaf', task,
    context: 'fresh', cwd: process.cwd(), model: `${provider}/deepseek-flash`, thinking: 'off',
    projectTrusted: false, runtimeSnapshotHost: api, availableModels: runtime.getAvailableSnapshot(),
    capabilityCeiling: resolveCurrentSubagentCapabilityCeiling(session.sessionManager.getSessionId()),
    intercomBridge: { mode: 'off' }, skill: false, artifacts: false,
    sessionRoot: resolve(hostDir, 'sessions'), parentSessionId: session.sessionManager.getSessionId() });
  if (!preflight.ok) throw new Error('Subagent launch preflight rejected: ' + preflight.message);
  if (preflight.contract.tools.effectiveAllowlist.length || preflight.contract.context !== 'fresh'
      || preflight.contract.inheritProjectContext || preflight.contract.inheritGlobalContext || preflight.contract.inheritSkills
      || resolve(preflight.contract.agent.filePath) !== resolve(agentDirectory, 'exploreos-leaf.md')) {
    throw new Error('Leaf launch profile was widened or replaced');
  }
  save({ preflight_digest: preflight.contract.digest, preflight_launch_digest: preflight.contract.launchContractDigest,
    profile: { context: preflight.contract.context, tools: preflight.contract.tools.effectiveAllowlist,
      inheritProjectContext: preflight.contract.inheritProjectContext, inheritGlobalContext: preflight.contract.inheritGlobalContext,
      inheritSkills: preflight.contract.inheritSkills, agent_file: preflight.contract.agent.filePath } });
  if (cancelled) throw new Error('Cancelled before delegation');
  const terminal = new Promise((resolveResult, rejectResult) => {
    const matches = value => value.requestId === identity.requestId && value.ownerRunId === identity.ownerRunId && value.nodeId === identity.nodeId;
    bus.on(delegation.SUBAGENT_DELEGATION_STARTED_EVENT, value => { if (matches(value)) save({ state: 'running' }); });
    bus.on(delegation.SUBAGENT_DELEGATION_UPDATE_EVENT, value => { if (matches(value) && value.runId) save({ runId: value.runId }); });
    bus.on(delegation.SUBAGENT_DELEGATION_RESPONSE_EVENT, value => {
      if (!matches(value) || settled) return;
      settled = true;
      save({ state: 'terminal', response: value, runId: value.runId ?? receipt.runId });
      resolveResult(value);
    });
    setTimeout(() => { if (!settled) { abort(); rejectResult(new Error('Delegation deadline exceeded')); } }, 85_000).unref();
  });
  save({ emitted: true });
  bus.emit(delegation.SUBAGENT_DELEGATION_REQUEST_EVENT, { ...identity,
    agent: 'exploreos-leaf', task, context: 'fresh', cwd: process.cwd(), model: `${provider}/deepseek-flash`,
    thinking: 'off', timeoutMs: 80_000, toolBudget: { hard: 0, block: '*' },
    skill: false, artifacts: false, intercomBridge: { mode: 'off' }, result: { kind: 'text' } });
  const response = await terminal;
  if (response.status !== 'completed' || response.result?.kind !== 'text' || receipt.provider_requests !== 1) {
    throw new Error('Delegated leaf did not complete: ' + response.status);
  }
  if (response.launchContractDigest !== receipt.preflight_launch_digest) throw new Error('Launch contract changed after preflight');
  const result = { result: response.result.text, pi_version: '1.4.0', plugin_version: '0.82.0',
    provider_requests: receipt.provider_requests, session_id: receipt.parent_session_id,
    events: [], delegation: { ...identity, runId: receipt.runId, status: response.status,
      launchContractDigest: response.launchContractDigest }, receipt_path: receiptPath };
  await new Promise((resolveWrite, rejectWrite) => process.stdout.write(JSON.stringify(result) + '\n',
    error => error ? rejectWrite(error) : resolveWrite()));
} catch (error) {
  save({ host_error: { type: error.name, message: error.message }, state: settled ? receipt.state : 'host_failed' });
  process.stderr.write(JSON.stringify({ type: error.name, message: error.message }) + '\n');
  process.exitCode = 1;
} finally {
  ceiling?.dispose();
  if (session) {
    try { await session.extensionRunner.emit('session_shutdown', { type: 'session_shutdown', reason: 'quit' }); } catch {}
    session.dispose();
    save({ host_cleanup_completed: true });
  }
  process.off('SIGTERM', abort);
  process.off('SIGINT', abort);
}
// This isolated host owns only one in-process, zero-tool foreground leaf.
// Plugin/SDK housekeeping timers do not keep a finished invocation alive.
process.exit(process.exitCode ?? 0);
