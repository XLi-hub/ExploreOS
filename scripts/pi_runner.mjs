// A single Pi agent turn. No Pi CLI discovery, tools, extensions or auth files.
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const modules = resolve(root, '.runtime/pi/node_modules');
const expected = '1.4.0';
for (const name of ['pi-agent-core', 'pi-ai']) {
  const pkg = JSON.parse(await readFile(resolve(modules, '@earendil-works', name, 'package.json'), 'utf8'));
  if (pkg.version !== expected) throw new Error('Pi package differs from the pinned runtime');
}
const { Agent } = await import(pathToFileURL(resolve(modules, '@earendil-works/pi-agent-core/dist/index.js')));
const { stream: streamAnthropic } = await import(pathToFileURL(resolve(modules, '@earendil-works/pi-ai/dist/api/anthropic-messages.js')));
if (process.argv.includes('--check')) {
  process.stdout.write(JSON.stringify({ agent_core: expected, pi_ai: expected, tools: [], model_requests: 0 }) + '\n');
  process.exit(0);
}

let input = '';
for await (const chunk of process.stdin) {
  input += chunk;
  if (Buffer.byteLength(input) > 100_000) throw new Error('Bounded invocation input exceeded');
}
const request = JSON.parse(input);
const endpoint = new URL(request.base_url);
if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1') {
  throw new Error('Pi may only contact the controller-owned loopback relay');
}
const model = {
  id: 'deepseek-flash', name: 'ExploreOS authorized model', api: 'anthropic-messages',
  provider: 'exploreos-local-relay', baseUrl: endpoint.href,
  reasoning: false, input: ['text'], contextWindow: 32_000, maxTokens: 900,
  // Supplier usage/cost authority is the shared relay ledger, not this display estimate.
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
};
let requests = 0;
const events = [];
const agent = new Agent({
  initialState: { systemPrompt: request.system_prompt, model, thinkingLevel: 'off', tools: [], messages: [] },
  sessionId: request.call_id,
  getApiKey: () => request.gateway_token,
  beforeToolCall: async () => ({ block: true, reason: 'No tools authorized in this runtime profile' }),
  finishTurn: async () => ({ action: 'end' }),
  streamFn: (selected, context, options) => {
    if (++requests > 1) throw new Error('One provider request per invocation; no autonomous retries or follow-up turns');
    return streamAnthropic(selected, context, {
      ...options, apiKey: request.gateway_token, maxTokens: 900, thinkingEnabled: false,
      cacheRetention: 'none', maxRetries: 0, timeoutMs: 60_000,
    });
  },
});
agent.subscribe(event => {
  if (['agent_start', 'turn_start', 'message_end', 'turn_end', 'agent_end', 'tool_execution_start'].includes(event.type)) {
    events.push({ type: event.type, role: event.message?.role });
  }
});
const abort = () => agent.abort();
process.on('SIGTERM', abort);
process.on('SIGINT', abort);
try {
  await agent.prompt(JSON.stringify(request.messages));
  const answer = agent.state.messages.findLast(message => message.role === 'assistant');
  if (!answer || ['error', 'aborted', 'length', 'toolUse'].includes(answer.stopReason)) {
    throw new Error('Pi invocation incomplete; reconcile the relay ledger before retrying');
  }
  if (answer.content.some(block => block.type === 'toolCall')) throw new Error('Unexpected tool request');
  process.stdout.write(JSON.stringify({ result: answer.content.filter(block => block.type === 'text').map(block => block.text).join(''),
    session_id: request.call_id, pi_version: expected, provider_requests: requests, events,
    response_id: answer.responseId, usage: answer.usage }) + '\n');
} catch (error) {
  process.stderr.write(JSON.stringify({ type: error.name, message: error.message }) + '\n');
  process.exitCode = 1;
} finally {
  process.off('SIGTERM', abort);
  process.off('SIGINT', abort);
}
