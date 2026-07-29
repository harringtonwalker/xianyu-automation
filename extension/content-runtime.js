(function (root, factory) {
  const core = typeof module === "object" && module.exports
    ? require("./core.js")
    : root.XianyuCore;
  const api = factory(core);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.XianyuContentRuntime = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (Core) {
  const UPLOAD_ERRORS = /上传失败|图片上传失败|上传出错|重新上传|格式不支持|文件过大/;
  const VERIFIED_BLANK_UPLOAD_ICON_FRAGMENT = "O1CN016XczIR1iimNeEcZoh_";

  function uploadRegion(input) {
    let node = input?.parentElement || null;
    for (let depth = 0; depth < 10 && node; depth += 1) {
      const text = Core.clean(node.innerText || node.textContent || "", 2000);
      if (
        /宝贝图片|商品图片|上传图片/.test(text)
        && typeof node.querySelectorAll === "function"
      ) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }

  function previewKeys(region) {
    if (!region || typeof region.querySelectorAll !== "function") return new Set();
    const keys = [];
    for (const element of region.querySelectorAll('img[src], [style*="background-image"]')) {
      const src = element.currentSrc || element.getAttribute?.("src") || element.src || "";
      const style = element.getAttribute?.("style") || "";
      const key = Core.clean(src || style, 2000);
      if (key) keys.push(key);
    }
    return new Set(keys);
  }

  function blankUploadEvidence(doc, input) {
    const currentInputs = [...doc.querySelectorAll('input[type="file"]')];
    const currentInput = currentInputs.length === 1 ? currentInputs[0] : input;
    const region = uploadRegion(currentInput);
    if (!region) return { ok: false, reason: "无法确定图片上传区域" };
    const regionText = Core.clean(region.innerText || region.textContent || "", 500);
    const keys = [...previewKeys(region)].sort();
    const busyCount = [...region.querySelectorAll(
      '[role="progressbar"],[aria-busy="true"],[class*="uploading"],[class*="progress"],[class*="loading"]'
    )].filter(Core.isVisible).length;
    const error = regionText.match(UPLOAD_ERRORS)?.[0] || "";
    const fileCount = Number(currentInput?.files?.length || 0);
    const reasons = [];
    if (fileCount !== 0) reasons.push("原生图片文件不为空");
    if (!regionText.includes("添加首图")) reasons.push("缺少空白图片入口");
    if (keys.length !== 1) reasons.push(`空白图片区基准图标数量为 ${keys.length}`);
    if (
      keys.length === 1
      && !keys[0].includes(VERIFIED_BLANK_UPLOAD_ICON_FRAGMENT)
    ) {
      reasons.push("空白图片区图标不匹配已验证契约");
    }
    if (busyCount) reasons.push("图片区仍有上传进度");
    if (error) reasons.push(`图片区包含错误：${error}`);
    return {
      ok: reasons.length === 0,
      reason: reasons.join("；"),
      fileCount,
      regionText,
      previewKeys: keys,
      busyCount,
    };
  }

  function uploadSnapshot(doc, input, expectedCount, baselineKeys) {
    const currentInputs = [...doc.querySelectorAll('input[type="file"]')];
    const currentInput = currentInputs.length === 1 ? currentInputs[0] : input;
    const region = uploadRegion(currentInput);
    if (!region) {
      return {
        ready: false,
        terminalError: "无法确定图片上传区域",
        code: "IMAGE_UPLOAD_UNVERIFIED",
      };
    }
    const text = Core.clean(region.innerText || region.textContent || "", 5000);
    const errorMatch = text.match(UPLOAD_ERRORS);
    if (errorMatch) {
      return {
        ready: false,
        terminalError: `平台图片上传失败：${errorMatch[0]}`,
        code: "IMAGE_UPLOAD_FAILED",
      };
    }
    const busy = [...region.querySelectorAll(
      '[role="progressbar"],[aria-busy="true"],[class*="uploading"],[class*="progress"],[class*="loading"]'
    )].filter(Core.isVisible);
    const currentKeys = previewKeys(region);
    const newKeys = [...currentKeys].filter((key) => !baselineKeys.has(key));
    const fileCount = Number(currentInput?.files?.length || 0);
    return {
      ready: fileCount === expectedCount && newKeys.length >= expectedCount && busy.length === 0,
      terminalError: "",
      code: "",
      fileCount,
      previewCount: newKeys.length,
      busyCount: busy.length,
      previewSignature: [...newKeys].sort().join("|"),
    };
  }

  async function waitForUploadCompletion({
    doc,
    input,
    expectedCount,
    baselineKeys,
    timeoutMs = 60000,
    pollMs = 500,
    stablePasses = 3,
    sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  }) {
    const deadline = Date.now() + timeoutMs;
    let consecutive = 0;
    let priorSignature = "";
    let last = null;
    do {
      last = uploadSnapshot(doc, input, expectedCount, baselineKeys);
      if (last.terminalError) {
        throw Object.assign(new Error(last.terminalError), { code: last.code });
      }
      if (last.ready && last.previewSignature === priorSignature) {
        consecutive += 1;
      } else {
        consecutive = last.ready ? 1 : 0;
      }
      priorSignature = last.previewSignature || "";
      if (consecutive >= stablePasses) return last;
      await sleep(pollMs);
    } while (Date.now() <= deadline);
    throw Object.assign(
      new Error(
        `60 秒内未取得图片上传完成证据（文件 ${last?.fileCount || 0}/${expectedCount}，`
        + `新增预览 ${last?.previewCount || 0}/${expectedCount}，进行中 ${last?.busyCount || 0}）`
      ),
      { code: "IMAGE_UPLOAD_UNVERIFIED" }
    );
  }

  return {
    VERIFIED_BLANK_UPLOAD_ICON_FRAGMENT,
    blankUploadEvidence,
    previewKeys,
    uploadRegion,
    uploadSnapshot,
    waitForUploadCompletion,
  };
});
