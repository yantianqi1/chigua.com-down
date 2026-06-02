import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

NODE_RENDER_TEST = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const registry = new Map();
const VOID_TAGS = new Set(["br", "hr", "img", "input", "meta", "link"]);

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function parseAttrs(rawAttrs) {
  const attrs = {};
  const attrPattern = /([A-Za-z_:][-A-Za-z0-9_:.]*)=(["'])(.*?)\2/g;
  let match;
  while ((match = attrPattern.exec(rawAttrs)) !== null) {
    attrs[match[1]] = match[3];
  }
  return attrs;
}

function unregisterTree(node) {
  if (node.id) registry.delete(node.id);
  node.children.forEach(unregisterTree);
}

function matchesSelector(node, selector) {
  if (selector.startsWith("#")) return node.id === selector.slice(1);
  if (selector.startsWith(".")) return node.hasClass(selector.slice(1));
  const role = selector.match(/^\[data-role=["']([^"']+)["']\]$/);
  if (role) return node.dataset.role === role[1];
  return node.tagName.toLowerCase() === selector.toLowerCase();
}

function findDescendant(node, selector) {
  for (const child of node.children) {
    if (matchesSelector(child, selector)) return child;
    const nested = findDescendant(child, selector);
    if (nested) return nested;
  }
  return null;
}

class Element {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.parentElement = null;
    this.style = {};
    this._id = "";
    this._innerHTML = "";
    this._textContent = "";
    this.className = "";
  }

  get id() { return this._id; }
  set id(value) {
    if (this._id) registry.delete(this._id);
    this._id = value;
    if (value) registry.set(value, this);
  }

  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) {
    this.children.slice().forEach(child => child.remove());
    this._innerHTML = String(value);
    parseHtmlInto(this, this._innerHTML);
  }

  get textContent() {
    return this._textContent + this.children.map(child => child.textContent).join("");
  }
  set textContent(value) {
    this.children.slice().forEach(child => child.remove());
    this._textContent = String(value);
    this._innerHTML = escapeHtml(value);
  }

  get classList() {
    return {
      contains: cls => this.hasClass(cls),
      add: cls => {
        if (!this.hasClass(cls)) this.className = `${this.className} ${cls}`.trim();
      },
      remove: cls => {
        this.className = this.className.split(/\s+/).filter(item => item !== cls).join(" ");
      },
    };
  }

  hasClass(cls) {
    return this.className.split(/\s+/).filter(Boolean).includes(cls);
  }

  appendChild(child) {
    if (child.parentElement) child.parentElement.removeChild(child);
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  insertBefore(child, reference) {
    if (!reference) return this.appendChild(child);
    if (child.parentElement) child.parentElement.removeChild(child);
    const index = this.children.indexOf(reference);
    assert.notEqual(index, -1, "reference node must be a child");
    child.parentElement = this;
    this.children.splice(index, 0, child);
    return child;
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index === -1) return;
    this.children.splice(index, 1);
    child.parentElement = null;
  }

  remove() {
    if (this.parentElement) this.parentElement.removeChild(this);
    unregisterTree(this);
  }

  insertAdjacentHTML(position, html) {
    const fragment = new Element("fragment");
    parseHtmlInto(fragment, html);
    if (position === "beforeend") {
      fragment.children.slice().forEach(child => this.appendChild(child));
      return;
    }
    assert.equal(position, "afterend", "unsupported insert position");
    const siblings = this.parentElement.children;
    let index = siblings.indexOf(this) + 1;
    fragment.children.slice().forEach(child => {
      this.parentElement.insertBefore(child, siblings[index] || null);
      index += 1;
    });
  }

  querySelector(selector) {
    const parts = selector.trim().split(/\s+/);
    let scope = this;
    for (const part of parts) {
      scope = findDescendant(scope, part);
      if (!scope) return null;
    }
    return scope;
  }
}

function applyAttrs(element, attrs) {
  if (attrs.id) element.id = attrs.id;
  if (attrs.class) element.className = attrs.class;
  if (attrs["data-task-id"]) element.dataset.taskId = attrs["data-task-id"];
  if (attrs["data-role"]) element.dataset.role = attrs["data-role"];
  if (attrs.style) {
    const width = attrs.style.match(/width\s*:\s*([^;]+)/);
    if (width) element.style.width = width[1].trim();
  }
}

function parseHtmlInto(parent, html) {
  const tagPattern = /<\/?([A-Za-z][A-Za-z0-9-]*)([^>]*)>/g;
  const stack = [parent];
  let match;
  while ((match = tagPattern.exec(html)) !== null) {
    const fullTag = match[0];
    const tagName = match[1];
    if (fullTag.startsWith("</")) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    const element = new Element(tagName);
    applyAttrs(element, parseAttrs(match[2]));
    stack[stack.length - 1].appendChild(element);
    const selfClosing = fullTag.endsWith("/>") || VOID_TAGS.has(tagName.toLowerCase());
    if (!selfClosing) stack.push(element);
  }
}

global.document = {
  createElement: tagName => new Element(tagName),
  getElementById: id => registry.get(id) || null,
};

global.clearInterval = () => {};
global.setInterval = () => 1;

const taskList = new Element("section");
taskList.id = "taskList";
const taskCount = new Element("span");
taskCount.id = "taskCount";

const renderCode = fs.readFileSync("static/render.js", "utf8");
const appCode = fs.readFileSync("static/app.js", "utf8").split("// Init")[0];
vm.runInThisContext(`${renderCode}
${appCode}
pollingTimer = 1;
const task = {
  id: "abc123",
  url: "https://chigua.com/archives/test/",
  status: "downloading",
  title: "Video A",
  filename: "Video A.mp4",
  progress: 12.5,
  speed: "1.0x",
  size: "",
  duration: "00:01:00",
  current_time: "00:00:07",
  error: "",
};

taskList.innerHTML = '<div class="empty-state">No tasks</div>';
renderTasks([task]);
assert.equal(taskList.children.length, 1, "empty placeholder should be removed");

const firstCard = document.getElementById("task-abc123");
const firstFill = firstCard.querySelector(".fill");

renderTasks([{ ...task, progress: 25.5, current_time: "00:00:15" }]);
const secondCard = document.getElementById("task-abc123");
const secondFill = secondCard.querySelector(".fill");

assert.strictEqual(secondCard, firstCard, "task card should be reused");
assert.strictEqual(secondFill, firstFill, "progress fill should be reused");
assert.equal(secondFill.style.width, "25.5%");
`);
"""


class FrontendRenderTest(unittest.TestCase):
    def test_reuses_progress_dom_between_refreshes(self):
        node_bin = shutil.which("node")
        self.assertIsNotNone(node_bin, "node is required for frontend tests")

        result = subprocess.run(
            [node_bin, "-e", textwrap.dedent(NODE_RENDER_TEST)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
