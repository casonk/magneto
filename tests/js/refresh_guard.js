// Runs src/magneto/static/app.js against a minimal DOM and reports whether the
// auto-refresh fetched the list. Usage: node refresh_guard.js <app.js> <scenario>
const fs = require("fs");
const vm = require("vm");

const [appPath, scenario] = process.argv.slice(2);
let fetches = 0;
let pending = null;
const classes = new Set();

function control(attrs) {
  return Object.assign(
    { type: "text", tagName: "INPUT", name: "x", value: "", defaultValue: "", matches: () => true },
    attrs,
  );
}

const controls = [];
const focus = { current: null };
const list = {
  dataset: { refreshUrl: "/f", visibleInterval: "1", hiddenInterval: "1" },
  innerHTML: "",
  classList: {
    add: (c) => classes.add(c),
    remove: (c) => classes.delete(c),
    toggle: () => {},
  },
  contains: (el) => el === focus.current,
  querySelectorAll: () => controls,
};

if (scenario === "typed") controls.push(control({ value: "7", defaultValue: "" }));
if (scenario === "select") {
  controls.push(
    control({
      tagName: "SELECT",
      options: [
        { selected: false, defaultSelected: true },
        { selected: true, defaultSelected: false },
      ],
    }),
  );
}
if (scenario === "focused") focus.current = control({});
if (scenario === "untouched") controls.push(control({ value: "5", defaultValue: "5" }));

const sandbox = {
  document: {
    hidden: false,
    querySelector: (sel) => (sel === "[data-torrent-list]" ? list : null),
    addEventListener: () => {},
    get activeElement() {
      return focus.current;
    },
  },
  window: {
    clearTimeout: () => {},
    setTimeout: (fn) => {
      pending = fn;
      return 1;
    },
    addEventListener: () => {},
    location: { href: "/" },
  },
  fetch: async () => {
    fetches += 1;
    return { ok: true, text: async () => "<p>new</p>" };
  },
  Number,
  Array,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(appPath, "utf8"), sandbox);

(async () => {
  await pending();
  await new Promise((resolve) => setImmediate(resolve));
  console.log(JSON.stringify({ fetches, editing: classes.has("is-editing"), html: list.innerHTML }));
})();
