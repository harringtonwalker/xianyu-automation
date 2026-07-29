const DEFAULTS = {
  serverUrl: "http://127.0.0.1:8766",
  extensionToken: "",
  pollingEnabled: true,
  xianyuOwnerUserId: "",
};

async function restore() {
  const config = await chrome.storage.local.get(DEFAULTS);
  document.querySelector("#serverUrl").value = config.serverUrl;
  document.querySelector("#extensionToken").value = config.extensionToken;
  document.querySelector("#pollingEnabled").checked = config.pollingEnabled;
  document.querySelector("#xianyuOwnerUserId").value = config.xianyuOwnerUserId;
}

document.querySelector("#save").addEventListener("click", async () => {
  const serverUrl = document.querySelector("#serverUrl").value.trim().replace(/\/$/, "");
  const extensionToken = document.querySelector("#extensionToken").value.trim();
  const pollingEnabled = document.querySelector("#pollingEnabled").checked;
  const xianyuOwnerUserId = document.querySelector("#xianyuOwnerUserId").value.trim();
  const status = document.querySelector("#status");
  if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(serverUrl)) {
    status.textContent = "地址必须是本机 HTTP 地址";
    status.style.color = "#a63b32";
    return;
  }
  if (!/^[A-Za-z0-9_-]{40,200}$/.test(extensionToken)) {
    status.textContent = "配对令牌格式无效：请只复制令牌输入框中的英文、数字、- 和 _";
    status.style.color = "#a63b32";
    return;
  }
  if (xianyuOwnerUserId && !/^\d{5,30}$/.test(xianyuOwnerUserId)) {
    status.textContent = "闲鱼本人用户 ID 格式无效";
    status.style.color = "#a63b32";
    return;
  }
  await chrome.storage.local.set({ serverUrl, extensionToken, pollingEnabled, xianyuOwnerUserId });
  await chrome.storage.local.remove("verifiedFormDefaults");
  try {
    const response = await fetch(`${serverUrl}/api/extension/ping`, {
      headers: { "X-Xianyu-Extension-Token": extensionToken },
    });
    if (!response.ok) throw new Error(`连接失败：${response.status}`);
    status.textContent = "已保存，配对成功";
    status.style.color = "#237a52";
  } catch (error) {
    status.textContent = error.message;
    status.style.color = "#a63b32";
  }
});

restore();
