async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("找不到当前标签页");
  return tab;
}

function show(selector, text, ok) {
  const element = document.querySelector(selector);
  element.textContent = text;
  element.className = `status ${ok ? "ok" : "bad"}`;
}

document.querySelector("#delivery").addEventListener("change", (event) => {
  const flatShipping = event.target.value === "一口价";
  document.querySelector("#shippingFeeGroup").classList.toggle("hidden", !flatShipping);
  if (!flatShipping) document.querySelector("#shippingFee").value = "";
});

document.querySelector("#preflight").addEventListener("click", async () => {
  try {
    const tab = await activeTab();
    const result = await chrome.tabs.sendMessage(tab.id, { type: "PREFLIGHT" });
    if (!result.ok) throw new Error(result.message || "页面契约检查失败");
    await chrome.storage.local.set({ verifiedFormDefaults: result.formDefaults });
    show(
      "#preflightResult",
      `通过\n契约签名：${result.signature}\n账号默认所在地：${result.formDefaults.locationText}\n自提：关闭\n有效期：24小时`,
      true
    );
  } catch (error) {
    show("#preflightResult", error.message, false);
  }
});

document.querySelector("#extract").addEventListener("click", async () => {
  try {
    const tab = await activeTab();
    const config = await chrome.storage.local.get({ xianyuOwnerUserId: "" });
    const confirmedDelivery = document.querySelector("#delivery").value;
    if (!confirmedDelivery) throw new Error("请先明确选择本批商品的交易方式");
    const confirmedShippingFee = document.querySelector("#shippingFee").value.trim();
    if (
      confirmedDelivery === "一口价"
      && !/^\d+(?:\.\d{1,2})?$/.test(confirmedShippingFee)
    ) {
      throw new Error("一口价必须填写有效固定邮费");
    }
    const extracted = await chrome.tabs.sendMessage(tab.id, {
      type: "EXTRACT_OWN",
      expectedXianyuUserId: config.xianyuOwnerUserId,
      confirmedDelivery,
      confirmedShippingFee,
    });
    if (!extracted.ok) throw new Error(extracted.error);
    if (!extracted.records.length) throw new Error("当前页面没有识别到可导入商品");
    const imported = await chrome.runtime.sendMessage({ type: "IMPORT_RECORDS", records: extracted.records });
    if (!imported.ok) throw new Error(imported.error);
    show(
      "#extractResult",
      `识别 ${extracted.records.length} 条；导入 ${imported.payload.imported.length} 条；重复 ${imported.payload.duplicates.length} 条；错误 ${imported.payload.errors.length} 条。`,
      imported.payload.errors.length === 0
    );
  } catch (error) {
    show("#extractResult", error.message, false);
  }
});

document.querySelector("#poll").addEventListener("click", async () => {
  const result = await chrome.runtime.sendMessage({ type: "POLL_NOW" });
  show("#runtimeResult", result.ok ? "已检查队列" : result.error, result.ok);
});
document.querySelector("#options").addEventListener("click", (event) => {
  event.preventDefault();
  chrome.runtime.openOptionsPage();
});
