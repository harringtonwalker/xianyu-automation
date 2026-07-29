const Core = globalThis.XianyuCore;
const Runtime = globalThis.XianyuContentRuntime;

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function setNativeValue(input, value) {
  const prototype = input instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  if (!setter) throw new Error("无法取得输入框原生 setter");
  setter.call(input, String(value));
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  input.blur();
}

function fillEditor(editor, value) {
  editor.focus();
  editor.replaceChildren(document.createTextNode(value));
  editor.dispatchEvent(new InputEvent("input", {
    bubbles: true,
    inputType: "insertText",
    data: value,
  }));
  editor.dispatchEvent(new Event("change", { bubbles: true }));
  editor.blur();
}

async function sendReport(job, stage, payload) {
  const response = await chrome.runtime.sendMessage({
    type: "REPORT",
    jobId: job.id,
    leaseToken: job.lease_token,
    stage,
    payload,
  });
  if (!response?.ok) throw new Error(response?.error || `本地状态报告失败：${stage}`);
  return response;
}

async function imageFiles(urls) {
  const files = [];
  for (let index = 0; index < urls.length; index += 1) {
    const response = await chrome.runtime.sendMessage({ type: "FETCH_ASSET", url: urls[index] });
    if (!response?.ok) throw new Error(response?.error || "水印图片读取失败");
    const blob = new Blob([new Uint8Array(response.bytes)], { type: response.contentType });
    if (!blob.type.startsWith("image/")) throw new Error("本地资产不是图片");
    files.push(new File([blob], `xianyu-${String(index + 1).padStart(2, "0")}.png`, { type: blob.type }));
  }
  return files;
}

function assignFiles(input, files) {
  const transfer = new DataTransfer();
  files.forEach((file) => transfer.items.add(file));
  input.files = transfer.files;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

async function selectDelivery(labelText, shippingFee) {
  const label = [...document.querySelectorAll("label")].find(
    (item) => Core.clean(item.innerText) === labelText && Core.isVisible(item)
  );
  if (!label) throw Object.assign(new Error(`未找到交易方式：${labelText}`), { code: "DOM_CONTRACT_CHANGED" });
  label.click();
  await wait(250);
  if (labelText === "一口价") {
    if (!shippingFee) throw new Error("一口价交易必须提供 shipping_fee");
    const contract = Core.pageContract(document, location.href);
    if (!contract.shippingFeeField) throw Object.assign(new Error("一口价邮费语义控件未出现"), { code: "DOM_CONTRACT_CHANGED" });
    setNativeValue(contract.shippingFeeField.input, shippingFee);
  }
}

function currentFormDefaults(contract, uploadEvidence, verifiedAt = new Date().toISOString()) {
  return {
    contractSignature: contract.signature,
    locationText: contract.locationField.value,
    selfPickupEnabled: contract.selfPickupField.checked,
    blankUploadPreviewKeys: uploadEvidence.previewKeys,
    blankUploadRegionText: uploadEvidence.regionText,
    verifiedAt,
  };
}

function pairingPreflight() {
  const result = Core.preflight(document, location.href);
  if (!result.ok) return result;
  if (Core.formHasUserDraft(result.contract)) {
    return { ok: false, code: "FORM_NOT_BLANK", message: "发布页包含图片、文案、价格或已开启自提" };
  }
  const uploadEvidence = Runtime.blankUploadEvidence(document, result.contract.files[0]);
  if (!uploadEvidence.ok) {
    return {
      ok: false,
      code: "FORM_NOT_BLANK",
      message: `图片区域不是已验证空白状态：${uploadEvidence.reason}`,
    };
  }
  const formDefaults = currentFormDefaults(result.contract, uploadEvidence);
  if (!Core.formDefaultsFresh(formDefaults)) {
    return { ok: false, code: "FORM_DEFAULTS_CHANGED", message: "空白表单默认值不满足安全契约" };
  }
  return {
    ok: true,
    signature: result.contract.signature,
    descriptor: result.contract.descriptor,
    formDefaults,
  };
}

async function runJob(job, verifiedFormDefaults) {
  const valid = Core.validateJob(job);
  if (!valid.ok) throw Object.assign(new Error(valid.errors.join("；")), { code: "INVALID_JOB" });
  if (!Core.formDefaultsFresh(verifiedFormDefaults)) {
    throw Object.assign(
      new Error("缺少24小时内人工核对的空白发布页默认值"),
      { code: "FORM_DEFAULTS_CHANGED" }
    );
  }
  const before = Core.preflight(document, location.href);
  if (!before.ok) throw Object.assign(new Error(before.message), { code: before.code, signature: before.signature });
  const contract = before.contract;
  // The current blank Xianyu publish form preselects one delivery radio.
  // A delivery default is not a saved draft because this adapter always
  // overwrites it with the reviewed job value and reads it back.
  const initialDirty = Core.formHasUserDraft(contract);
  if (initialDirty) {
    throw Object.assign(new Error("专用发布页不是空白表单，已停止以避免覆盖草稿"), { code: "FORM_NOT_BLANK" });
  }
  const blankUpload = Runtime.blankUploadEvidence(document, contract.files[0]);
  const currentDefaults = currentFormDefaults(
    contract,
    blankUpload,
    verifiedFormDefaults.verifiedAt
  );
  if (!blankUpload.ok || !Core.formDefaultsMatch(verifiedFormDefaults, currentDefaults)) {
    throw Object.assign(
      new Error(`发布页默认状态与人工预检不一致：${blankUpload.reason || "所在地、自提或图片基准已变化"}`),
      { code: "FORM_DEFAULTS_CHANGED" }
    );
  }
  const files = await imageFiles(job.image_urls);
  const baselinePreviewKeys = new Set(blankUpload.previewKeys);
  assignFiles(contract.files[0], files);
  const uploadEvidence = await Runtime.waitForUploadCompletion({
    doc: document,
    input: contract.files[0],
    expectedCount: files.length,
    baselineKeys: baselinePreviewKeys,
  });
  fillEditor(contract.editors[0], job.description);
  setNativeValue(contract.priceInputs[0], job.price);
  setNativeValue(contract.priceInputs[1], job.original_price || "");
  await selectDelivery(job.delivery, job.shipping_fee);
  await wait(300);

  const allowedAfterSignatures = job.delivery === "一口价"
    ? [Core.VERIFIED_SIGNATURES.FLAT_SHIPPING_VISIBLE]
    : [Core.VERIFIED_SIGNATURES.BASE];
  const after = Core.preflight(document, location.href, allowedAfterSignatures);
  if (!after.ok) throw Object.assign(new Error(after.message), { code: after.code, signature: after.signature });
  const editorText = Core.clean(after.contract.editors[0].innerText, 2000);
  if (editorText !== Core.clean(job.description, 2000)) throw new Error("描述回读校验失败");
  if (after.contract.files[0].files.length !== files.length) throw new Error("图片数量回读校验失败");
  if (after.contract.priceInputs[0].value !== String(job.price)) throw new Error("价格回读校验失败");
  if (after.contract.priceInputs[1].value !== String(job.original_price || "")) throw new Error("原价回读校验失败");
  const selectedDelivery = [...document.querySelectorAll('input[type="radio"]:checked')]
    .map((input) => Core.clean(input.closest("label")?.innerText));
  if (!selectedDelivery.includes(job.delivery)) throw new Error("交易方式回读校验失败");
  if (after.contract.selfPickupField.checked) {
    throw Object.assign(new Error("支持自提状态发生变化"), { code: "FORM_DEFAULTS_CHANGED" });
  }
  if (after.contract.locationField.value !== verifiedFormDefaults.locationText) {
    throw Object.assign(
      new Error("宝贝所在地不再是人工预检的账号默认值"),
      { code: "FORM_DEFAULTS_CHANGED" }
    );
  }

  await sendReport(job, "filled", {
    contract_signature: after.contract.signature,
    image_count: files.length,
    uploaded_preview_count: uploadEvidence.previewCount,
    upload_busy_count: uploadEvidence.busyCount,
  });

  const risk = Core.riskSignal(document.body?.innerText || "");
  if (risk) throw Object.assign(new Error(`提交前检测到风控：${risk}`), { code: "RISK_SIGNAL" });
  if (!Core.formDefaultsFresh(verifiedFormDefaults)) {
    throw Object.assign(
      new Error("人工核对的空白发布页默认值已超过24小时有效期"),
      { code: "FORM_DEFAULTS_CHANGED" }
    );
  }
  await sendReport(job, "submitting", { contract_signature: after.contract.signature });
  try {
    after.contract.publishButtons[0].click();
  } catch (error) {
    throw Object.assign(
      new Error(`已进入提交阶段但无法确认点击结果：${error.message}`),
      { code: "RECEIPT_UNCERTAIN" }
    );
  }
  return { status: "submitting", contractSignature: after.contract.signature };
}

function extractOwnRecords(expectedXianyuUserId, confirmedDelivery, confirmedShippingFee) {
  const sourceType = Core.authorizedOwnerPage(location.href, expectedXianyuUserId);
  if (!sourceType) {
    throw new Error("仅允许淘宝“我的商品”或已在扩展设置中绑定用户 ID 的本人闲鱼个人页提取");
  }
  if (!Core.DELIVERY.includes(confirmedDelivery)) {
    throw new Error("必须先在扩展弹窗明确选择这批商品的交易/运费方式");
  }
  if (
    confirmedDelivery === "一口价"
    && !/^\d+(?:\.\d{1,2})?$/.test(String(confirmedShippingFee || ""))
  ) {
    throw new Error("一口价必须明确填写有效邮费");
  }
  const records = [];
  const seen = new Set();
  const candidates = [...document.querySelectorAll("tr, [class*='item'], [class*='card']")].filter(Core.isVisible).slice(0, 300);
  for (const candidate of candidates) {
    const text = Core.clean(candidate.innerText, 800);
    if (text.length < 8) continue;
    const links = [...candidate.querySelectorAll("a[href]")];
    const itemLink = links.find((link) => Core.authorizedItemUrl(link.href, sourceType));
    if (!itemLink) continue;
    const itemUrl = new URL(itemLink.href);
    const externalId = itemUrl.searchParams.get("id") || itemUrl.searchParams.get("itemId") || "";
    const dedupe = externalId || itemLink.href;
    if (seen.has(dedupe)) continue;
    seen.add(dedupe);
    const titleCandidates = links.map((link) => Core.clean(link.innerText, 120)).filter((item) => item.length >= 2);
    const title = titleCandidates.sort((a, b) => b.length - a.length)[0] || text.slice(0, 60);
    const price = (text.match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/) || text.match(/(?:价格|售价)\s*(\d+(?:\.\d{1,2})?)/) || [])[1];
    if (!price) continue;
    records.push({
      source_type: sourceType,
      external_id: externalId,
      title,
      price,
      delivery: confirmedDelivery,
      shipping_fee: confirmedDelivery === "一口价" ? confirmedShippingFee : "",
      source_url: itemLink.href,
      rights_confirmed: true,
      facts: { "自有后台页面摘要": text.slice(0, 500) },
    });
    if (records.length >= 100) break;
  }
  return records;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "RUN_JOB") {
    runJob(message.job, message.formDefaults)
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({
        ok: false,
        error: { code: error.code || "FORM_EXECUTION_FAILED", message: error.message, signature: error.signature || "" },
      }));
    return true;
  }
  if (message.type === "PREFLIGHT") {
    sendResponse(pairingPreflight());
  }
  if (message.type === "EXTRACT_OWN") {
    try {
      sendResponse({
        ok: true,
        records: extractOwnRecords(
          message.expectedXianyuUserId || "",
          message.confirmedDelivery || "",
          message.confirmedShippingFee || ""
        ),
      });
    } catch (error) {
      sendResponse({ ok: false, error: error.message });
    }
  }
});

const receiptItemId = Core.itemIdFromUrl(location.href);
if (receiptItemId) {
  const receiptPageText = Core.clean(document.body?.innerText || "", 5000);
  chrome.runtime.sendMessage({
    type: "RECEIPT_CANDIDATE",
    itemId: receiptItemId,
    receiptUrl: location.href,
    pageTitle: document.title,
    pageText: receiptPageText,
    pagePrices: [...receiptPageText.matchAll(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/g)]
      .map((match) => match[1])
      .slice(0, 20),
  }).catch(() => {});
}
