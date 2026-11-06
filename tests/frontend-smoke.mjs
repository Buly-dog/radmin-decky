// Exercises the compiled Decky entry point with simulated RPC and hook state.
// This checks wiring/state transitions, not real React or Steam's native UI.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../dist/index.js", import.meta.url), "utf8");
assert(source.includes("export { index as default };"));
const cells = [];
const effects = [];
const intervals = new Map();
let cursor = 0;
let current = {installed: false, configured: false, state: "missing", ready: false, ip: "", message: "Install", enabled: false, installing: false, install_failed: false, gui_mode: false};
const calls = [];
const handlers = {
  get_status: async () => structuredClone(current),
  install_system: async () => (current = {...current, installing: true}),
  set_enabled: async enabled => (current = {...current, enabled, ready: enabled, ip: enabled ? "26.1.2.3" : ""}),
  restart: async () => current,
  get_logs: async () => "first log",
  set_gui_mode: async enabled => (current = {...current, gui_mode: enabled}),
};
const hooks = {
  createContext: value => ({value}),
  useState(initial) {
    const index = cursor++;
    if (!(index in cells)) cells[index] = initial;
    return [cells[index], value => { cells[index] = typeof value === "function" ? value(cells[index]) : value; }];
  },
  useRef(initial) {
    const index = cursor++;
    return cells[index] ??= {current: initial};
  },
  useCallback(fn) {
    const index = cursor++;
    return cells[index] ??= fn;
  },
  useEffect(effect) {
    const index = cursor++;
    if (!(index in cells)) { cells[index] = true; effects.push(effect); }
  },
};
const jsx = (type, props) => ({type, props});
const context = vm.createContext({
  console, SP_REACT: hooks, SP_JSX: {jsx, jsxs: jsx, Fragment: "Fragment"},
  DFL: {ButtonItem: "ButtonItem", ToggleField: "ToggleField", PanelSection: "PanelSection", PanelSectionRow: "PanelSectionRow", staticClasses: {Title: "title"}},
  setInterval(fn) { intervals.set(1, fn); return 1; },
  clearInterval(id) { intervals.delete(id); },
  window: {__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: {
    connect: () => ({_version: 2, callable: name => async (...args) => {
      calls.push({name, args});
      assert(name in handlers, `Unknown backend RPC: ${name}`);
      return handlers[name](...args);
    }, toaster: {toast() {}}}),
  }},
});
new vm.Script(source.replace("export { index as default };", "globalThis.factory = index;")).runInContext(context);
const plugin = context.factory();
assert.equal(plugin.name, "Radmin VPN");
let tree;
const cleanup = [];
function render() {
  cursor = 0;
  tree = plugin.content.type();
  while (effects.length) cleanup.push(effects.shift()());
}
function walk(node, predicate) {
  if (Array.isArray(node)) return node.flatMap(child => walk(child, predicate));
  if (!node || typeof node !== "object") return [];
  return [...(predicate(node) ? [node] : []), ...walk(node.props?.children, predicate)];
}
const button = label => walk(tree, node => node.type === "ButtonItem" && node.props.children === label)[0];
const toggle = () => walk(tree, node => node.type === "ToggleField")[0];
const modeToggle = () => walk(tree, node => node.type === "ToggleField" && node.props.label === "Запуск с окном Radmin")[0];
const text = node => Array.isArray(node) ? node.map(text).join(" ") : typeof node === "object" && node ? text(node.props?.children) : typeof node === "string" ? node : "";
const settle = async () => { await new Promise(setImmediate); render(); };
const poll = async () => { for (const callback of intervals.values()) callback(); await settle(); };

render(); await settle();
assert.equal(toggle().props.disabled, true);
button("Установить компоненты VPN").props.onClick(); await settle();
assert.equal(button("Устанавливается…").props.disabled, true);
assert.equal(calls.filter(c => c.name === "install_system").length, 1);
assert.equal(calls.filter(c => c.name === "set_enabled").length, 0);

current = {...current, installed: true, configured: true, installing: false, state: "inactive"};
await poll();
assert.equal(toggle().props.disabled, false);
modeToggle().props.onChange(true); await settle();
assert.equal(modeToggle().props.checked, true);
assert.equal(calls.findLast(c => c.name === "set_gui_mode").args[0], true);
toggle().props.onChange(true); await settle();
assert.equal(toggle().props.checked, true);
assert.equal(modeToggle().props.disabled, true);
assert(text(tree).includes("26.1.2.3"));
assert.equal(calls.findLast(c => c.name === "set_enabled").args[0], true);

// A slow poll begun before a toggle must not undo the toggle's newer result.
let release;
handlers.get_status = () => new Promise(resolve => { release = resolve; });
for (const callback of intervals.values()) callback();
toggle().props.onChange(false); await settle();
release({...current, enabled: true}); await settle();
assert.equal(toggle().props.checked, false);
handlers.get_status = async () => structuredClone(current);

button("Показать журнал").props.onClick(); await settle();
assert(text(tree).includes("first log"));
handlers.get_logs = async () => "second log";
button("Обновить журнал").props.onClick(); await settle();
assert(text(tree).includes("second log"));

toggle().props.onChange(true); await settle();
handlers.restart = async () => { throw new Error("simulated restart failure"); };
button("Перезапустить VPN").props.onClick(); await settle();
assert(text(tree).includes("simulated restart failure"));
await poll();
assert(text(tree).includes("simulated restart failure"));

for (const fn of cleanup) if (fn) fn();
assert.equal(intervals.size, 0);
console.log("Compiled frontend smoke test OK: install, enable/disable, stale polling, log refresh, persistent errors, timer cleanup");
