const test = require("node:test");
const assert = require("node:assert/strict");
const Runtime = require("../extension/content-runtime.js");

function preview(src) {
  return {
    currentSrc: src,
    getAttribute(name) {
      return name === "src" ? src : "";
    },
  };
}

function uploadFixture() {
  const input = { files: [{}, {}, {}], parentElement: null };
  const region = {
    innerText: "宝贝图片",
    textContent: "宝贝图片",
    parentElement: null,
    querySelectorAll(selector) {
      if (selector === 'img[src], [style*="background-image"]') {
        return [
          preview("https://static.example/upload-icon.png"),
          preview("blob:one"),
          preview("blob:two"),
          preview("blob:three"),
        ];
      }
      return [];
    },
  };
  input.parentElement = region;
  const doc = {
    querySelectorAll(selector) {
      return selector === 'input[type="file"]' ? [input] : [];
    },
  };
  return { doc, input, region };
}

test("upload completion requires exact files, new previews, no progress, and stability", async () => {
  global.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1" });
  const { doc, input, region } = uploadFixture();
  const baselineKeys = new Set(["https://static.example/upload-icon.png"]);
  const snapshot = Runtime.uploadSnapshot(doc, input, 3, baselineKeys);
  assert.equal(snapshot.ready, true);
  assert.equal(snapshot.fileCount, 3);
  assert.equal(snapshot.previewCount, 3);

  let polls = 0;
  const evidence = await Runtime.waitForUploadCompletion({
    doc,
    input,
    expectedCount: 3,
    baselineKeys,
    stablePasses: 3,
    timeoutMs: 1000,
    pollMs: 1,
    sleep: async () => { polls += 1; },
  });
  assert.equal(evidence.ready, true);
  assert.equal(evidence.previewCount, 3);
  assert.equal(polls, 2);
  assert.equal(Runtime.uploadRegion(input), region);
});

test("upload errors fail closed immediately", async () => {
  const { doc, input, region } = uploadFixture();
  region.innerText = "宝贝图片 图片上传失败 请重新上传";
  await assert.rejects(
    Runtime.waitForUploadCompletion({
      doc,
      input,
      expectedCount: 3,
      baselineKeys: new Set(),
      timeoutMs: 100,
      pollMs: 1,
      sleep: async () => {},
    }),
    (error) => error.code === "IMAGE_UPLOAD_FAILED"
  );
});

test("missing preview evidence never counts the native file assignment as uploaded", async () => {
  const { doc, input, region } = uploadFixture();
  region.querySelectorAll = () => [];
  await assert.rejects(
    Runtime.waitForUploadCompletion({
      doc,
      input,
      expectedCount: 3,
      baselineKeys: new Set(),
      timeoutMs: -1,
      pollMs: 1,
      sleep: async () => {},
    }),
    (error) => error.code === "IMAGE_UPLOAD_UNVERIFIED"
  );
});

test("blank upload evidence requires the single verified add-cover icon", () => {
  const input = { files: [], parentElement: null };
  const icon = preview(
    "https://img.alicdn.com/imgextra/i1/O1CN016XczIR1iimNeEcZoh_!!6000000004447-2-tps-36-36.png.webp"
  );
  const region = {
    innerText: "宝贝图片 * 添加首图",
    parentElement: null,
    querySelectorAll(selector) {
      if (selector === 'img[src], [style*="background-image"]') return [icon];
      return [];
    },
  };
  input.parentElement = region;
  const doc = {
    querySelectorAll(selector) {
      return selector === 'input[type="file"]' ? [input] : [];
    },
  };
  const blank = Runtime.blankUploadEvidence(doc, input);
  assert.equal(blank.ok, true);
  assert.equal(
    blank.previewKeys[0].includes(Runtime.VERIFIED_BLANK_UPLOAD_ICON_FRAGMENT),
    true
  );
  icon.currentSrc = "https://img.alicdn.com/unverified-icon.webp";
  assert.equal(Runtime.blankUploadEvidence(doc, input).ok, false);
  icon.currentSrc = (
    "https://img.alicdn.com/imgextra/i1/O1CN016XczIR1iimNeEcZoh_!!6000000004447-2-tps-36-36.png.webp"
  );
  input.files = [{}];
  assert.equal(Runtime.blankUploadEvidence(doc, input).ok, false);
  input.files = [];
  region.innerText = "宝贝图片 已上传";
  assert.equal(Runtime.blankUploadEvidence(doc, input).ok, false);
});
