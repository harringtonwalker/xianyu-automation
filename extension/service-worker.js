importScripts("core.js");
const Core = globalThis.XianyuCore;

const DEFAULTS = {
  serverUrl: "http://127.0.0.1:8766",
  extensionToken: "",
  pollingEnabled: true,
};

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) };
}

async function api(path, options = {}) {
  const config = await settings();
  if (!config.extensionToken) throw new Error("扩展尚未与本地控制台配对");
  const response = await fetch(`${config.serverUrl.replace(/\/$/, "")}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Xianyu-Extension-Token": config.extensionToken,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.error?.message || `本地服务请求失败：${response.status}`);
  return payload;
}

async function report(jobId, leaseToken, stage, payload = {}) {
  return api(`/api/extension/jobs/${jobId}/report`, {
    method: "POST",
    body: JSON.stringify({ lease_token: leaseToken, stage, payload }),
  });
}

async function publishTab() {
  // Never reuse a user's manual draft or a prior failed form.
  return chrome.tabs.create({ url: "https://www.goofish.com/publish", active: true });
}

async function waitForTab(tabId, timeoutMs = 30000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return tab;
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error("闲鱼发布页加载超时");
}

async function execute(job, formDefaults) {
  const tab = await publishTab();
  // Persist the execution/receipt association across browser restarts. The lease token
  // only authorizes this localhost job; it is removed immediately on terminal handling.
  await chrome.storage.local.set({
    activeExecution: {
      jobId: job.id,
      leaseToken: job.lease_token,
      tabId: tab.id,
      startedAt: Date.now(),
      expectedTitle: job.title,
      expectedPrice: String(job.price || "").replace(/\.00$/, ""),
    },
  });
  await waitForTab(tab.id);
  const response = await chrome.tabs.sendMessage(tab.id, { type: "RUN_JOB", job, formDefaults });
  if (!response?.ok) {
    const error = response?.error || { code: "FORM_EXECUTION_FAILED", message: "发布页未返回执行结果" };
    const stage = Core.executionFailureStage(error.code);
    await report(job.id, job.lease_token, stage, error);
    await chrome.storage.local.remove("activeExecution");
    return;
  }
}

async function recoverActiveExecution(active) {
  if (!active || Date.now() - active.startedAt < 5 * 60 * 1000) return false;
  const stage = active.submitted ? "blocked" : "failed";
  const payload = active.submitted
    ? { code: "RECEIPT_UNCERTAIN", message: "提交后五分钟内未取得可核验商品回执，禁止自动重试" }
    : { code: "FORM_SESSION_TIMEOUT", message: "发布页会话超时，未进入提交阶段" };
  try {
    await report(active.jobId, active.leaseToken, stage, payload);
  } finally {
    await chrome.storage.local.remove("activeExecution");
  }
  return true;
}

let polling = false;
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const config = await settings();
    if (!config.pollingEnabled || !config.extensionToken) return;
    const runtimeState = await chrome.storage.local.get({
      activeExecution: null,
      verifiedFormDefaults: null,
    });
    const active = runtimeState.activeExecution;
    if (active && !(await recoverActiveExecution(active))) return;
    if (!Core.formDefaultsFresh(runtimeState.verifiedFormDefaults)) {
      await chrome.storage.local.set({
        lastError: "请先在空白闲鱼发布页完成24小时内的人工预检",
        lastErrorAt: new Date().toISOString(),
      });
      return;
    }
    const payload = await api("/api/extension/next", { method: "POST", body: "{}" });
    if (payload.publisher_enabled && payload.job) {
      await execute(payload.job, runtimeState.verifiedFormDefaults);
    }
  } catch (error) {
    await chrome.storage.local.set({ lastError: error.message, lastErrorAt: new Date().toISOString() });
  } finally {
    polling = false;
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) });
  chrome.alarms.create("xianyu-queue-poll", { periodInMinutes: 0.5 });
});
chrome.runtime.onStartup.addListener(() => chrome.alarms.create("xianyu-queue-poll", { periodInMinutes: 0.5 }));
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "xianyu-queue-poll") poll();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "REPORT") {
    report(message.jobId, message.leaseToken, message.stage, message.payload)
      .then(async (payload) => {
        if (message.stage === "submitting") {
          const current = (await chrome.storage.local.get("activeExecution")).activeExecution;
          if (current?.jobId === message.jobId) {
            await chrome.storage.local.set({ activeExecution: { ...current, submitted: true } });
          }
        }
        sendResponse({ ok: true, payload });
      })
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "RECEIPT_CANDIDATE") {
    (async () => {
      const active = (await chrome.storage.local.get("activeExecution")).activeExecution;
      if (!active) return { ok: false, error: "没有等待回执的任务" };
      if (!sender.tab?.id || sender.tab.id !== active.tabId) {
        return { ok: false, error: "回执标签页与执行标签页不一致" };
      }
      if (!active.submitted) return { ok: false, error: "任务尚未进入提交阶段" };
      const receiptMatch = Core.receiptMatches(active, message);
      if (!receiptMatch.titleMatched) {
        return { ok: false, error: "回执页面未匹配已审批商品标题" };
      }
      if (!receiptMatch.priceMatched) {
        return { ok: false, error: "回执页面未匹配已审批商品价格" };
      }
      await report(active.jobId, active.leaseToken, "published", {
        item_id: message.itemId,
        receipt_url: message.receiptUrl,
        title_matched: true,
        price_matched: true,
      });
      await chrome.storage.local.remove("activeExecution");
      return { ok: true };
    })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "FETCH_ASSET") {
    (async () => {
      const config = await settings();
      const allowedPrefix = `${config.serverUrl.replace(/\/$/, "")}/api/assets/`;
      if (!String(message.url || "").startsWith(allowedPrefix)) throw new Error("拒绝读取非本地任务资产");
      const response = await fetch(message.url, {
        cache: "no-store",
        headers: { "X-Xianyu-Extension-Token": config.extensionToken },
      });
      if (!response.ok) throw new Error(`水印图片读取失败：${response.status}`);
      const contentType = response.headers.get("Content-Type") || "";
      if (!contentType.startsWith("image/")) throw new Error("本地资产不是图片");
      const bytes = Array.from(new Uint8Array(await response.arrayBuffer()));
      return { ok: true, bytes, contentType };
    })().then(sendResponse).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "IMPORT_RECORDS") {
    api("/api/extension/import", {
      method: "POST",
      body: JSON.stringify({ records: message.records }),
    }).then((payload) => sendResponse({ ok: true, payload }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "POLL_NOW") {
    poll().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
});
