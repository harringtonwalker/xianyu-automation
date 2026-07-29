(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.XianyuCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const RISK_SIGNALS = [
    "验证码",
    "滑块",
    "安全验证",
    "异常操作",
    "访问受限",
    "账号存在风险",
    "操作过于频繁",
  ];
  const DELIVERY = ["包邮", "按距离计费", "一口价", "无需邮寄"];
  const VERIFIED_SIGNATURES = {
    BASE: "5dd2c232",
    FLAT_SHIPPING_VISIBLE: "7eeb481c",
  };
  const GLOBAL_BLOCK_CODES = new Set([
    "RISK_SIGNAL",
    "DOM_CONTRACT_CHANGED",
    "WRONG_PAGE",
    "IMAGE_UPLOAD_FAILED",
    "IMAGE_UPLOAD_UNVERIFIED",
    "FORM_DEFAULTS_CHANGED",
    "RECEIPT_UNCERTAIN",
  ]);

  function clean(value, limit = 160) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
  }

  function isVisible(element) {
    if (!element) return false;
    const style = typeof getComputedStyle === "function" ? getComputedStyle(element) : null;
    if (style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0)) return false;
    return typeof element.getClientRects !== "function" || element.getClientRects().length > 0;
  }

  function riskSignal(text) {
    const normalized = clean(text, 12000);
    return RISK_SIGNALS.find((signal) => normalized.includes(signal)) || "";
  }

  function stableHash(value) {
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }

  function anchoredPriceField(doc, pattern) {
    const labels = [...doc.querySelectorAll("label")];
    for (const label of labels) {
      const labelText = clean(label.innerText);
      if (!pattern.test(labelText)) continue;
      let node = label;
      for (let depth = 0; depth < 7 && node; depth += 1) {
        const candidates = [...(node.querySelectorAll?.('input[placeholder="0.00"]') || [])].filter(isVisible);
        if (candidates.length === 1) return { input: candidates[0], label: labelText };
        node = node.parentElement;
      }
    }
    return null;
  }

  function anchoredLabeledText(doc, labelText) {
    const labels = [...doc.querySelectorAll("label")].filter(
      (label) => clean(label.innerText) === labelText
    );
    if (labels.length !== 1) return null;
    let node = labels[0].parentElement;
    for (let depth = 0; depth < 5 && node; depth += 1) {
      const text = clean(node.innerText, 500);
      if (text.startsWith(labelText) && text.length > labelText.length) {
        const value = clean(text.slice(labelText.length), 160);
        if (value) return { label: labelText, value };
      }
      node = node.parentElement;
    }
    return null;
  }

  function anchoredSwitch(doc, labelText) {
    const labels = [...doc.querySelectorAll("div,span,label")].filter(
      (element) => isVisible(element) && clean(element.innerText) === labelText
    );
    for (const label of labels) {
      let node = label.parentElement;
      for (let depth = 0; depth < 5 && node; depth += 1) {
        const switches = [...(node.querySelectorAll?.('[role="switch"]') || [])].filter(isVisible);
        if (switches.length === 1) {
          return {
            input: switches[0],
            label: labelText,
            checked: switches[0].getAttribute?.("aria-checked") === "true",
          };
        }
        node = node.parentElement;
      }
    }
    return null;
  }

  function pageContract(doc, href) {
    // Native file inputs are commonly visually hidden behind an upload card.
    // They remain the authoritative control and must not be rejected for zero client rects.
    const files = [...doc.querySelectorAll('input[type="file"]')];
    const editors = [...doc.querySelectorAll('[contenteditable="true"]')].filter(isVisible);
    const allPriceInputs = [...doc.querySelectorAll('input[placeholder="0.00"]')].filter(isVisible);
    const priceField = anchoredPriceField(doc, /^价格\s*\*?$/);
    const originalPriceField = anchoredPriceField(doc, /^原价$/);
    const shippingFeeField = anchoredPriceField(doc, /^邮费\s*\*?$/);
    const selfPickupField = anchoredSwitch(doc, "支持自提");
    const locationField = anchoredLabeledText(doc, "宝贝所在地");
    const priceInputs = [priceField?.input, originalPriceField?.input, shippingFeeField?.input].filter(Boolean);
    const labels = [...doc.querySelectorAll("label")].map((item) => clean(item.innerText)).filter(Boolean);
    const publishButtons = [...doc.querySelectorAll("button")].filter(
      (item) => isVisible(item) && clean(item.innerText) === "发布"
    );
    const descriptor = JSON.stringify({
      path: new URL(href).pathname,
      fileAccept: files.map((item) => item.getAttribute?.("accept") || item.accept || "").sort(),
      editorCount: editors.length,
      fieldAnchors: [priceField?.label, originalPriceField?.label, shippingFeeField?.label].filter(Boolean),
      rawPriceCount: allPriceInputs.length,
      delivery: DELIVERY.filter((label) => labels.includes(label)),
      publishCount: publishButtons.length,
    });
    return {
      path: new URL(href).pathname,
      files,
      editors,
      priceInputs,
      allPriceInputs,
      priceField,
      originalPriceField,
      shippingFeeField,
      selfPickupField,
      locationField,
      labels,
      publishButtons,
      signature: stableHash(descriptor),
      descriptor,
    };
  }

  function preflight(doc, href, allowedSignatures = [VERIFIED_SIGNATURES.BASE]) {
    const risk = riskSignal(doc.body?.innerText || "");
    if (risk) return { ok: false, code: "RISK_SIGNAL", message: `检测到平台风控提示：${risk}` };
    const url = new URL(href);
    if (url.hostname !== "www.goofish.com" || url.pathname !== "/publish") {
      return { ok: false, code: "WRONG_PAGE", message: "当前不是闲鱼 Web 发布页" };
    }
    const contract = pageContract(doc, href);
    const missing = [];
    if (contract.files.length !== 1) missing.push("唯一图片上传控件");
    if (contract.editors.length !== 1) missing.push("唯一宝贝描述编辑器");
    if (!contract.priceField) missing.push("价格语义控件");
    if (!contract.originalPriceField) missing.push("原价语义控件");
    if (![2, 3].includes(contract.allPriceInputs.length)) missing.push("价格控件数量");
    if (contract.priceInputs.length !== contract.allPriceInputs.length) missing.push("存在未锚定价格控件");
    if (contract.publishButtons.length !== 1) missing.push("唯一发布按钮");
    if (!contract.selfPickupField) missing.push("支持自提语义控件");
    if (!contract.locationField) missing.push("宝贝所在地语义控件");
    for (const delivery of DELIVERY) if (!contract.labels.includes(delivery)) missing.push(`交易方式:${delivery}`);
    if (missing.length || !allowedSignatures.includes(contract.signature)) {
      if (!allowedSignatures.includes(contract.signature)) {
        missing.push(`未验证契约签名:${contract.signature}`);
      }
      return {
        ok: false,
        code: "DOM_CONTRACT_CHANGED",
        message: `页面字段契约不匹配：${missing.join("、")}`,
        signature: contract.signature,
      };
    }
    return { ok: true, contract };
  }

  function validateJob(job) {
    const errors = [];
    if (!job || !job.id || !job.lease_token) errors.push("任务或租约缺失");
    if (!job.description || job.description.length < 20 || job.description.length > 1500) errors.push("描述长度无效");
    if (!Array.isArray(job.image_urls) || job.image_urls.length < 1 || job.image_urls.length > 9) errors.push("图片数量必须为1到9张");
    if (!/^\d+(\.\d{1,2})?$/.test(String(job.price || ""))) errors.push("价格格式无效");
    if (!DELIVERY.includes(job.delivery)) errors.push("交易方式无效");
    if (
      job.delivery === "一口价"
      && !/^\d+(\.\d{1,2})?$/.test(String(job.shipping_fee || ""))
    ) {
      errors.push("一口价邮费格式无效");
    }
    if (job.delivery !== "一口价" && String(job.shipping_fee || "") !== "") {
      errors.push("非一口价任务不得携带固定邮费");
    }
    if (job.execution_mode !== "submit") errors.push("任务未授权真实提交");
    if (job.location_mode !== "KEEP_ACCOUNT_DEFAULT") errors.push("当前适配器仅允许保持账号默认所在地");
    return { ok: errors.length === 0, errors };
  }

  function formHasUserDraft(contract) {
    return (
      contract.files.some((input) => Number(input.files?.length || 0) > 0)
      || contract.editors.some((editor) => clean(editor.innerText, 2000) !== "")
      || contract.allPriceInputs.some((input) => String(input.value || "") !== "")
      || contract.selfPickupField?.checked === true
    );
  }

  function formDefaultsFresh(defaults, now = Date.now()) {
    if (!defaults || typeof defaults !== "object") return false;
    const verifiedAt = Date.parse(defaults.verifiedAt || "");
    return (
      defaults.contractSignature === VERIFIED_SIGNATURES.BASE
      && Number.isFinite(verifiedAt)
      && verifiedAt <= now
      && now - verifiedAt <= 24 * 60 * 60 * 1000
      && clean(defaults.locationText, 160).length > 0
      && defaults.selfPickupEnabled === false
      && Array.isArray(defaults.blankUploadPreviewKeys)
      && defaults.blankUploadPreviewKeys.length === 1
      && clean(defaults.blankUploadRegionText, 500).includes("添加首图")
    );
  }

  function formDefaultsMatch(expected, current) {
    if (!formDefaultsFresh(expected)) return false;
    return (
      expected.contractSignature === current.contractSignature
      && clean(expected.locationText, 160) === clean(current.locationText, 160)
      && expected.selfPickupEnabled === current.selfPickupEnabled
      && clean(expected.blankUploadRegionText, 500) === clean(current.blankUploadRegionText, 500)
      && JSON.stringify([...expected.blankUploadPreviewKeys].sort())
        === JSON.stringify([...(current.blankUploadPreviewKeys || [])].sort())
    );
  }

  function itemIdFromUrl(href) {
    try {
      const url = new URL(href);
      if (url.hostname !== "www.goofish.com" || url.pathname !== "/item") return "";
      return url.searchParams.get("id") || "";
    } catch {
      return "";
    }
  }

  function authorizedOwnerPage(href, expectedXianyuUserId = "") {
    try {
      const url = new URL(href);
      if (url.hostname === "myseller.taobao.com" && url.pathname.includes("/SellManage/")) {
        return "taobao-own";
      }
      const expected = clean(expectedXianyuUserId, 40);
      if (
        url.hostname === "www.goofish.com"
        && url.pathname === "/personal"
        && /^\d{5,30}$/.test(expected)
        && url.searchParams.get("userId") === expected
      ) {
        return "xianyu-own";
      }
      return "";
    } catch {
      return "";
    }
  }

  function authorizedItemUrl(href, sourceType) {
    try {
      const url = new URL(href);
      const itemId = url.searchParams.get("id") || "";
      if (!/^\d{5,30}$/.test(itemId)) return false;
      if (sourceType === "xianyu-own") {
        return url.protocol === "https:"
          && url.hostname === "www.goofish.com"
          && url.pathname === "/item";
      }
      if (sourceType === "taobao-own") {
        return url.protocol === "https:"
          && url.hostname === "item.taobao.com"
          && url.pathname === "/item.htm";
      }
      return false;
    } catch {
      return false;
    }
  }

  function receiptMatches(expected, candidate) {
    const expectedTitle = clean(expected.expectedTitle, 160);
    const candidateTitle = clean(candidate.pageTitle, 200).replace(/_闲鱼$/, "");
    const expectedPriceCents = Math.round(Number(expected.expectedPrice) * 100);
    const candidatePriceCents = (candidate.pagePrices || [])
      .map((value) => Math.round(Number(value) * 100))
      .filter(Number.isFinite);
    return {
      titleMatched: Boolean(expectedTitle) && candidateTitle === expectedTitle,
      priceMatched: Number.isFinite(expectedPriceCents) && candidatePriceCents.includes(expectedPriceCents),
    };
  }

  function executionFailureStage(code) {
    return GLOBAL_BLOCK_CODES.has(String(code || "")) ? "blocked" : "failed";
  }

  return {
    DELIVERY,
    GLOBAL_BLOCK_CODES,
    RISK_SIGNALS,
    VERIFIED_SIGNATURES,
    authorizedOwnerPage,
    authorizedItemUrl,
    clean,
    executionFailureStage,
    formDefaultsFresh,
    formDefaultsMatch,
    formHasUserDraft,
    isVisible,
    itemIdFromUrl,
    pageContract,
    preflight,
    receiptMatches,
    riskSignal,
    stableHash,
    validateJob,
  };
});
