const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch {
    throw new Error(
      "Локальный сервер не ответил. Почему: он остановлен или страница потеряла соединение. Что сделать: запустите сервер и повторите.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg || "Некорректное значение").join(". ")
      : data.detail;
    throw new Error(
      detail ||
      `Запрос завершился с ошибкой HTTP ${response.status}. Сервер не передал подробную причину.`,
    );
  }
  return data;
}

function message(form, text, isError = false) {
  const node = $(".form-message", form);
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error-text", isError);
}

function busy(form, value) {
  const button = $("button[type='submit']", form);
  if (button) button.disabled = value;
}

function showToast(text) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = text;
  toast.classList.add("visible");
  setTimeout(() => toast.classList.remove("visible"), 2800);
}

function showOnboardingStep(step) {
  const overlay = $("#onboarding-overlay");
  if (!overlay) return;
  overlay.hidden = false;
  document.body.classList.add("onboarding-open");
  $$("[data-onboarding-panel]", overlay).forEach((panel) => {
    panel.hidden = panel.dataset.onboardingPanel !== step;
  });
  $$("[data-progress-step]", overlay).forEach((item) => {
    const order = { credentials: 0, telegram: 1, success: 2 };
    item.classList.toggle(
      "active",
      order[item.dataset.progressStep] <= order[step],
    );
  });
}

function closeOnboarding() {
  const overlay = $("#onboarding-overlay");
  if (!overlay) return;
  overlay.hidden = true;
  document.body.classList.remove("onboarding-open");
}

async function loadStatus() {
  const card = $("#auth-card");
  if (!card) return null;
  try {
    const status = await api("/api/status");
    if ($("#storage-path")) $("#storage-path").textContent = status.save_dir;
    if (card) {
      card.classList.remove("skeleton", "authorized", "warning");
      const title = $("strong", card);
      const reason = $("#auth-reason", card);
      const action = $("#open-onboarding");
      if (status.authenticated) {
        card.classList.add("authorized");
        const user = status.user || {};
        title.textContent = user.username
          ? `@${user.username}`
          : (user.phone || `ID ${user.id}`);
        action.textContent = "Настройки";
        action.dataset.action = "settings";
        if (reason) reason.textContent = "Локальная session активна.";
        closeOnboarding();
      } else {
        card.classList.add("warning");
        title.textContent = status.configured
          ? "Нужно войти в Telegram"
          : "Нужны api_id и api_hash";
        action.textContent = "Настроить";
        action.dataset.action = "onboarding";
        if (reason) reason.textContent = status.reason || "";
        showOnboardingStep(status.configured ? "telegram" : "credentials");
      }
    }
    return status;
  } catch (error) {
    if (card) {
      $("strong", card).textContent = "Не удалось проверить session";
      const reason = $("#auth-reason", card);
      if (reason) reason.textContent = error.message;
    }
  }
}

const openOnboardingButton = $("#open-onboarding");
if (openOnboardingButton) {
  openOnboardingButton.addEventListener("click", () => {
    if (openOnboardingButton.dataset.action === "settings") {
      location.href = "/settings";
      return;
    }
    const overlay = $("#onboarding-overlay");
    showOnboardingStep(overlay?.dataset.initialStep || "credentials");
  });
}

const credentialsForm = $("#credentials-form");
if (credentialsForm) {
  credentialsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(credentialsForm);
    busy(credentialsForm, true);
    message(credentialsForm, "Проверяем credentials через Telegram…");
    try {
      await api("/api/setup/credentials", {
        method: "POST",
        body: JSON.stringify({
          api_id: Number(data.get("api_id")),
          api_hash: data.get("api_hash"),
          session_name: data.get("session_name"),
        }),
      });
      message(credentialsForm, "Данные подтверждены.");
      showOnboardingStep("telegram");
    } catch (error) {
      message(credentialsForm, error.message, true);
    } finally {
      busy(credentialsForm, false);
    }
  });
}

const telegramLoginForm = $("#telegram-login-form");
if (telegramLoginForm) {
  const phoneInput = $("[name='phone']", telegramLoginForm);
  const passwordInput = $("[name='password']", telegramLoginForm);
  const codeInput = $("[name='code']", telegramLoginForm);
  const codeField = $("#code-field");
  const buttonLabel = $(".login-button-label", telegramLoginForm);
  const changePhoneButton = $("#change-phone");

  function setLoginMode(mode) {
    telegramLoginForm.dataset.mode = mode;
    const waitingForCode = mode === "complete-login";
    phoneInput.disabled = waitingForCode;
    codeInput.disabled = !waitingForCode;
    codeField.classList.toggle("unlocked", waitingForCode);
    codeField.classList.toggle("locked-field", !waitingForCode);
    buttonLabel.textContent = waitingForCode
      ? "Завершить вход"
      : "Проверить и отправить код";
    changePhoneButton.hidden = !waitingForCode;
    if (waitingForCode) {
      codeInput.placeholder = "Введите код";
      codeInput.focus();
    } else {
      codeInput.value = "";
      codeInput.placeholder = "Сначала запросите код";
    }
  }

  telegramLoginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    busy(telegramLoginForm, true);
    const mode = telegramLoginForm.dataset.mode;
    try {
      if (mode === "request-code") {
        message(telegramLoginForm, "Проверяем номер и запрашиваем код…");
        const result = await api("/api/setup/send-code", {
          method: "POST",
          body: JSON.stringify({ phone: phoneInput.value }),
        });
        if (result.state === "authorized") {
          showOnboardingStep("success");
        } else {
          setLoginMode("complete-login");
          message(telegramLoginForm, "Код отправлен в Telegram. Введите его ниже.");
        }
      } else {
        message(telegramLoginForm, "Проверяем код и создаём local session…");
        const result = await api("/api/setup/complete-login", {
          method: "POST",
          body: JSON.stringify({
            code: codeInput.value,
            password: passwordInput.value,
          }),
        });
        if (result.state === "2fa_required") {
          passwordInput.focus();
          message(
            telegramLoginForm,
            "Telegram запросил пароль 2FA. Введите его и повторите вход.",
            true,
          );
        } else {
          showOnboardingStep("success");
        }
      }
    } catch (error) {
      message(telegramLoginForm, error.message, true);
    } finally {
      busy(telegramLoginForm, false);
    }
  });

  changePhoneButton.addEventListener("click", () => {
    setLoginMode("request-code");
    phoneInput.disabled = false;
    phoneInput.focus();
    message(telegramLoginForm, "Введите номер заново.");
  });
}

const parseForm = $("#parse-form");
if (parseForm) {
  const urlInput = $("#telegram-url");
  urlInput.addEventListener("input", () => {
    const value = urlInput.value.trim().replace(/^https?:\/\//, "");
    const path = value.replace(/^(t\.me\/|@)/, "").split("/").filter(Boolean);
    const isPrivatePost = path[0] === "c" && path.length > 2;
    const isPublicPost = path[0] !== "c" && path.length > 1;
    $("#target-kind").textContent = (
      (isPrivatePost || isPublicPost) && /^\d+$/.test(path.at(-1))
    )
      ? "пост"
      : "канал";
  });
  parseForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    busy(parseForm, true);
    message(parseForm, "Считаем доступные публикации в Telegram…");
    try {
      const rawLimit = $("#parse-limit").value.trim();
      const payload = {
        url: urlInput.value,
        limit: rawLimit ? Number(rawLimit) : null,
        download_media: $("#download-media").checked,
      };
      const preview = await api("/api/parse/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!confirm(preview.confirmation)) {
        message(parseForm, "Запуск отменён. Данные не загружались.");
        busy(parseForm, false);
        return;
      }
      message(parseForm, "Создаём локальный запуск…");
      const result = await api("/api/parse", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      location.href = result.detail_url;
    } catch (error) {
      message(parseForm, error.message, true);
      busy(parseForm, false);
      if (error.message.includes("настройте") || error.message.includes("авторизуйте")) {
        showOnboardingStep(
          error.message.includes("api_id") ? "credentials" : "telegram",
        );
      }
    }
  });
}

$$("[data-export-media]").forEach((toggle) => {
  const panel = toggle.closest(".export-panel");
  const links = $$("[data-export-link]", panel);
  const exportMessage = $(".export-message", panel);
  const updateLinks = () => {
    links.forEach((link) => {
      const url = new URL(link.href);
      if (toggle.checked) {
        url.searchParams.set("include_media", "true");
      } else {
        url.searchParams.delete("include_media");
      }
      link.href = url.toString();
    });
  };
  links.forEach((link) => {
    link.addEventListener("click", async (event) => {
      if (!toggle.checked) return;
      event.preventDefault();
      if (exportMessage) {
        exportMessage.textContent = "Собираем ZIP с папкой media…";
        exportMessage.classList.remove("error-text");
      }
      try {
        const response = await fetch(link.href);
        const contentType = response.headers.get("Content-Type") || "";
        if (!response.ok) {
          const payload = contentType.includes("json")
            ? await response.json()
            : {};
          throw new Error(
            payload.detail ||
            `Экспорт не выполнен: HTTP ${response.status}.`,
          );
        }
        const blob = await response.blob();
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="([^"]+)"/);
        const filename = match?.[1] || "telegram_export.zip";
        const downloadUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = downloadUrl;
        anchor.download = filename;
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
        if (exportMessage) {
          exportMessage.textContent =
            "ZIP готов. Все файлы лежат в папке media.";
        }
      } catch (error) {
        if (exportMessage) {
          exportMessage.textContent = error.message;
          exportMessage.classList.add("error-text");
        }
      }
    });
  });
  toggle.addEventListener("change", updateLinks);
  updateLinks();
});

function bindJsonForm(selector, endpoint, payloadFactory, onSuccess) {
  const form = $(selector);
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    busy(form, true);
    message(form, "Сохраняем…");
    try {
      const result = await api(endpoint, {
        method: "POST",
        body: JSON.stringify(payloadFactory(new FormData(form))),
      });
      message(form, "Готово.");
      if (onSuccess) onSuccess(result);
    } catch (error) {
      message(form, error.message, true);
    } finally {
      busy(form, false);
    }
  });
}

bindJsonForm("#storage-form", "/api/settings/storage", (data) => ({
  save_dir: data.get("save_dir"),
}), (result) => {
  const path = $("#settings-storage-path");
  if (path) path.textContent = result.save_dir;
  showToast("Папка сохранена");
});

let privateSettings = null;
let allSecretsVisible = false;

function secretValue(data, key) {
  if (key === "username") {
    return data.user?.username ? `@${data.user.username}` : "не задан";
  }
  if (key === "phone") {
    return data.user?.phone ? `+${data.user.phone}` : "не задан";
  }
  return data[key] || "не задан";
}

async function getPrivateSettings() {
  if (!privateSettings) {
    privateSettings = await api("/api/settings/private", { method: "POST" });
  }
  return privateSettings;
}

function hideSecretRow(row) {
  const lengths = { api_hash: 16, phone: 10 };
  row.querySelector(".secret-content").textContent = "•".repeat(lengths[row.dataset.secretKey] || 8);
  row.classList.remove("revealed");
}

async function revealSecretRow(row) {
  try {
    const data = await getPrivateSettings();
    row.querySelector(".secret-content").textContent = secretValue(data, row.dataset.secretKey);
    row.classList.add("revealed");
  } catch (error) {
    $("#secrets-message").textContent = error.message;
    $("#secrets-message").classList.add("error-text");
  }
}

$$("[data-secret-key]").forEach((row) => {
  row.addEventListener("click", async () => {
    if (row.classList.contains("revealed")) {
      hideSecretRow(row);
    } else {
      await revealSecretRow(row);
    }
  });
});

const revealSecretsButton = $("#reveal-secrets");
if (revealSecretsButton) {
  revealSecretsButton.addEventListener("click", async () => {
    const rows = $$("[data-secret-key]");
    if (allSecretsVisible) {
      rows.forEach(hideSecretRow);
      allSecretsVisible = false;
      revealSecretsButton.textContent = "Увидеть данные";
      return;
    }
    await Promise.all(rows.map(revealSecretRow));
    allSecretsVisible = true;
    revealSecretsButton.textContent = "Скрыть данные";
  });
}

$$("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = $(button.dataset.copyTarget);
    try {
      await navigator.clipboard.writeText(target.textContent.trim());
      button.textContent = "Скопировано";
      setTimeout(() => { button.textContent = "Копировать"; }, 1800);
    } catch {
      showToast("Не удалось скопировать путь");
    }
  });
});

const resetButton = $("#reset-session");
if (resetButton) {
  resetButton.addEventListener("click", async () => {
    if (!confirm(
      "Отозвать этот вход в Telegram и удалить локальную session, api_id, api_hash, телефон и профиль? История парсинга и результаты останутся.",
    )) return;
    resetButton.disabled = true;
    try {
      const result = await api("/api/setup/reset", {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      privateSettings = null;
      $("#reset-message").textContent = result.message;
      showToast("Данные входа удалены");
      setTimeout(() => { location.href = "/"; }, 700);
    } catch (error) {
      $("#reset-message").textContent = error.message;
      $("#reset-message").classList.add("error-text");
    } finally {
      resetButton.disabled = false;
    }
  });
}

let runStateVersion = 0;

function renderRunState(run) {
  const head = $("[data-run-id]");
  if (!head) return;
  head.dataset.runStatus = run.status;
  const status = $("#run-status");
  status.textContent = run.status;
  status.className = `status-badge status-${run.status}`;
  $("#run-progress-text").textContent = `${run.processed_posts} / ${run.total_posts} постов`;
  $("#run-progress").style.width = `${run.total_posts ? (run.processed_posts / run.total_posts) * 100 : 0}%`;
  if ($("#run-eta")) $("#run-eta").textContent = run.estimated_wait_text;
  $("#run-posts").textContent = run.posts_count;
  $("#run-comments").textContent = run.comments_count;
  if ($("#run-media")) $("#run-media").textContent = run.media_files_count || 0;
  $("#run-error").textContent = run.error || "";
  if ($("#pause-run")) {
    $("#pause-run").hidden = !["queued", "running"].includes(run.status);
  }
  if ($("#resume-run")) {
    $("#resume-run").hidden = run.status !== "paused";
  }
}

async function changeRunState(action) {
  const head = $("[data-run-id]");
  if (!head) return;
  const button = action === "pause" ? $("#pause-run") : $("#resume-run");
  const controlMessage = $("#run-control-message");
  runStateVersion += 1;
  button.disabled = true;
  controlMessage.classList.remove("error-text");
  try {
    const run = await api(`/api/runs/${head.dataset.runId}/${action}`, {
      method: "POST",
    });
    renderRunState(run);
    controlMessage.textContent = action === "pause"
      ? "Парсинг приостановлен. Уже начатый запрос Telegram завершится безопасно."
      : "Парсинг продолжен с сохранённого места.";
  } catch (error) {
    controlMessage.textContent = error.message;
    controlMessage.classList.add("error-text");
  } finally {
    button.disabled = false;
  }
}

$("#pause-run")?.addEventListener("click", () => changeRunState("pause"));
$("#resume-run")?.addEventListener("click", () => changeRunState("resume"));

async function pollRun() {
  const head = $("[data-run-id]");
  if (!head) return;
  if (!["queued", "running", "paused"].includes(head.dataset.runStatus)) return;
  const runId = head.dataset.runId;
  const requestedVersion = runStateVersion;
  try {
    const run = await api(`/api/runs/${runId}`);
    if (requestedVersion !== runStateVersion) {
      setTimeout(pollRun, 250);
      return;
    }
    renderRunState(run);
    if (["queued", "running", "paused"].includes(run.status)) {
      setTimeout(pollRun, 1200);
    } else {
      location.reload();
    }
  } catch (error) {
    $("#run-error").textContent = error.message;
  }
}

const onboarding = $("#onboarding-overlay");
if (onboarding && !onboarding.hidden) {
  showOnboardingStep(onboarding.dataset.initialStep || "credentials");
}
loadStatus();
pollRun();
