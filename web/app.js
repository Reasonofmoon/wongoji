/* 원고지 첨삭기 — 교사 화면.
   칸 좌표는 서버 SVG가 진실이다. 브라우저는 상태와 입력만 담당한다. */
(function () {
  "use strict";
  var S = { svg: null, data: null, sel: null, hidden: {}, focus: [] };
  var FOCUS_KINDS = [
    ["space", "띄움표"], ["join", "붙임표"], ["insert", "넣음표"],
    ["punct", "부호 넣음표"], ["delete", "뺌표"], ["replace", "고침표"],
    ["swap", "자리 바꿈표"], ["newline", "줄 바꿈표"], ["joinline", "줄 이음표"],
    ["indent", "들여쓰기표"], ["outdent", "내어쓰기표"],
    ["up", "끌어 올림표"], ["down", "끌어 내림표"]
  ];
  var SAMPLES = {
    elem: "어제 나는 친구와같이 놀이 터에서 놀았다. 그런데 갑자기 비 왔다 그래서 우리는 집으로 뛰어갔다. 아주 정말 재미있었다",
    mid: "나는 교복을 자유화해야 한다고 생각한다. 왜냐하면 교복은 불편하고 활동하기 어렵다. 그리고 개성을 표현할수 없다. 물론 교복을 입으면 옷을 고민 안해도 된다는 장점도 있다 하지만 나는 자유가 더 중요하다고 본다."
  };
  var CATALOG = null;
  var $ = function (id) { return document.getElementById(id); };

  function overlay(on, text) {
    var el = $("overlay");
    if (!el) return;
    el.classList.toggle("hidden", !on);
    if (text) $("overlay-text").textContent = text;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function showView(name) {
    $("view-compose").classList.toggle("on", name === "compose");
    $("view-review").classList.toggle("on", name === "review");
    $("to-compose").classList.toggle("hidden", name === "compose");
  }

  /* ---------------------------------------------------------------- 초기화 */
  function boot(payload) {
    S.svg = payload.svg;
    S.data = payload.data;
    S.gate = payload.gate || [];
    if (!S.data.review) S.data.review = {};
    $("sheetwrap").innerHTML = S.svg;
    S.data.corrections.forEach(function (c) { if (!c.state) c.state = "pending"; });
    bindSheet();
    renderChips();
    renderItems();
    renderGate();
    renderReview();
    updateState();
    showView("review");
  }

  function bindSheet() {
    Array.prototype.forEach.call(document.querySelectorAll(".mk"), function (g) {
      g.addEventListener("click", function () { select(+g.dataset.n, true); });
    });
  }

  /* ---------------------------------------------------------------- 목록 */
  function itemHTML(c) {
    var src = c.source === "rule" ? "규칙" : "LLM";
    var tgt = c.target ? '<span class="tgt">' + esc(c.target) + "</span>" : "";
    var to = c.text ? ' → <span class="tgt">' + esc(c.text) + "</span>" : "";
    return '<li class="item" data-n="' + c.n + '" data-state="' + c.state + '">' +
      '<div class="hd"><span class="num">' + c.n + "</span>" +
      '<span class="kind">' + esc(c.label) + "</span>" +
      '<span class="badge ' + c.source + '">' + src + "</span>" +
      '<span class="badge">' + esc(c.layer) + "</span></div>" +
      '<p class="why">' + tgt + to + " · " + esc(c.reason) + "</p>" +
      '<div class="acts">' +
      '<button class="btn sm act" data-a="approved" type="button">승인</button>' +
      '<button class="btn sm act" data-a="edit" type="button">수정</button>' +
      '<button class="btn sm act" data-a="rejected" type="button">기각</button></div>' +
      "</li>";
  }

  function renderItems() {
    var box = $("items");
    box.innerHTML = S.data.corrections.map(itemHTML).join("");
    $("cnt-items").textContent = S.data.corrections.length;
    Array.prototype.forEach.call(box.querySelectorAll(".item"), function (li) {
      var n = +li.dataset.n;
      li.addEventListener("click", function (e) {
        if (e.target.classList.contains("act")) return;
        select(n, false);
      });
      Array.prototype.forEach.call(li.querySelectorAll(".act"), function (b) {
        b.addEventListener("click", function (e) {
          e.stopPropagation();
          if (b.dataset.a === "edit") openEdit(li, n);
          else setState(n, b.dataset.a);
        });
      });
    });
    paintButtons();
  }

  function paintButtons() {
    Array.prototype.forEach.call($("items").querySelectorAll(".item"), function (li) {
      var c = find(+li.dataset.n);
      li.dataset.state = c.state;
      Array.prototype.forEach.call(li.querySelectorAll(".act"), function (b) {
        b.classList.remove("on-ok", "on-no");
        if (b.dataset.a === "approved" && c.state === "approved") b.classList.add("on-ok");
        if (b.dataset.a === "rejected" && c.state === "rejected") b.classList.add("on-no");
      });
    });
  }

  function openEdit(li, n) {
    if (li.querySelector(".edit-row")) return;
    var c = find(n);
    var wrap = document.createElement("div");
    wrap.className = "edit-row";
    wrap.addEventListener("click", function (e) { e.stopPropagation(); });
    var needsText = c.kind === "insert" || c.kind === "punct" || c.kind === "replace";
    wrap.innerHTML =
      '<label>사유<textarea class="edit" id="ed-reason-' + n + '" rows="3">' +
        esc(c.reason || "") + "</textarea></label>" +
      (needsText
        ? '<label>대체·넣을 글자<input class="edit" id="ed-text-' + n + '" value="' +
          esc(c.text || "") + '"></label>'
        : "");
    wrap.addEventListener("change", function () {
      c.reason = $("ed-reason-" + n).value;
      if (needsText) c.text = $("ed-text-" + n).value;
      c.state = "edited";
      renderItems();
      select(n, false);
      updateState();
    });
    li.appendChild(wrap);
    var ta = $("ed-reason-" + n);
    if (ta) ta.focus();
  }

  function find(n) {
    return S.data.corrections.filter(function (c) { return c.n === n; })[0];
  }

  /* ---------------------------------------------------------------- 상태 */
  function setState(n, st) {
    var c = find(n);
    c.state = c.state === st ? "pending" : st;
    var g = document.querySelector('.mk[data-n="' + n + '"]');
    if (g) g.dataset.state = c.state;
    paintButtons();
    applyVisibility();
    updateState();
  }

  function select(n, fromSheet) {
    S.sel = n;
    Array.prototype.forEach.call(document.querySelectorAll(".mk"), function (g) {
      g.classList.toggle("sel", +g.dataset.n === n);
    });
    Array.prototype.forEach.call($("items").querySelectorAll(".item"), function (li) {
      var on = +li.dataset.n === n;
      li.classList.toggle("sel", on);
      if (on && fromSheet) li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
    if (fromSheet) showTab("items");
  }

  function updateState() {
    var cs = S.data.corrections;
    var pend = cs.filter(function (c) { return c.state === "pending"; }).length;
    var el = $("stateline");
    if (pend === 0 && cs.length) {
      el.textContent = "검토 완료 · " + cs.length + "건";
      el.classList.add("done");
    } else {
      el.textContent = "검토 대기 · 남은 " + pend + "건";
      el.classList.remove("done");
    }
    $("return").disabled = pend !== 0;
  }

  /* ---------------------------------------------------------------- 필터 */
  function renderChips() {
    var by = {};
    S.data.corrections.forEach(function (c) {
      by[c.kind] = by[c.kind] || { label: c.label, n: 0 };
      by[c.kind].n++;
    });
    $("kindchips").innerHTML = Object.keys(by).map(function (k) {
      return '<button class="chip" data-kind="' + k + '" type="button">' + esc(by[k].label) +
        '<span class="n">' + by[k].n + "</span></button>";
    }).join("");
    Array.prototype.forEach.call($("kindchips").children, function (b) {
      b.addEventListener("click", function () {
        var k = b.dataset.kind;
        S.hidden[k] = !S.hidden[k];
        b.classList.toggle("off", !!S.hidden[k]);
        applyVisibility();
      });
    });
  }

  function applyVisibility() {
    var hidePending = $("hidepending").checked;
    Array.prototype.forEach.call(document.querySelectorAll(".mk"), function (g) {
      var c = find(+g.dataset.n);
      var off = S.hidden[c.kind] || (hidePending && c.state === "pending");
      g.classList.toggle("hidden", !!off);
    });
  }

  /* ---------------------------------------------------------------- 총평·게이트 */
  function renderReview() {
    var r = S.data.review || {};
    $("rv-good").value = r.good || "";
    $("rv-fix").value = r.fix || "";
    $("rv-next").value = r.next || "";
    ["good", "fix", "next"].forEach(function (k) {
      $("rv-" + k).onchange = function () {
        S.data.review[k] = $("rv-" + k).value;
      };
    });
  }

  function renderGate() {
    $("cnt-gate").textContent = S.gate.length;
    $("gateitems").innerHTML = S.gate.map(function (c) {
      return '<li class="item"><div class="hd"><span class="num">–</span>' +
        '<span class="kind">' + esc(c.kind) + "</span>" +
        '<span class="badge llm">LLM</span></div>' +
        '<p class="why"><span class="tgt">' + esc(c.target || "") + "</span> · " +
        esc(c.reason || "") + "</p>" +
        '<p class="why"><b>반려</b> — ' + esc(c.drop_reason || "") + "</p></li>";
    }).join("") || '<p class="note">반려된 항목이 없습니다.</p>';
  }

  function showTab(name) {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
      t.classList.toggle("on", t.dataset.tab === name);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tabpane"), function (p) {
      p.classList.toggle("on", p.id === "pane-" + name);
    });
  }

  /* ---------------------------------------------------------------- 내보내기 */
  function payloadOut(fmt, audience) {
    return {
      text: S.data.meta.text,
      corrections: S.data.corrections.map(function (c) {
        return { kind: c.kind, target: c.target, nth: c.nth, text: c.text,
                 reason: c.reason, layer: c.layer, source: c.source, state: c.state };
      }),
      review: S.data.review,
      format: fmt,
      audience: audience
    };
  }

  function exportSheet(fmt, audience) {
    if (window.__CHUMSAK__) {
      $("msg").textContent = "정적 데모에서는 내보내기가 동작하지 않습니다. server.py를 실행하세요.";
      return;
    }
    $("msg").textContent = "만드는 중…";
    fetch("/api/export", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadOut(fmt, audience)) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        $("msg").innerHTML = x.j.error ? esc(x.j.error)
          : '완료 — <a href="' + esc(x.j.url) + '" target="_blank">' + esc(x.j.url) + "</a>" +
            "  (승인 " + x.j.approved + "건 · 되살림표 " + x.j.stet + "건)";
      })
      .catch(function (e) { $("msg").textContent = "실패: " + e; });
  }

  /* ---------------------------------------------------------------- 입력 */
  function renderFocusChips() {
    $("focus-chips").innerHTML = FOCUS_KINDS.map(function (pair) {
      return '<button class="chip" type="button" data-kind="' + pair[0] + '">' +
        pair[1] + "</button>";
    }).join("");
    Array.prototype.forEach.call($("focus-chips").children, function (b) {
      b.addEventListener("click", function () {
        var k = b.dataset.kind;
        var i = S.focus.indexOf(k);
        if (i >= 0) {
          S.focus.splice(i, 1);
          b.classList.remove("on");
        } else {
          S.focus.push(k);
          b.classList.add("on");
        }
      });
    });
  }

  function runChumsak() {
    var text = $("src").value.trim();
    var msg = $("compose-msg");
    if (!text) { msg.textContent = "본문을 붙여 넣으세요."; return; }
    if (window.__CHUMSAK__) {
      msg.textContent = "정적 데모에서는 새 첨삭을 돌릴 수 없습니다.";
      return;
    }
    msg.textContent = "첨삭하는 중…";
    $("run").disabled = true;
    overlay(true, "규칙 계층과 LLM이 원고를 읽고 있습니다…");
    fetch("/api/chumsak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        grade: $("grade").value,
        focus: S.focus.length ? S.focus : null,
        indirect: $("indirect").checked
      })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        $("run").disabled = false;
        overlay(false);
        if (!x.ok) { msg.textContent = x.j.error || "실패"; return; }
        msg.textContent = "";
        boot(x.j);
      })
      .catch(function (e) {
        $("run").disabled = false;
        overlay(false);
        msg.textContent = "실패: " + e;
      });
  }

  function loadRecent() {
    if (window.__CHUMSAK__) { boot(window.__CHUMSAK__); return; }
    $("compose-msg").textContent = "불러오는 중…";
    fetch("/api/session").then(function (r) { return r.json(); }).then(boot)
      .catch(function (e) { $("compose-msg").textContent = "실패: " + e; });
  }

  function pingHealth() {
    var el = $("healthline");
    var pill = $("llmpill");
    if (window.__CHUMSAK__) {
      el.textContent = "정적 데모 · 내보내기 없음";
      return;
    }
    fetch("/api/health").then(function (r) { return r.json(); }).then(function (j) {
      S.health = j;
      if (j.catalog) CATALOG = j.catalog;
      fillProviders(j.provider, j.model);
      if (j.llm) {
        el.textContent = "LLM 연결 · " + (j.provider || "") + " · " + (j.model || "") +
          (j.key_hint ? " · " + j.key_hint : "");
        pill.textContent = (j.model || j.provider || "LLM");
        pill.classList.add("on"); pill.classList.remove("off");
      } else {
        el.textContent = "규칙 계층만 동작 중. API 키를 저장하면 총평과 내용 첨삭이 붙습니다.";
        pill.textContent = "LLM 꺼짐";
        pill.classList.add("off"); pill.classList.remove("on");
      }
    }).catch(function () { el.textContent = "서버에 닿지 않습니다. uvicorn server:app --port 8000"; });
  }

  function catalogProviders() {
    return (CATALOG && CATALOG.providers) || [];
  }

  function fillProviders(selected, model) {
    var sel = $("set-provider");
    if (!sel) return;
    sel.innerHTML = catalogProviders().map(function (p) {
      return '<option value="' + p.id + '">' + p.label + "</option>";
    }).join("");
    if (selected) sel.value = selected;
    fillModels(sel.value, model);
  }

  function fillModels(providerId, selected) {
    var pack = catalogProviders().filter(function (p) { return p.id === providerId; })[0];
    var sel = $("set-model");
    var models = pack ? pack.models : [];
    sel.innerHTML = models.map(function (m) {
      var tag = m.tag ? " · " + m.tag : "";
      return '<option value="' + m.id + '">' + m.name + tag + "</option>";
    }).join("") + '<option value="__custom__">직접 입력…</option>';
    $("set-key-hint").textContent = pack ? pack.key_hint : "";
    var want = selected || (pack && pack.default) || "";
    var ids = models.map(function (m) { return m.id; });
    if (want && ids.indexOf(want) < 0) {
      sel.value = "__custom__";
      $("set-model-custom").value = want;
    } else {
      sel.value = want;
    }
    $("set-custom-wrap").classList.toggle("hidden", sel.value !== "__custom__");
  }

  function chosenModel() {
    var v = $("set-model").value;
    if (v === "__custom__") return $("set-model-custom").value.trim();
    return v;
  }

  function loadCatalog(then) {
    fetch("/api/models").then(function (r) { return r.json(); }).then(function (j) {
      CATALOG = j;
      fillProviders();
      if (then) then();
    }).catch(function () {
      fillProviders();
      if (then) then();
    });
  }

  function saveSettings() {
    var msg = $("set-msg");
    var model = chosenModel();
    if (!model) { msg.textContent = "모델을 고르세요."; return; }
    msg.textContent = "연결 확인 중…";
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: $("set-provider").value,
        api_key: $("set-key").value,
        model: model
      })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (x) {
        if (!x.ok) { msg.textContent = x.j.error || "실패"; return; }
        msg.textContent = "연결됨 · " + (x.j.provider || "") + " · " + (x.j.model || "");
        $("set-key").value = "";
        pingHealth();
      })
      .catch(function (e) { msg.textContent = "실패: " + e; });
  }

  /* ---------------------------------------------------------------- 바인딩 */
  document.addEventListener("DOMContentLoaded", function () {
    renderFocusChips();
    loadCatalog(pingHealth);
    $("set-provider").addEventListener("change", function () { fillModels(this.value); });
    $("set-model").addEventListener("change", function () {
      $("set-custom-wrap").classList.toggle("hidden", this.value !== "__custom__");
    });
    $("src").addEventListener("input", function () {
      $("src-count").textContent = $("src").value.length;
    });
    $("run").addEventListener("click", runChumsak);
    $("load-recent").addEventListener("click", loadRecent);
    $("open-settings").addEventListener("click", function () {
      $("settings").classList.remove("hidden");
    });
    $("close-settings").addEventListener("click", function () {
      $("settings").classList.add("hidden");
    });
    $("save-settings").addEventListener("click", saveSettings);
    Array.prototype.forEach.call(document.querySelectorAll("[data-sample]"), function (b) {
      b.addEventListener("click", function () {
        var t = SAMPLES[b.dataset.sample];
        if (!t) return;
        $("src").value = t;
        $("src-count").textContent = t.length;
        $("grade").value = b.dataset.sample === "mid" ? "중등 2학년" : "초등 6학년";
      });
    });
    $("to-compose").addEventListener("click", function () {
      $("run").disabled = false;
      $("compose-msg").textContent = "";
      showView("compose");
    });

    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
      t.addEventListener("click", function () { showTab(t.dataset.tab); });
    });
    $("hidepending").addEventListener("change", applyVisibility);
    $("approve-all").addEventListener("click", function () {
      S.data.corrections.forEach(function (c) {
        if (c.source === "rule" && c.state === "pending") c.state = "approved";
      });
      S.data.corrections.forEach(function (c) {
        var g = document.querySelector('.mk[data-n="' + c.n + '"]');
        if (g) g.dataset.state = c.state;
      });
      paintButtons(); applyVisibility(); updateState();
    });
    $("reset-all").addEventListener("click", function () {
      S.data.corrections.forEach(function (c) { c.state = "pending"; });
      S.data.corrections.forEach(function (c) {
        var g = document.querySelector('.mk[data-n="' + c.n + '"]');
        if (g) g.dataset.state = "pending";
      });
      paintButtons(); applyVisibility(); updateState();
    });
    $("export-png").addEventListener("click", function () { exportSheet("png", "teacher"); });
    $("return").addEventListener("click", function () { exportSheet("pdf", "student"); });

    if (window.__CHUMSAK__) {
      $("src").value = (window.__CHUMSAK__.data && window.__CHUMSAK__.data.meta
        && window.__CHUMSAK__.data.meta.text) || "";
      $("src-count").textContent = $("src").value.length;
      boot(window.__CHUMSAK__);
    }
  });
})();
