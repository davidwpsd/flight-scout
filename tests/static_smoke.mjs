/**
 * Smoke test for the static (GitHub Pages) build.
 *
 * Runs web/app.js in a stubbed DOM against site/data/snapshot.json, so we can
 * assert the page really renders without a backend — no browser required.
 *
 *   node tests/static_smoke.mjs
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const site = path.join(here, "..", "site");
const appJs = fs.readFileSync(path.join(site, "app.js"), "utf8");
const snapshot = JSON.parse(fs.readFileSync(path.join(site, "data", "snapshot.json"), "utf8"));

function makeEl(id) {
  const classes = new Set();
  let rawValue = "";
  const el = {
    id,
    children: [],
    innerHTML: "",
    textContent: "",
    placeholder: "",
    title: "",
    checked: false,
    disabled: false,
    clientWidth: 800,
    dataset: {},
    style: {},
    // Real inputs stringify whatever you assign; mirror that so Number("4") works.
    get value() {
      return rawValue;
    },
    set value(v) {
      rawValue = String(v ?? "");
    },
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      toggle: (c, force) => {
        const on = force === undefined ? !classes.has(c) : Boolean(force);
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
      contains: (c) => classes.has(c),
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    removeChild() {},
    addEventListener() {},
    removeEventListener() {},
    querySelectorAll() {
      return [];
    },
    querySelector() {
      return null;
    },
    click() {},
    focus() {},
  };
  return el;
}

const els = new Map();
const byId = (id) => {
  if (!els.has(id)) els.set(id, makeEl(id));
  return els.get(id);
};

const documentStub = {
  title: "",
  documentElement: { dataset: {} },
  body: makeEl("body"),
  getElementById: byId,
  createElement: (tag) => makeEl(`created-${tag}`),
  querySelector: (sel) => (sel === ".brand-text p" ? byId("brandSub") : null),
  querySelectorAll: () => [],
  addEventListener() {},
};

const responses = {
  "/api/meta": { ok: false, status: 404, json: async () => ({}) },
  "/api/config": { ok: false, status: 404, json: async () => ({}) },
};

const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  Blob: class {},
  URL: { createObjectURL: () => "blob:", revokeObjectURL() {} },
  document: documentStub,
  location: { hash: "" },
  navigator: { language: "zh-HK" },
  localStorage: { getItem: () => null, setItem() {} },
  window: { addEventListener() {} },
  fetch: async (url) => {
    const key = String(url);
    if (key.includes("snapshot.json")) {
      return { ok: true, status: 200, json: async () => snapshot };
    }
    return responses[key] || { ok: false, status: 404, json: async () => ({}) };
  },
};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
vm.runInContext(appJs, sandbox, { filename: "app.js" });

await new Promise((r) => setTimeout(r, 150));

const failures = [];
const check = (label, condition) => {
  if (!condition) failures.push(label);
  console.log(`${condition ? "PASS" : "FAIL"}  ${label}`);
};

const tableHtml = byId("resultsBody").innerHTML;
const filterSelect = byId("origin");

check("快照被载入（表格有行）", tableHtml.includes("<tr>"));
check("表格包含去重后的目的地", /class="city"/.test(tableHtml));
check("出发地下拉已填充", filterSelect.children.length === snapshot.origins.length);
check("结果摘要显示快照时间", byId("resultMeta").textContent.includes("快照更新于"));
check("顶栏显示快照标记", byId("providerPill").textContent.includes("快照"));
check("页脚说明是快照模式", byId("footerNote").innerHTML.includes("快照模式"));

const originCodes = filterSelect.children.map((o) => o.value);
check(`出发地为 ${originCodes.join("/")}`, originCodes.includes(snapshot.origin));

if (failures.length) {
  console.error(`\n${failures.length} 项失败`);
  process.exit(1);
}
console.log("\n静态站点渲染正常");
