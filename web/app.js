const $ = (id) => document.getElementById(id);
const state = { cities: null, health: null, abortController: null, queryId: null, cancelling: false, hasResults: false, validationAttempted: false, queryTimer: null, viewAnimation: null, lockedControls: [] };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const compactLayout = window.matchMedia("(max-width: 680px)");
const preferences = { cheapest: "最省钱", balanced: "更均衡", fastest: "最快到达" };
const motionEffects = new Map();
const pressWaves = new Map();

// Motion is presentation only: native controls and request state never wait for it.
function animateFeedback(element, frames, options = {}) {
  if (!element) return null;
  const previous = motionEffects.get(element);
  if (previous && options.fromCurrent !== false && typeof getComputedStyle === "function") {
    const current = getComputedStyle(element);
    frames = [{ ...frames[0], transform: current.transform, opacity: current.opacity }, ...frames.slice(1)];
  }
  previous?.cancel();
  motionEffects.delete(element);
  if (reducedMotion.matches || !element.animate) return null;
  const { fromCurrent, ...timing } = options;
  const effect = element.animate(frames, { duration: 280, easing: "cubic-bezier(.16,1,.3,1)", ...timing });
  motionEffects.set(element, effect);
  const cleanup = () => { if (motionEffects.get(element) === effect) motionEffects.delete(element); };
  effect.finished?.then(cleanup, cleanup);
  return effect;
}

function moveSelectionIndicator(container, active, indicator, animate = true) {
  if (!container?.getBoundingClientRect || !active || !indicator) return;
  // Read presentation bounds before cancelling; a second tap can retarget mid-motion.
  const parent = container.getBoundingClientRect();
  const target = active.getBoundingClientRect();
  if (!target.width || !target.height) return;
  const ready = container.classList.contains("has-indicator");
  const current = ready ? indicator.getBoundingClientRect() : target;
  const x = target.left - parent.left - container.clientLeft;
  const y = target.top - parent.top - container.clientTop;
  const transform = `translate(${x}px, ${y}px)`;
  motionEffects.get(indicator)?.cancel();
  motionEffects.delete(indicator);
  indicator.style.width = `${target.width}px`;
  indicator.style.height = `${target.height}px`;
  indicator.style.transform = transform;
  container.classList.add("has-indicator");
  if (animate && ready) animateFeedback(indicator, [
    { transform: `translate(${current.left - parent.left - container.clientLeft}px, ${current.top - parent.top - container.clientTop}px) scale(${current.width / target.width}, ${current.height / target.height})` },
    { transform },
  ], { duration: 340, fromCurrent: false });
}

function updateSelectionIndicators(animate = true) {
  const nav = $("page-nav");
  moveSelectionIndicator(nav, nav?.querySelector(".is-active"), $("nav-indicator"), animate);
  const choices = $("preference-choices");
  moveSelectionIndicator(choices, choices?.querySelector("input:checked")?.closest?.(".choice"), $("preference-indicator"), animate);
}

function setPreviewText(id, text, animate) {
  const element = $(id);
  if (element.textContent === text) return;
  element.textContent = text;
  if (animate === true) animateFeedback(element, [
    { opacity: .55, transform: "translateY(5px)" },
    { opacity: 1, transform: "translateY(0)" },
  ], { duration: 240 });
}

function showPressWave(button, point) {
  if (reducedMotion.matches || button.disabled) return;
  const oldWave = pressWaves.get(button);
  if (oldWave) { motionEffects.get(oldWave)?.cancel(); oldWave.remove(); }
  const rect = button.getBoundingClientRect();
  const x = point ? point.clientX - rect.left : rect.width / 2;
  const y = point ? point.clientY - rect.top : rect.height / 2;
  const radius = Math.max(Math.hypot(x, y), Math.hypot(rect.width - x, y), Math.hypot(x, rect.height - y), Math.hypot(rect.width - x, rect.height - y));
  const wave = document.createElement("span");
  wave.className = "press-wave";
  wave.setAttribute("aria-hidden", "true");
  Object.assign(wave.style, { width: `${radius * 2}px`, height: `${radius * 2}px`, left: `${x - radius}px`, top: `${y - radius}px` });
  button.append(wave);
  pressWaves.set(button, wave);
  const effect = animateFeedback(wave, [{ opacity: .18, transform: "scale(0)" }, { opacity: 0, transform: "scale(1)" }], { duration: 440, easing: "cubic-bezier(.2,.7,.3,1)" });
  const cleanup = () => { wave.remove(); if (pressWaves.get(button) === wave) pressWaves.delete(button); };
  if (effect?.finished) effect.finished.then(cleanup, cleanup);
  else cleanup();
}

function initializeInteractions() {
  const buttonFrom = (event) => event.target.closest?.(".primary-button, .secondary-button, .swap-button, .nav-item");
  document.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const button = buttonFrom(event);
    if (button) showPressWave(button, event);
  });
  document.addEventListener("keydown", (event) => {
    if (event.repeat || !["Enter", " "].includes(event.key)) return;
    const button = buttonFrom(event);
    if (button) showPressWave(button);
  });
  document.querySelectorAll(".choice > input").forEach((input) => input.addEventListener("change", () => {
    const icon = input.nextElementSibling.querySelector(".icon:not(.choice-check)");
    if (input.checked) animateFeedback(icon, [{ transform: "translateY(3px) scale(.85)" }, { transform: "translateY(0) scale(1)" }], { duration: 260 });
    updateSelectionIndicators();
  }));
  updateSelectionIndicators(false);
  if (typeof ResizeObserver === "function") {
    const observer = new ResizeObserver(() => updateSelectionIndicators(false));
    observer.observe($("page-nav"));
    observer.observe($("preference-choices"));
  }
}

function localDate(offsetDays) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function setView(name) {
  const showResults = name === "results";
  $("planning-view").hidden = showResults;
  $("results-view").hidden = !showResults;
  $("nav-planning").classList.toggle("is-active", !showResults);
  $("nav-results").classList.toggle("is-active", showResults);
  for (const [id, active] of [["nav-planning", !showResults], ["nav-results", showResults]]) {
    if (active) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
  updateSelectionIndicators();
  state.viewAnimation?.cancel();
  const view = $(showResults ? "results-view" : "planning-view");
  if (!reducedMotion.matches) {
    state.viewAnimation = view.animate([
      { opacity: 0, transform: `translateX(${showResults ? 12 : -12}px)` },
      { opacity: 1, transform: "translateX(0)" },
    ], { duration: 320, easing: "cubic-bezier(.2,.8,.2,1)" });
  }
  document.title = `行价比 · ${showResults ? "出行方案" : "出行规划"}`;
  $(showResults ? "results-title" : "planning-title").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: reducedMotion.matches ? "instant" : "smooth" });
}

function setSourceStatus(label, kind = "") {
  $("source-label").textContent = label;
  $("source-indicator").className = `source-indicator ${kind}`.trim();
}

function setFormMessage(message, kind = "error") {
  $("form-message").textContent = message;
  $("form-message").classList.toggle("is-info", kind === "info");
  $("form-message").setAttribute("role", kind === "info" ? "status" : "alert");
}

function shortDate(value) {
  if (!value) return "待选择日期";
  const [, month, day] = value.split("-");
  return `${Number(month)}月${Number(day)}日`;
}

function updatePreview(animate = false) {
  for (const id of ["origin", "destination"]) {
    const isLong = $(id).value.trim().length > 3;
    $(id).classList.toggle("is-long", isLong);
    $(`preview-${id}`).classList.toggle("is-long", isLong);
  }
  setPreviewText("preview-origin", $("origin").value.trim() || "待选择", animate);
  setPreviewText("preview-destination", $("destination").value.trim() || "待选择", animate);
  setPreviewText("preview-type", $("round-trip").checked ? "往返" : "单程", animate);
  setPreviewText("preview-outbound", `${shortDate($("outbound-date").value)} · ${$("outbound-start").value || "—"}–${$("outbound-end").value || "—"}`, animate);
  setPreviewText("preview-return", `${shortDate($("return-date").value)} · ${$("return-start").value || "—"}–${$("return-end").value || "—"}`, animate);
  $("preview-return-row").hidden = !$("round-trip").checked;
  const modes = [$("mode-train").checked ? "火车" : "", $("mode-flight").checked ? "飞机" : ""].filter(Boolean);
  setPreviewText("preview-modes", modes.join(" + ") || "待选择", animate);
  setPreviewText("preview-preference", preferences[document.querySelector('input[name="preference"]:checked')?.value] || "更均衡", animate);
  setPreviewText("preview-budget", $("budget").value ? money($("budget").value) : "不限预算", animate);
  const vehicle = $("route-vehicle-use");
  const icon = $("mode-flight").checked ? "#icon-plane" : "#icon-train";
  if (vehicle.getAttribute("href") !== icon) {
    vehicle.setAttribute("href", icon);
    $("route-vehicle-heading").setAttribute("transform", icon === "#icon-plane" ? "rotate(90)" : "rotate(0)");
    if (animate === true) animateFeedback($("route-vehicle"), [{ opacity: .5, transform: "translateX(-8px)" }, { opacity: 1, transform: "translateX(0)" }]);
  }
  $("route-vehicle").setAttribute("visibility", modes.length ? "visible" : "hidden");
}

function updateRoundTrip(animate = false) {
  const roundTrip = $("round-trip").checked;
  $("return-card").classList.toggle("is-disabled", !roundTrip);
  $("return-note").textContent = roundTrip ? "往返行程" : "单程 · 无需填写";
  for (const id of ["return-date", "return-start", "return-end"]) {
    $(id).disabled = !roundTrip;
  }
  if (!roundTrip) $("dorm-enabled").checked = false;
  $("dorm-enabled").disabled = !roundTrip;
  updateDormTime();
  updatePreview(animate);
}

function updateDormTime() {
  $("dorm-time").disabled = !$("dorm-enabled").checked || !$("round-trip").checked;
}

function updateAccommodation() {
  $("accommodation-cost").disabled = !$("accommodation").checked;
}

function combineDateTime(date, time) {
  return `${date}T${time}:00`;
}

function validateAndBuildRequest() {
  const errors = [];
  const addError = (id, message) => errors.push({ id, message });
  const origin = $("origin").value.trim().replace(/市$/, "");
  const destination = $("destination").value.trim().replace(/市$/, "");
  for (const [id, city] of [["origin", origin], ["destination", destination]]) {
    if (!city) addError(id, id === "origin" ? "请选择出发地。" : "请选择目的地。");
    else if (state.cities && !state.cities.has(city)) addError(id, "请从列表选择已收录的中国大陆城市。");
  }
  if (origin && origin === destination) addError("destination", "目的地不能与出发地相同。");

  const outboundDate = $("outbound-date").value;
  const outboundStart = $("outbound-start").value;
  const outboundEnd = $("outbound-end").value;
  for (const [id, value, name] of [["outbound-date", outboundDate, "去程日期"], ["outbound-start", outboundStart, "最早出发时间"], ["outbound-end", outboundEnd, "最晚出发时间"]]) {
    if (!value) addError(id, `请填写${name}。`);
  }
  const outboundAfter = combineDateTime(outboundDate, outboundStart);
  const outboundBefore = combineDateTime(outboundDate, outboundEnd);
  if (outboundStart && outboundEnd && outboundAfter >= outboundBefore) addError("outbound-end", "最晚出发时间需晚于最早出发时间。");

  let returnAfter = null;
  let returnBefore = null;
  if ($("round-trip").checked) {
    const returnDate = $("return-date").value;
    const returnStart = $("return-start").value;
    const returnEnd = $("return-end").value;
    for (const [id, value, name] of [["return-date", returnDate, "返程日期"], ["return-start", returnStart, "返程最早出发时间"], ["return-end", returnEnd, "返程最晚出发时间"]]) {
      if (!value) addError(id, `请填写${name}。`);
    }
    returnAfter = combineDateTime(returnDate, returnStart);
    returnBefore = combineDateTime(returnDate, returnEnd);
    if (returnStart && returnEnd && returnAfter >= returnBefore) addError("return-end", "返程最晚出发时间需晚于最早出发时间。");
    if (returnDate && returnStart && outboundDate && returnAfter <= outboundAfter) addError("return-date", "返程需晚于去程出发时间。");
  }

  const allowedModes = ["train", "flight"].filter((mode) => $(`mode-${mode}`).checked);
  if (!allowedModes.length) addError("mode-train", "请至少选择一种交通方式。");
  const budgetRaw = $("budget").value;
  const budget = budgetRaw === "" ? null : Number(budgetRaw);
  if (budget !== null && (!Number.isFinite(budget) || budget <= 0 || !$("budget").validity.valid)) addError("budget", "总预算需填写大于 0 的整数，或留空不限。 ");
  const accommodationCost = $("accommodation").checked ? Number($("accommodation-cost").value) : 0;
  if ($("accommodation").checked && (!Number.isFinite(accommodationCost) || accommodationCost < 0 || !$("accommodation-cost").validity.valid)) addError("accommodation-cost", "住宿估算需填写不小于 0 的整数。");
  if ($("dorm-enabled").checked && !$("dorm-time").value) addError("dorm-time", "请填写返校门禁时间。");
  if (errors.length) throw Object.assign(new Error("请检查行程条件。"), { fields: errors });

  return {
    origin,
    destination,
    outbound_after: outboundAfter,
    outbound_before: outboundBefore,
    return_after: returnAfter,
    return_before: returnBefore,
    allowed_modes: allowedModes,
    preference: document.querySelector('input[name="preference"]:checked').value,
    budget,
    max_transfers: 0,
    dorm_deadline: $("dorm-enabled").checked && returnAfter
      ? combineDateTime($("return-date").value, $("dorm-time").value)
      : null,
    include_accommodation: $("accommodation").checked,
    accommodation_cost: accommodationCost,
  };
}

function showFieldErrors(errors, updateSummary = false) {
  for (const input of document.querySelectorAll('[aria-describedby$="-error"]')) {
    const matches = errors.filter((error) => error.id === input.id);
    const message = matches.map((error) => error.message).join(" ");
    $(input.getAttribute("aria-describedby")).textContent = message;
    if (message) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }
  if (!updateSummary) return;
  $("error-summary").hidden = !errors.length;
  $("error-summary").innerHTML = errors.length ? `<h2>请检查以下 ${errors.length} 项条件</h2><ul>${errors.map((error) => `<li><a href="#${error.id}">${escapeHtml(error.message)}</a></li>`).join("")}</ul>` : "";
}

function setQueryBusy(busy) {
  $("trip-preview").classList.toggle("is-querying", busy);
  $("submit-button").classList.toggle("is-loading", busy);
  $("submit-button").querySelector("span").textContent = busy ? "取消查询" : "搜索出行方案";
  $("query-status").hidden = !busy;
  $("nav-planning").disabled = busy;
  $("nav-results").disabled = busy || !state.hasResults;
  if (busy) {
    state.lockedControls = [...document.querySelectorAll('#plan-form input, #swap-cities')].map((control) => [control, control.disabled]);
    for (const [control] of state.lockedControls) control.disabled = true;
    const started = Date.now();
    $("query-elapsed").textContent = "已等待 0 秒 · 可随时取消";
    state.queryTimer = setInterval(() => {
      $("query-elapsed").textContent = `已等待 ${Math.floor((Date.now() - started) / 1000)} 秒 · 可随时取消`;
    }, 1000);
  } else {
    for (const [control, wasDisabled] of state.lockedControls) control.disabled = wasDisabled;
    state.lockedControls = [];
    clearInterval(state.queryTimer);
    state.queryTimer = null;
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function money(value) {
  return `¥${Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
}

function duration(minutes) {
  const hours = Math.floor(Number(minutes || 0) / 60);
  const rest = Number(minutes || 0) % 60;
  return hours ? `${hours}小时${rest ? `${rest}分` : ""}` : `${rest}分钟`;
}

function segmentHtml(segment) {
  const mode = segment.mode === "flight" ? "飞机" : "火车";
  const icon = segment.mode === "flight" ? "icon-plane" : "icon-train";
  const departureTime = String(segment.departure_at || "").split("T")[1]?.slice(0, 5) || "待确认";
  const arrivalTime = String(segment.arrival_at || "").split("T")[1]?.slice(0, 5) || "待确认";
  const minutes = segment.duration_minutes ?? Math.round((new Date(segment.arrival_at) - new Date(segment.departure_at)) / 60000);
  return `<div class="segment">
    <div class="segment-meta"><svg class="icon" aria-hidden="true"><use href="#${icon}" /></svg><strong>${escapeHtml(mode)} ${escapeHtml(segment.number)}</strong><span>${escapeHtml(segment.seat_or_cabin)}</span><strong class="segment-price">${money(segment.price)}</strong></div>
    <div class="segment-timeline">
      <div class="segment-endpoint"><div class="segment-date">${escapeHtml(shortDate(String(segment.departure_at).split("T")[0]))} 出发</div><div class="segment-time">${escapeHtml(departureTime)}</div><div class="segment-station">${escapeHtml(segment.departure_station || segment.origin)}</div></div>
      <div class="segment-duration">${escapeHtml(duration(minutes))}<span class="segment-track" aria-hidden="true"></span><span>直达</span></div>
      <div class="segment-endpoint"><div class="segment-date">${escapeHtml(shortDate(String(segment.arrival_at).split("T")[0]))} 到达</div><div class="segment-time">${escapeHtml(arrivalTime)}</div><div class="segment-station">${escapeHtml(segment.arrival_station || segment.destination)}</div></div>
    </div>
  </div>`;
}

function journeyHtml(title, segments) {
  if (!segments?.length) return "";
  return `<div class="journey-block"><h3 class="journey-title">${title}</h3>${segments.map(segmentHtml).join("")}</div>`;
}

function resultHtml(plan, index, request, recommended) {
  const warnings = (plan.warnings || []).map((warning) => `<span class="risk"><svg class="icon" aria-hidden="true"><use href="#icon-warning" /></svg>${escapeHtml(warning)}</span>`).join("");
  const modes = [...new Set([...(plan.outbound || []), ...(plan.inbound || [])].map((segment) => segment.mode === "flight" ? "飞机" : "火车"))];
  const priceDelta = plan.total_cost - recommended.total_cost;
  const timeDelta = plan.total_duration_minutes - recommended.total_duration_minutes;
  const comparison = index > 0 ? [
    priceDelta === 0 ? "与推荐同价" : `较推荐${priceDelta < 0 ? "省" : "多花"} ${money(Math.abs(priceDelta))}`,
    timeDelta === 0 ? "耗时相同" : `${timeDelta < 0 ? "少" : "多"}耗时 ${duration(Math.abs(timeDelta))}`,
  ].join(" · ") : "";
  return `<article class="surface result-card ${index === 0 ? "is-recommended" : ""}">
    <div class="result-top">
      <div><span class="result-rank">${index === 0 ? '<svg class="icon" aria-hidden="true"><use href="#icon-check" /></svg>优先推荐' : `备选方案 0${index + 1}`}</span><h3 class="result-name">${escapeHtml(modes.join(" + "))} · ${request.return_after ? "往返" : "单程"}</h3></div>
      <div class="result-stats"><span>总成本</span><strong class="price">${money(plan.total_cost)}</strong><span>交通总耗时 <strong>${escapeHtml(duration(plan.total_duration_minutes))}</strong></span></div>
    </div>
    <div class="journey-grid">${journeyHtml("去程", plan.outbound)}${journeyHtml("返程", plan.inbound)}</div>
    ${comparison ? `<p class="comparison-note">${escapeHtml(comparison)}</p>` : ""}
    <div class="result-bottom">
      <span>票价 <strong>${money(plan.ticket_cost)}</strong></span>
      <span>住宿 <strong>${money(plan.accommodation_cost)}</strong></span>
      <span>市内换乘 <strong>${money(plan.local_transfer_cost)}</strong></span>
      ${warnings}
    </div>
  </article>`;
}

function sourceName(mode) {
  return mode === "train" ? "12306 火车" : mode === "flight" ? "国内航班" : mode;
}

function sourceErrorText(mode, message) {
  if (mode === "flight" && state.health?.flight_browser_engine === "safari") {
    if (/CONTENT_NOT_READY|未取得可核实|验证|登录/.test(message)) return "机票来源尚未返回可核实的数据，请确认 Safari 中携程已登录，或完成页面验证后重试";
    if (/授权|Apple|osascript|控制 Safari/i.test(message)) return "机票来源未完成 Safari 页面读取，请检查本机 Safari 自动化授权后重试";
    return "机票来源暂时未返回结果，请稍后重试；原始错误可在来源诊断中查看";
  }
  if (/WhaleGuard|反爬|拦截/.test(message)) {
    return `${sourceName(mode)}暂不可用：携程拦截了当前查询，尚未取得机票价格`;
  }
  if (/验证码|验证|登录/.test(message)) {
    return `${sourceName(mode)}暂不可用：请在弹出的携程窗口完成人工验证或登录，再重新查询`;
  }
  return `${sourceName(mode)}暂不可用：${message}`;
}

function renderFlights(data, request) {
  const selected = request.allowed_modes.includes("flight");
  const failed = Boolean(data.source_errors?.flight);
  const box = $("flight-results");
  const outbound = data.flights?.outbound || [];
  const inbound = data.flights?.inbound || [];
  const count = outbound.length + inbound.length;
  box.hidden = !selected || (failed && count === 0);
  if (box.hidden) return;
  $("flight-results-source").textContent = data.data_mode === "demo"
    ? "演示数据 · 非实时票价"
    : data.flight_browser_engine === "safari"
      ? "携程 · Safari 已加载航班 · 本次查询"
      : "携程公开页面 · 本次实时查询";
  $("flight-results-title").textContent = "航班列表";
  $("flight-results-count").textContent = `${count} 班`;
  box.open = false;
  $("flight-results-list").innerHTML = count
    ? `${journeyHtml("去程航班", outbound)}${journeyHtml("返程航班", inbound)}`
    : `<p class="flight-results-empty">所选日期和时间段没有获取到航班；这不代表其他时段无票。</p>`;
}

function renderResults(data, request) {
  state.hasResults = true;
  $("nav-results").disabled = false;
  $("nav-count").hidden = false;
  $("nav-count").textContent = String(data.plans.length);
  $("nav-results").title = "查看本次搜索的出行方案";
  $("result-subtitle").textContent = `${request.origin} → ${request.destination} · ${shortDate(request.outbound_after.split("T")[0])}${request.return_after ? ` — ${shortDate(request.return_after.split("T")[0])} · 往返` : " · 单程"}`;
  $("recommendation-note").textContent = `${preferences[request.preference]}优先 · ${data.plans.length} 个方案`;
  const errors = Object.entries(data.source_errors || {});
  if (errors.length) {
    setSourceStatus("部分票务来源不可用", "is-error");
  } else if (data.data_mode === "demo") {
    setSourceStatus("演示数据 · 非实时票价", "is-demo");
  } else {
    setSourceStatus("实时票务 · 价格仅供参考", "is-live");
  }
  $("results-message").innerHTML = [
    data.data_mode === "demo" ? '<div class="notice"><svg class="icon" aria-hidden="true"><use href="#icon-info" /></svg><span>当前为演示数据，用于验证搜索流程与界面，不是实时票价。</span></div>' : "",
    errors.length ? `<div class="notice"><svg class="icon" aria-hidden="true"><use href="#icon-warning" /></svg><div><span>${errors.map(([mode, message]) => escapeHtml(sourceErrorText(mode, message))).join("；")}。以下仅展示已成功查询的${data.data_mode === "demo" ? "演示" : "真实来源"}结果。</span><details class="source-diagnostics"><summary>查看来源诊断</summary>${errors.map(([mode, message]) => `<p><strong>${escapeHtml(sourceName(mode))}</strong> · ${escapeHtml(message)}</p>`).join("")}</details></div></div>` : "",
  ].join("");
  $("results-overview").hidden = !data.plans.length;
  if (data.plans.length) {
    const lowest = Math.min(...data.plans.map((plan) => plan.total_cost));
    const fastest = Math.min(...data.plans.map((plan) => plan.total_duration_minutes));
    const obtainedModes = [...new Set(data.plans.flatMap((plan) => [...(plan.outbound || []), ...(plan.inbound || [])]).map((segment) => segment.mode === "train" ? "火车" : "飞机"))];
    $("results-overview").innerHTML = `<div class="overview-cell"><span>本次行程</span><strong>${escapeHtml(request.origin)} ${request.return_after ? "⇄" : "→"} ${escapeHtml(request.destination)}</strong><p>${obtainedModes.join(" / ")} · 直达方案</p></div><div class="overview-cell"><span>所获方案最低总价</span><strong>${money(lowest)}</strong></div><div class="overview-cell"><span>所获方案最短交通耗时</span><strong>${escapeHtml(duration(fastest))}</strong></div>`;
  }
  renderFlights(data, request);
  $("result-list").innerHTML = data.plans.length
    ? data.plans.map((plan, index) => resultHtml(plan, index, request, data.plans[0])).join("")
    : `<div class="surface empty-state"><svg class="icon" aria-hidden="true"><use href="#icon-list" /></svg><h3>没有找到符合条件的方案</h3><p>试试放宽预算、出发时间，或选择另一种交通方式。</p><button type="button" class="secondary-button" id="empty-edit-search">调整搜索条件</button></div>`;
  $("empty-edit-search")?.addEventListener("click", () => setView("planning"));
  const sources = [...new Set([
    ...data.plans.flatMap((plan) => [...(plan.outbound || []), ...(plan.inbound || [])]),
    ...(data.flights?.outbound || []),
    ...(data.flights?.inbound || []),
  ].map((segment) => segment.source).filter(Boolean))];
  const queryTime = data.queried_at ? new Date(data.queried_at).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" }) : "";
  $("result-footnote").textContent = `数据来源：${sources.join("、") || "无"} · 查询时间：${queryTime || "未知"} · 票价与余票可能变化，请以购票平台实时信息为准。`;
  setView("results");
}

async function search(event) {
  event.preventDefault();
  if (state.abortController) {
    if (state.cancelling) return;
    state.cancelling = true;
    $("submit-button").disabled = true;
    $("submit-button").querySelector("span").textContent = "正在取消…";
    const controller = state.abortController;
    try {
      const response = await fetch("/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query_id: state.queryId }),
      });
      if (!response.ok) throw new Error("后端未确认取消，请稍后重试");
      controller.abort();
    } catch (error) {
      setFormMessage(`取消未完成：${error.message}`);
    } finally {
      state.cancelling = false;
      $("submit-button").disabled = false;
      $("submit-button").querySelector("span").textContent = state.abortController ? "取消查询" : "搜索出行方案";
    }
    return;
  }
  let request;
  state.validationAttempted = true;
  try {
    request = validateAndBuildRequest();
    showFieldErrors([], true);
  } catch (error) {
    showFieldErrors(error.fields || [], true);
    $("error-summary").focus();
    return;
  }
  const controller = new AbortController();
  state.abortController = controller;
  state.queryId = crypto.randomUUID();
  request.query_id = state.queryId;
  setQueryBusy(true);
  setFormMessage(state.health?.data_mode === "demo" ? "正在读取演示数据，不会查询实时票价。" : request.allowed_modes.includes("flight")
    ? state.health?.flight_browser_engine === "safari"
      ? "正在读取 Safari 携程页面；请保留查询标签页，如有验证请手动完成。可随时取消。"
      : "正在实时读取携程航班页面；如弹出验证或登录窗口，请手动完成。可随时取消。"
    : "正在查询票务来源，可随时取消。", "info");
  try {
    const response = await fetch("/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) {
      const sourceDetails = Object.entries(data.source_errors || {}).map(([mode, message]) => sourceErrorText(mode, message)).join("；");
      if (response.status === 503) setSourceStatus("票务来源暂不可用", "is-error");
      throw new Error([data.message || "查询失败", sourceDetails].filter(Boolean).join("。"));
    }
    setFormMessage("");
    renderResults(data, request);
  } catch (error) {
    setFormMessage(error.name === "AbortError" ? "已取消查询，后端正在释放本次查询资源。" : `查询未完成：${error.message}`, error.name === "AbortError" ? "info" : "error");
    $("form-message").focus({ preventScroll: true });
  } finally {
    state.abortController = null;
    state.queryId = null;
    setQueryBusy(false);
  }
}

async function initialize() {
  $("origin").value = "上海";
  $("destination").value = "北京";
  $("outbound-date").value = localDate(2);
  $("outbound-start").value = "06:00";
  $("outbound-end").value = "12:00";
  $("return-date").value = localDate(4);
  $("return-start").value = "16:00";
  $("return-end").value = "22:30";
  $("nav-results").disabled = true;
  $("trip-preview").open = !compactLayout.matches;
  updateRoundTrip();
  updateAccommodation();
  initializeInteractions();

  $("plan-form").addEventListener("submit", search);
  $("plan-form").addEventListener("input", (event) => {
    if (!["checkbox", "radio"].includes(event.target.type)) updatePreview();
  });
  $("plan-form").addEventListener("change", () => {
    updatePreview(true);
    if (state.validationAttempted && !state.abortController) {
      let errors = [];
      try { validateAndBuildRequest(); } catch (error) { errors = error.fields || []; }
      showFieldErrors(errors, true);
    }
  });
  $("plan-form").addEventListener("focusout", (event) => {
    if (!event.target.matches("input") || state.abortController) return;
    let errors = [];
    try { validateAndBuildRequest(); } catch (error) { errors = error.fields || []; }
    if (!state.validationAttempted) {
      errors = errors.filter((error) => error.id === event.target.id || $(error.id).hasAttribute("aria-invalid"));
    }
    showFieldErrors(errors, state.validationAttempted);
  });
  $("error-summary").addEventListener("click", (event) => {
    const link = event.target.closest("a");
    if (!link) return;
    event.preventDefault();
    const target = $(link.hash.slice(1));
    const details = target.closest("details");
    if (details) details.open = true;
    target.focus();
  });
  $("swap-cities").addEventListener("click", () => {
    const origin = $("origin").value;
    $("origin").value = $("destination").value;
    $("destination").value = origin;
    $("swap-cities").classList.toggle("is-swapped");
    for (const [id, direction] of [["origin", 1], ["destination", -1]]) animateFeedback($(id), [{ opacity: .6, transform: `translateX(${direction * 8}px)` }, { opacity: 1, transform: "translateX(0)" }]);
    updatePreview(true);
    animateFeedback($("route-vehicle"), [{ opacity: .55, transform: "translateX(-12px)" }, { opacity: 1, transform: "translateX(0)" }]);
  });
  $("round-trip").addEventListener("change", () => updateRoundTrip(true));
  $("dorm-enabled").addEventListener("change", updateDormTime);
  $("accommodation").addEventListener("change", updateAccommodation);
  $("nav-planning").addEventListener("click", () => setView("planning"));
  $("nav-results").addEventListener("click", () => state.hasResults && setView("results"));
  $("edit-search").addEventListener("click", () => setView("planning"));

  try {
    const [healthResponse, cityResponse] = await Promise.all([fetch("/health"), fetch("/cities")]);
    if (!healthResponse.ok || !cityResponse.ok) throw new Error("票务服务状态不可用");
    state.health = await healthResponse.json();
    const cityData = await cityResponse.json();
    state.cities = new Set(cityData.cities || []);
    $("city-list").replaceChildren(...[...state.cities].map((city) => {
      const option = document.createElement("option");
      option.value = city;
      return option;
    }));
    const demo = state.health.data_mode === "demo";
    const modes = new Set(state.health.available_modes || []);
    for (const mode of ["train", "flight"]) {
      $(`mode-${mode}`).disabled = !modes.has(mode);
      $(`mode-${mode}`).checked = modes.has(mode);
    }
    if (demo) {
      $("outbound-date").value = "2026-10-01";
      $("return-date").value = "2026-10-03";
      setSourceStatus("演示数据 · 非实时票价", "is-demo");
    } else {
      setSourceStatus("实时票务 · 价格仅供参考", "is-live");
    }
    updatePreview();
  } catch (error) {
    setSourceStatus("票务服务连接异常", "is-error");
    setFormMessage("无法确认票务服务状态，请刷新页面重试。");
  }
}

initialize();
reducedMotion.addEventListener("change", () => {
  if (reducedMotion.matches) {
    state.viewAnimation?.cancel();
    for (const effect of motionEffects.values()) effect.cancel();
    motionEffects.clear();
    for (const wave of pressWaves.values()) wave.remove();
    pressWaves.clear();
  }
});
compactLayout.addEventListener("change", (event) => { $("trip-preview").open = !event.matches; });
