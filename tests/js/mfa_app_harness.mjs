// Runs tools/mfa_app.html's script against a fake host and prints what the panel did.
// Usage: node mfa_app_harness.mjs <html-path> <scenario>; no dependency beyond Node.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [htmlPath, scenario] = process.argv.slice(2);
const html = readFileSync(htmlPath, 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const LINK = 'https://auth.example/authorize?step_up_ticket=t';

const SCENARIOS = {
  no_open_links: { caps: { serverTools: {} }, click: false },
  open_link_declined: { caps: { openLinks: {}, serverTools: {} }, openLink: { isError: true } },
  poll_completes: { polls: [{ structuredContent: { status: 'success', data: { completed: true } } }] },
  poll_error_envelope: { polls: [{ structuredContent: { status: 'error', message: 'nope' } }] },
  poll_is_error_text: { polls: [{ isError: true, content: [{ type: 'text', text: 'boom' }] }] },
  poll_hangs: { polls: null },
  host_requests: { click: false, hostRequests: [{ id: 'p1', method: 'ping' }, { id: 'p2', method: 'foo/bar' }] },
  http_link: { link: 'http://auth.example/authorize', click: false },
};
const s = { caps: { openLinks: {}, serverTools: {} }, openLink: {}, link: LINK, click: true, ...SCENARIOS[scenario] };

function element() {
  const listeners = {};
  return {
    textContent: '', hidden: false, disabled: false, dataset: {},
    addEventListener: (type, fn) => { listeners[type] = fn; },
    fire: (type) => listeners[type] && listeners[type](),
  };
}
const elements = { status: element(), link: element(), authenticate: element() };
elements.link.hidden = true;

const sent = [];
let listener = null;
const deliver = (data) => listener && listener({ source: parent, data });
let pollIndex = 0;
const parent = {
  postMessage(msg) {
    sent.push(msg);
    if (msg.id === undefined || !msg.method) return;
    let result;
    if (msg.method === 'ui/initialize') result = { hostCapabilities: s.caps, hostContext: {} };
    else if (msg.method === 'ui/open-link') result = s.openLink;
    else if (msg.method === 'tools/call') {
      if (!s.polls) return; // the host never answers
      result = s.polls[Math.min(pollIndex++, s.polls.length - 1)];
    } else return;
    queueMicrotask(() => deliver({ jsonrpc: '2.0', id: msg.id, result }));
  },
};
const window = { parent, addEventListener: (type, fn) => { if (type === 'message') listener = fn; } };
const document = { getElementById: (id) => elements[id], documentElement: { dataset: {} } };
const fastTimeout = (fn) => setTimeout(fn, 0); // the panel's waits all elapse at once

vm.runInNewContext(script, { window, document, setTimeout: fastTimeout, Date, Promise, JSON, Map, Error, queueMicrotask });

const settle = () => new Promise((r) => setTimeout(r, 30));
await settle();
deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { structuredContent: { status: 'mfa_link_shown', workspace: 'acme', region: 'ap1' }, _meta: { 'alpacon/mfa': { mfa_url: s.link } } } });
for (const request of s.hostRequests || []) deliver({ jsonrpc: '2.0', ...request });
if (s.click) { elements.authenticate.fire('click'); }
await settle();

console.log(JSON.stringify({
  status: elements.status.textContent,
  tone: elements.status.dataset.tone || null,
  link: elements.link.hidden ? null : elements.link.textContent,
  buttonDisabled: elements.authenticate.disabled,
  toolCalls: sent.filter((m) => m.method === 'tools/call').length,
  responses: sent.filter((m) => !m.method),
}));
