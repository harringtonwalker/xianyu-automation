const test = require("node:test");
const assert = require("node:assert/strict");
const Core = require("../extension/core.js");

function element({ text = "", value = "", accept = "", visible = true } = {}) {
  return {
    innerText: text,
    value,
    accept,
    getAttribute: () => null,
    getClientRects: () => (visible ? [{}] : []),
  };
}

function anchoredLabel(text, input) {
  const container = {
    parentElement: null,
    querySelectorAll(selector) {
      return selector === 'input[placeholder="0.00"]' ? [input] : [];
    },
  };
  return {
    ...element({ text }),
    parentElement: container,
    querySelectorAll: () => [],
  };
}

test("risk signals stop execution", () => {
  assert.equal(Core.riskSignal("请完成安全验证后继续"), "安全验证");
  assert.equal(Core.riskSignal("正常发布页面"), "");
});

test("systemic execution failures trip the global circuit breaker", () => {
  for (const code of [
    "RISK_SIGNAL",
    "DOM_CONTRACT_CHANGED",
    "WRONG_PAGE",
    "IMAGE_UPLOAD_FAILED",
    "IMAGE_UPLOAD_UNVERIFIED",
    "RECEIPT_UNCERTAIN",
  ]) {
    assert.equal(Core.executionFailureStage(code), "blocked");
  }
  assert.equal(Core.executionFailureStage("FORM_NOT_BLANK"), "failed");
});

test("valid jobs require explicit submit mode and default location", () => {
  const validJob = {
    id: "job-1",
    lease_token: "lease",
    description: "这是一段超过二十个字符且完全基于事实生成的商品描述文本。",
    image_urls: ["http://127.0.0.1:8766/a.png"],
    price: "1999.00",
    delivery: "无需邮寄",
    execution_mode: "submit",
    location_mode: "KEEP_ACCOUNT_DEFAULT",
  };
  const valid = Core.validateJob(validJob);
  assert.equal(valid.ok, true);
  assert.equal(Core.validateJob({}).ok, false);
  assert.equal(Core.validateJob({ ...validJob, delivery: "一口价", shipping_fee: "" }).ok, false);
  assert.equal(Core.validateJob({ ...validJob, delivery: "一口价", shipping_fee: "12.50" }).ok, true);
  assert.equal(Core.validateJob({ ...validJob, shipping_fee: "12.50" }).ok, false);
});

test("blank-form detection ignores Xianyu's default delivery radio", () => {
  const contract = {
    files: [{ files: [] }],
    editors: [{ innerText: "" }],
    allPriceInputs: [{ value: "" }, { value: "" }],
    selfPickupField: { checked: false },
  };
  assert.equal(Core.formHasUserDraft(contract), false);
  // The radio state is intentionally outside the contract: Xianyu currently
  // preselects 包邮 on an otherwise blank form.
  assert.equal(Core.formHasUserDraft({ ...contract, defaultCheckedDelivery: "包邮" }), false);
  assert.equal(
    Core.formHasUserDraft({ ...contract, editors: [{ innerText: "旧草稿" }] }),
    true
  );
  assert.equal(
    Core.formHasUserDraft({ ...contract, allPriceInputs: [{ value: "99" }, { value: "" }] }),
    true
  );
  assert.equal(
    Core.formHasUserDraft({ ...contract, selfPickupField: { checked: true } }),
    true
  );
});

test("fresh form defaults bind location, self-pickup, upload baseline, and signature", () => {
  const defaults = {
    contractSignature: Core.VERIFIED_SIGNATURES.BASE,
    locationText: "账号默认所在地",
    selfPickupEnabled: false,
    blankUploadPreviewKeys: ["https://img.alicdn.com/upload-icon.webp"],
    blankUploadRegionText: "宝贝图片 * 添加首图",
    verifiedAt: new Date().toISOString(),
  };
  assert.equal(Core.formDefaultsFresh(defaults), true);
  assert.equal(Core.formDefaultsMatch(defaults, { ...defaults }), true);
  assert.equal(Core.formDefaultsMatch(defaults, { ...defaults, locationText: "其他地点" }), false);
  assert.equal(Core.formDefaultsMatch(defaults, { ...defaults, selfPickupEnabled: true }), false);
  assert.equal(Core.formDefaultsMatch(defaults, { ...defaults, blankUploadPreviewKeys: ["other"] }), false);
  assert.equal(
    Core.formDefaultsFresh({
      ...defaults,
      verifiedAt: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(),
    }),
    false
  );
});

test("receipt only accepts real goofish item URLs", () => {
  assert.equal(Core.itemIdFromUrl("https://www.goofish.com/item?id=12345"), "12345");
  assert.equal(Core.itemIdFromUrl("https://example.com/item?id=12345"), "");
});

test("Xianyu extraction only accepts the explicitly bound owner profile", () => {
  assert.equal(
    Core.authorizedOwnerPage("https://www.goofish.com/personal?userId=1000000001", "1000000001"),
    "xianyu-own"
  );
  assert.equal(
    Core.authorizedOwnerPage("https://www.goofish.com/personal?userId=1000000002", "1000000001"),
    ""
  );
  assert.equal(
    Core.authorizedOwnerPage("https://www.goofish.com/item?id=1000000000001", "1000000001"),
    ""
  );
  assert.equal(
    Core.authorizedOwnerPage("https://myseller.taobao.com/home.htm/SellManage/on_sale", ""),
    "taobao-own"
  );
});

test("owned inventory cards require exact platform item hosts and paths", () => {
  assert.equal(
    Core.authorizedItemUrl("https://www.goofish.com/item?id=1000000000001", "xianyu-own"),
    true
  );
  assert.equal(
    Core.authorizedItemUrl("https://item.taobao.com/item.htm?id=123456789", "taobao-own"),
    true
  );
  assert.equal(
    Core.authorizedItemUrl(
      "https://evil.example/path/goofish.com/item?id=1000000000001",
      "xianyu-own"
    ),
    false
  );
  assert.equal(
    Core.authorizedItemUrl("https://www.goofish.com/item?id=1000000000001", "taobao-own"),
    false
  );
  assert.equal(
    Core.authorizedItemUrl("https://item.taobao.com/other?id=123456789", "taobao-own"),
    false
  );
});

test("receipt evidence must match the approved title and price", () => {
  const expected = { expectedTitle: "门店小程序定制服务", expectedPrice: "1999" };
  const correct = Core.receiptMatches(expected, {
    pageTitle: "门店小程序定制服务_闲鱼",
    pagePrices: ["1999"],
  });
  assert.deepEqual(correct, { titleMatched: true, priceMatched: true });
  const wrong = Core.receiptMatches(expected, {
    pageTitle: "另一个商品_闲鱼",
    pagePrices: ["2999"],
  });
  assert.deepEqual(wrong, { titleMatched: false, priceMatched: false });
  const substringTrap = Core.receiptMatches(
    { expectedTitle: "门店小程序", expectedPrice: "19" },
    { pageTitle: "另一个门店小程序套餐_闲鱼", pagePrices: ["199"] }
  );
  assert.deepEqual(substringTrap, { titleMatched: false, priceMatched: false });
  const decimalEquivalent = Core.receiptMatches(
    { expectedTitle: "门店小程序", expectedPrice: "18.50" },
    { pageTitle: "门店小程序_闲鱼", pagePrices: ["18.5"] }
  );
  assert.deepEqual(decimalEquivalent, { titleMatched: true, priceMatched: true });
});

test("preflight checks the current publish contract", () => {
  global.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1" });
  // The real Xianyu upload input is visually hidden behind an upload card.
  const file = element({
    accept: "image/png, image/jpg, image/jpeg, image/heic, image/webp",
    visible: false,
  });
  const editor = element();
  const price1 = element();
  const price2 = element();
  const button = element({ text: "发布" });
  const pickupSwitch = {
    ...element(),
    getAttribute(name) { return name === "aria-checked" ? "false" : null; },
  };
  const pickupContainer = {
    parentElement: null,
    querySelectorAll(selector) {
      return selector === '[role="switch"]' ? [pickupSwitch] : [];
    },
  };
  const pickupText = { ...element({ text: "支持自提" }), parentElement: pickupContainer };
  const locationRow = {
    ...element({ text: "宝贝所在地 账号默认所在地" }),
    parentElement: null,
    querySelectorAll: () => [],
  };
  const locationLabel = {
    ...element({ text: "宝贝所在地" }),
    parentElement: locationRow,
    querySelectorAll: () => [],
  };
  const labels = [
    anchoredLabel("价格 *", price1),
    anchoredLabel("原价", price2),
    ...Core.DELIVERY.map((text) => element({ text })),
    locationLabel,
  ];
  const doc = {
    body: { innerText: "宝贝图片 宝贝描述 价格 原价 发布" },
    querySelectorAll(selector) {
      if (selector === 'input[type="file"]') return [file];
      if (selector === '[contenteditable="true"]') return [editor];
      if (selector === 'input[placeholder="0.00"]') return [price1, price2];
      if (selector === "label") return labels;
      if (selector === "div,span,label") return [pickupText];
      if (selector === "button") return [button];
      return [];
    },
  };
  const result = Core.preflight(doc, "https://www.goofish.com/publish");
  assert.equal(result.ok, true);
  assert.equal(result.contract.signature, Core.VERIFIED_SIGNATURES.BASE);
  const reorderedDoc = {
    ...doc,
    querySelectorAll(selector) {
      if (selector === 'input[placeholder="0.00"]') return [price2, price1];
      return doc.querySelectorAll(selector);
    },
  };
  const reordered = Core.preflight(reorderedDoc, "https://www.goofish.com/publish");
  assert.equal(reordered.ok, true);
  assert.equal(reordered.contract.priceInputs[0], price1);
  assert.equal(reordered.contract.priceInputs[1], price2);
});

test("preflight blocks contract drift and risk prompts", () => {
  global.getComputedStyle = () => ({ display: "block", visibility: "visible", opacity: "1" });
  const doc = {
    body: { innerText: "请完成验证码" },
    querySelectorAll: () => [],
  };
  assert.equal(Core.preflight(doc, "https://www.goofish.com/publish").code, "RISK_SIGNAL");
  doc.body.innerText = "普通页面";
  assert.equal(Core.preflight(doc, "https://www.goofish.com/publish").code, "DOM_CONTRACT_CHANGED");
});

test("manifest has no cookie debugger or stealth privileges", () => {
  const manifest = require("../extension/manifest.json");
  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.permissions.includes("cookies"), false);
  assert.equal(manifest.permissions.includes("debugger"), false);
  assert.equal(manifest.permissions.includes("tabs"), false);
  assert.equal(manifest.host_permissions.some((item) => item.includes("goofish.com")), false);
  assert.equal(manifest.content_scripts[0].matches.includes("https://www.goofish.com/*"), false);
  assert.equal(JSON.stringify(manifest).includes("stealth"), false);
});

test("service worker persists receipt association and never reuses a publish draft", () => {
  const fs = require("node:fs");
  const worker = fs.readFileSync(require.resolve("../extension/service-worker.js"), "utf8");
  assert.equal(worker.includes("chrome.storage.session"), false);
  assert.equal(worker.includes("chrome.storage.local.set({\n    activeExecution"), true);
  assert.equal(worker.includes('chrome.tabs.query({ url: "https://www.goofish.com/publish*" })'), false);
  assert.equal(worker.includes('chrome.tabs.create({ url: "https://www.goofish.com/publish"'), true);
  assert.equal(worker.includes("verifiedFormDefaults"), true);
  assert.equal(worker.indexOf("Core.formDefaultsFresh") < worker.indexOf('api("/api/extension/next"'), true);
});

test("content script rechecks preflight freshness immediately before submit state", () => {
  const fs = require("node:fs");
  const content = fs.readFileSync(require.resolve("../extension/content.js"), "utf8");
  const submitting = content.indexOf('await sendReport(job, "submitting"');
  const freshness = content.lastIndexOf(
    "if (!Core.formDefaultsFresh(verifiedFormDefaults))",
    submitting
  );
  const risk = content.lastIndexOf("const risk = Core.riskSignal", submitting);
  assert.notEqual(submitting, -1);
  assert.equal(freshness > risk && freshness < submitting, true);
});

test("options reject non-ASCII pairing tokens before persistence or fetch", () => {
  const fs = require("node:fs");
  const options = fs.readFileSync(require.resolve("../extension/options.js"), "utf8");
  const validation = options.indexOf("!/^[A-Za-z0-9_-]{40,200}$/.test(extensionToken)");
  const persistence = options.indexOf("await chrome.storage.local.set");
  const ping = options.indexOf("/api/extension/ping");
  assert.notEqual(validation, -1);
  assert.equal(validation < persistence && persistence < ping, true);
});

test("dashboard copies the real pairing token without exposing the password field", () => {
  const fs = require("node:fs");
  const dashboard = fs.readFileSync(require.resolve("../static/app.js"), "utf8");
  const html = fs.readFileSync(require.resolve("../static/index.html"), "utf8");
  assert.equal(html.includes('id="copyPairingTokenButton"'), true);
  assert.equal(dashboard.includes("navigator.clipboard.writeText(token)"), true);
  assert.equal(
    dashboard.includes('$("#copyPairingTokenButton").addEventListener("click", copyPairingToken)'),
    true
  );
});
