import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(
  new URL("../static/js/api.js", import.meta.url),
  "utf8"
);
const api = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`
);
const uploadScreen = await readFile(
  new URL("../static/js/screens/upload.js", import.meta.url),
  "utf8"
);
const componentsScreen = await readFile(
  new URL("../static/js/screens/components.js", import.meta.url),
  "utf8"
);
const estimateScreen = await readFile(
  new URL("../static/js/screens/estimate.js", import.meta.url),
  "utf8"
);

class MockXHR {
  constructor() {
    this.listeners = {};
    this.upload = { addEventListener: (name, callback) => {
      this.uploadProgressHandler = callback;
    } };
    MockXHR.latest = this;
  }

  open(method, url) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name, value) {
    this.headers = { ...this.headers, [name]: value };
  }

  addEventListener(name, callback) {
    this.listeners[name] = callback;
  }

  getResponseHeader(name) {
    return name === "X-Request-ID" ? "req_0123456789ab" : null;
  }

  send(body) {
    this.body = body;
  }
}

test("photo upload reports progress and returns the photo resource", async () => {
  const previousXHR = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = MockXHR;
  try {
    const progress = [];
    const photo = { id: "pho_0123456789abcdef" };
    const request = api.uploadPhoto("prj_0123456789abcdef", new Blob(["photo"]), (value) => {
      progress.push(value);
    });
    const xhr = MockXHR.latest;
    assert.equal(xhr.method, "POST");
    assert.equal(xhr.url, "/api/projects/prj_0123456789abcdef/photos");
    assert.equal(xhr.timeout, 60000);
    assert.equal(xhr.headers["Content-Type"], undefined);
    xhr.uploadProgressHandler({ lengthComputable: true, loaded: 1, total: 4 });
    xhr.status = 201;
    xhr.responseText = JSON.stringify(photo);
    xhr.listeners.load();
    assert.deepEqual(await request, photo);
    assert.deepEqual(progress, [25]);
  } finally {
    globalThis.XMLHttpRequest = previousXHR;
  }
});

test("photo upload normalizes server errors", async () => {
  const previousXHR = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = MockXHR;
  try {
    const request = api.uploadPhoto("prj_0123456789abcdef", new Blob(["photo"]));
    const xhr = MockXHR.latest;
    xhr.status = 409;
    xhr.responseText = JSON.stringify({
      error: {
        code: "PHOTO_LIMIT_REACHED",
        message: "This project already has a photo.",
        details: {},
        request_id: "req_0123456789ab",
      },
    });
    xhr.listeners.load();
    await assert.rejects(request, (error) => {
      assert.equal(error.code, "PHOTO_LIMIT_REACHED");
      assert.equal(error.status, 409);
      assert.equal(error.requestId, "req_0123456789ab");
      return true;
    });
  } finally {
    globalThis.XMLHttpRequest = previousXHR;
  }
});

test("upload and detection instructions accept photographs and 3D renderings", () => {
  const instruction =
    "Upload a clear exterior photograph or 3D architectural rendering of your house.";
  assert.ok(uploadScreen.includes(instruction));
  assert.ok(componentsScreen.includes(instruction));
});

test("estimate screen warns that rendering-derived sizes need physical verification", () => {
  assert.ok(estimateScreen.includes("not verified physical measurements"));
  assert.ok(estimateScreen.includes("known scale or on site"));
  assert.ok(estimateScreen.includes("user-provided measurements take precedence"));
});
