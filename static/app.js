const state = { health: null, jobs: [], settings: null, reviewingJobId: "" };

const $ = (selector) => document.querySelector(selector);
const escapeText = (value) => String(value ?? "");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.error?.message || `请求失败：${response.status}`);
  }
  return payload;
}

function setResult(text, error = false) {
  const output = $("#importResult");
  output.textContent = text;
  output.style.color = error ? "#a63b32" : "#237a52";
}

const statusLabels = {
  INGESTED: "待生成",
  PENDING_APPROVAL: "待审批",
  APPROVED: "已审批",
  RUNNING: "执行中",
  AWAITING_RECEIPT: "等待回执",
  PUBLISHED: "已发布",
  BLOCKED: "已阻塞",
  FAILED: "失败",
  SUPERSEDED: "来源已更新",
};

function render() {
  const counts = {};
  state.jobs.forEach((job) => { counts[job.status] = (counts[job.status] || 0) + 1; });
  $("#metricAll").textContent = state.jobs.length;
  $("#metricIngested").textContent = counts.INGESTED || 0;
  $("#metricPending").textContent = counts.PENDING_APPROVAL || 0;
  $("#metricPublished").textContent = counts.PUBLISHED || 0;
  $("#metricBlocked").textContent = (counts.BLOCKED || 0) + (counts.FAILED || 0);

  if (state.settings) {
    $("#brandName").value = state.settings.brand_name || "";
    $("#watermarkText").value = state.settings.watermark_text || "";
  }

  const enabled = Boolean(state.health?.publisher_enabled);
  $("#publisherState").textContent = enabled ? "已启用 · 只执行已审批任务" : "已关闭 · 不会触碰发布页";
  $("#publisherState").style.color = enabled ? "#a63b32" : "#237a52";
  $("#publisherButton").textContent = enabled ? "关闭自动发布" : "启用自动发布";
  $("#publisherButton").disabled = !state.health;

  const rows = $("#jobRows");
  rows.replaceChildren();
  $("#emptyState").classList.toggle("hidden", state.jobs.length > 0);
  const template = $("#jobRowTemplate");
  state.jobs.forEach((job) => {
    const row = template.content.cloneNode(true);
    const checkbox = row.querySelector(".job-check");
    checkbox.dataset.jobId = job.id;
    checkbox.disabled = job.status !== "PENDING_APPROVAL" || !job.reviewed_at;
    row.querySelector(".job-title").textContent = job.title;
    row.querySelector(".job-source").textContent = `${job.source_type} · ${job.external_id || "无外部编号"}`;
    row.querySelector(".job-desc").textContent = job.description
      ? `${job.description.slice(0, 105)}${job.description.length > 105 ? "…" : ""}`
      : "尚未生成文案";
    row.querySelector(".job-price").textContent = `¥ ${job.price}`;
    row.querySelector(".job-delivery").textContent = job.delivery;
    const status = row.querySelector(".status");
    status.textContent = statusLabels[job.status] || job.status;
    status.classList.add(job.status);
    row.querySelector(".job-error").textContent = job.error_message || "";
    const thumbs = row.querySelector(".thumbs");
    (job.image_urls || []).forEach((url) => {
      const image = document.createElement("img");
      image.src = url;
      image.alt = `${job.title} 水印图`;
      thumbs.append(image);
    });
    const actions = row.querySelector(".row-actions");
    if (job.status === "PENDING_APPROVAL") {
      actions.append(actionButton(job.reviewed_at ? "查看完整内容（已复核）" : "查看完整内容并复核", () => openReview(job.id), job.reviewed_at ? "" : "primary"));
    }
    if (job.status === "INGESTED") {
      actions.append(actionButton("生成文案与图片", () => generate(job.id), "primary"));
    }
    if (job.error_code === "RECEIPT_UNCERTAIN" || job.status === "AWAITING_RECEIPT") {
      actions.append(actionButton("对账：填写已发布回执", () => reconcilePublished(job.id)));
      actions.append(actionButton("对账：确认未发布", () => reconcileNotPublished(job.id)));
    } else if (["BLOCKED", "FAILED"].includes(job.status)) {
      actions.append(actionButton("复核后重新排队", () => retry(job.id)));
    }
    if (job.receipt_url) {
      const link = document.createElement("a");
      link.className = "button subtle";
      link.href = job.receipt_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "打开发布回执";
      actions.append(link);
    }
    rows.append(row);
  });
}

function actionButton(label, callback, variant = "") {
  const button = document.createElement("button");
  button.className = `button ${variant}`;
  button.textContent = label;
  button.addEventListener("click", callback);
  return button;
}

async function refresh() {
  try {
    const [health, jobs, settings] = await Promise.all([
      api("/api/health"),
      api("/api/jobs"),
      api("/api/settings"),
    ]);
    state.health = health;
    state.jobs = jobs.jobs;
    state.settings = settings.settings;
    $("#healthDot").classList.add("ok");
    $("#healthText").textContent = "本地服务正常";
    render();
  } catch (error) {
    $("#healthDot").classList.remove("ok");
    $("#healthText").textContent = error.message;
  }
}

async function importFile() {
  const file = $("#sourceFile").files[0];
  if (!file) return setResult("请先选择 CSV 或 JSON 文件。", true);
  try {
    const text = await file.text();
    let result;
    if (file.name.toLowerCase().endsWith(".json")) {
      const parsed = JSON.parse(text);
      const records = Array.isArray(parsed) ? parsed : (parsed.records || [parsed]);
      result = await api("/api/import/json", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ records }),
      });
    } else {
      result = await api("/api/import/csv", {
        method: "POST",
        headers: { "Content-Type": "text/csv; charset=utf-8" },
        body: text,
      });
    }
    setResult(`导入 ${result.imported.length} 条；重复跳过 ${result.duplicates.length} 条；错误 ${result.errors.length} 条。${result.errors.length ? `\n${JSON.stringify(result.errors, null, 2)}` : ""}`, result.errors.length > 0);
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function generate(jobId) {
  try {
    await api(`/api/jobs/${jobId}/generate`, { method: "POST" });
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function generateAll() {
  try {
    const result = await api("/api/generate-all", { method: "POST" });
    setResult(`已生成 ${result.generated.length} 条；失败 ${result.errors.length} 条。`, result.errors.length > 0);
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function approveSelected() {
  const jobIds = [...document.querySelectorAll(".job-check:checked")].map((item) => item.dataset.jobId);
  if (!jobIds.length) return setResult("请先选择待审批任务。", true);
  const required = `确认发布${jobIds.length}条`;
  const typed = window.prompt(`这会把 ${jobIds.length} 条任务放入真实发布队列。\n请输入：${required}`);
  if (typed !== required) return setResult("未通过确认，审批已取消。", true);
  try {
    await api("/api/jobs/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: jobIds, acknowledgement: typed }),
    });
    setResult(`已审批 ${jobIds.length} 条。只有发布总开关开启时，扩展才会领取。`);
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

function openReview(jobId) {
  const job = state.jobs.find((item) => item.id === jobId);
  if (!job) return;
  state.reviewingJobId = jobId;
  $("#reviewTitle").textContent = job.title;
  const meta = $("#reviewMeta");
  meta.replaceChildren();
  [
    `售价：¥${job.price}`,
    `原价：${job.original_price ? `¥${job.original_price}` : "未填写"}`,
    `交易：${job.delivery}${job.shipping_fee ? ` / 运费 ¥${job.shipping_fee}` : ""}`,
    `所在地：${job.location || "保持账号默认"}`,
    `来源：${job.source_type}`,
    `来源编号：${job.external_id || "无"}`,
  ].forEach((text) => {
    const span = document.createElement("span");
    span.textContent = text;
    meta.append(span);
  });
  const facts = $("#reviewFacts");
  facts.replaceChildren();
  Object.entries(job.facts || {}).forEach(([key, value]) => {
    const term = document.createElement("dt");
    term.textContent = key;
    const detail = document.createElement("dd");
    detail.textContent = value;
    facts.append(term, detail);
  });
  if (job.notes) {
    const term = document.createElement("dt");
    term.textContent = "补充说明";
    const detail = document.createElement("dd");
    detail.textContent = job.notes;
    facts.append(term, detail);
  }
  $("#reviewDescription").textContent = job.description;
  const images = $("#reviewImages");
  images.replaceChildren();
  (job.image_urls || []).forEach((url) => {
    const image = document.createElement("img");
    image.src = url;
    image.alt = `${job.title} 完整水印图`;
    images.append(image);
  });
  $("#confirmReviewButton").textContent = job.reviewed_at ? "重新确认完整内容" : "确认已核对完整内容";
  $("#reviewDialog").showModal();
}

async function confirmFullReview() {
  const required = "确认已核对完整文案与商品事实";
  const typed = window.prompt(`请输入：${required}`);
  if (typed !== required) return setResult("未完成完整内容复核。", true);
  try {
    await api(`/api/jobs/${state.reviewingJobId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledgement: typed }),
    });
    $("#reviewDialog").close();
    setResult("完整内容已复核，现在可以勾选审批。");
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function togglePublisher() {
  const enabled = !state.health.publisher_enabled;
  const required = enabled ? "启用自动发布" : "关闭自动发布";
  const typed = window.prompt(`请输入：${required}`);
  if (typed !== required) return setResult("总开关未改变。", true);
  try {
    await api("/api/publisher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, acknowledgement: typed }),
    });
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function retry(jobId) {
  if (!window.confirm("请确认你已经检查失败原因和当前平台页面，再重新排队。")) return;
  try {
    await api(`/api/jobs/${jobId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acknowledgement: "确认重新排队" }),
    });
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function reconcilePublished(jobId) {
  const receiptUrl = window.prompt("先在“我的闲鱼”确认商品确实存在，再粘贴该商品的完整 HTTPS URL：");
  if (!receiptUrl) return;
  let itemId = "";
  try {
    const url = new URL(receiptUrl);
    itemId = url.searchParams.get("id") || "";
  } catch {
    return setResult("回执 URL 无效。", true);
  }
  const required = "确认回执归属该任务";
  const typed = window.prompt(`请输入：${required}`);
  if (typed !== required) return setResult("对账已取消。", true);
  try {
    await api(`/api/jobs/${jobId}/reconcile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: "found_published",
        acknowledgement: typed,
        receipt_url: receiptUrl,
        item_id: itemId,
      }),
    });
    setResult("已按人工核验回执标记为发布成功。");
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function reconcileNotPublished(jobId) {
  const required = "确认未发布并重新排队";
  const typed = window.prompt(`必须先检查“我的闲鱼”和相关商品状态，确认没有发布结果。\n请输入：${required}`);
  if (typed !== required) return setResult("对账已取消。", true);
  try {
    await api(`/api/jobs/${jobId}/reconcile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: "verified_not_published",
        acknowledgement: typed,
      }),
    });
    setResult("已记录人工确认未发布，任务返回待审批状态。");
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function saveSettings() {
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        brand_name: $("#brandName").value.trim(),
        watermark_text: $("#watermarkText").value.trim(),
      }),
    });
    setResult("品牌设置已保存。新生成的图片会使用新水印。");
    await refresh();
  } catch (error) {
    setResult(error.message, true);
  }
}

async function showPairing() {
  try {
    const pairing = await api("/api/pairing-token");
    $("#pairingUrl").value = pairing.server_url;
    $("#pairingToken").value = pairing.extension_token;
    $("#pairingCopyStatus").textContent = "";
    $("#pairingBox").classList.remove("hidden");
  } catch (error) {
    setResult(error.message, true);
  }
}

async function copyPairingToken() {
  const token = $("#pairingToken").value;
  const status = $("#pairingCopyStatus");
  if (!token) {
    status.textContent = "请先点击“显示一次配对信息”。";
    return;
  }
  try {
    await navigator.clipboard.writeText(token);
  } catch {
    const temporary = document.createElement("textarea");
    temporary.value = token;
    temporary.setAttribute("aria-hidden", "true");
    temporary.style.cssText = "position:fixed;left:-9999px;opacity:0";
    document.body.appendChild(temporary);
    temporary.select();
    const copied = document.execCommand("copy");
    temporary.remove();
    if (!copied) {
      status.textContent = "复制失败，请允许本地页面使用剪贴板后重试。";
      return;
    }
  }
  status.textContent = "真实配对令牌已复制；请直接粘贴到扩展设置。";
}

function downloadSample() {
  const csv = "\ufeffsource_type,external_id,title,price,original_price,delivery,location,source_url,rights_confirmed,fact_交付内容,fact_适用范围,notes\nlocal,DEMO-001,门店小程序定制服务,1999,2999,无需邮寄,,,true,源码与后台,以实际沟通确认的平台和功能为准,下单前确认功能清单\n";
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "xianyu-authorized-products-template.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

$("#importButton").addEventListener("click", importFile);
$("#generateAllButton").addEventListener("click", generateAll);
$("#approveButton").addEventListener("click", approveSelected);
$("#publisherButton").addEventListener("click", togglePublisher);
$("#refreshButton").addEventListener("click", refresh);
$("#saveSettingsButton").addEventListener("click", saveSettings);
$("#pairingButton").addEventListener("click", showPairing);
$("#copyPairingTokenButton").addEventListener("click", copyPairingToken);
$("#sampleButton").addEventListener("click", downloadSample);
$("#selectAll").addEventListener("change", (event) => {
  document.querySelectorAll(".job-check:not(:disabled)").forEach((item) => { item.checked = event.target.checked; });
});
$("#closeReviewButton").addEventListener("click", () => $("#reviewDialog").close());
$("#confirmReviewButton").addEventListener("click", confirmFullReview);

refresh();
setInterval(refresh, 7000);
