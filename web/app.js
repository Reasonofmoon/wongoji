/* 원고지 첨삭기 — 교사 검토 화면.
   서버가 보낸 SVG(칸 좌표는 파이썬이 계산)를 붙이고, 상태 관리만 담당한다.
   window.__CHUMSAK__ 가 있으면 그것을 쓰고(정적 데모), 없으면 /api/chumsak 을 부른다. */
(function () {
  "use strict";
  var S = { svg: null, data: null, sel: null, hidden: {} };
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /* ---------------------------------------------------------------- 초기화 */
  function boot(payload) {
    S.svg = payload.svg;
    S.data = payload.data;
    S.gate = payload.gate || [];
    $("sheetwrap").innerHTML = S.svg;
    S.data.corrections.forEach(function (c) { if (!c.state) c.state = "pending"; });
    bindSheet();
    renderChips();
    renderItems();
    renderGate();
    renderReview();
    updateState();
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
      '<button class="btn sm act" data-a="approved">승인</button>' +
      '<button class="btn sm act" data-a="edit">수정</button>' +
      '<button class="btn sm act" data-a="rejected">기각</button></div>' +
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
    if (li.querySelector(".edit")) return;
    var c = find(n);
    var ta = document.createElement("textarea");
    ta.className = "edit";
    ta.rows = 3;
    ta.value = c.reason;
    ta.addEventListener("click", function (e) { e.stopPropagation(); });
    ta.addEventListener("change", function () {
      c.reason = ta.value;
      c.state = "edited";
      c.source = c.source;
      renderItems();
      select(n, false);
      updateState();
    });
    li.appendChild(ta);
    ta.focus();
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
      return '<button class="chip" data-kind="' + k + '">' + esc(by[k].label) +
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
      $("rv-" + k).addEventListener("change", function () {
        S.data.review[k] = $("rv-" + k).value;
      });
    });
  }

  function renderGate() {
    $("cnt-gate").textContent = S.gate.length;
    $("gateitems").innerHTML = S.gate.map(function (c, i) {
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
  function payloadOut(fmt) {
    return {
      text: S.data.meta.text,
      corrections: S.data.corrections.map(function (c) {
        return { kind: c.kind, target: c.target, nth: c.nth, text: c.text,
                 reason: c.reason, layer: c.layer, source: c.source, state: c.state };
      }),
      review: S.data.review,
      format: fmt
    };
  }

  function exportSheet(fmt) {
    if (window.__CHUMSAK__) {
      $("msg").textContent = "정적 데모에서는 내보내기가 동작하지 않습니다. server.py를 실행하세요.";
      return;
    }
    $("msg").textContent = "만드는 중…";
    fetch("/api/export", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payloadOut(fmt)) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        $("msg").innerHTML = j.error ? esc(j.error)
          : '완료 — <a href="' + esc(j.url) + '" target="_blank">' + esc(j.url) + "</a>" +
            "  (승인 " + j.approved + "건 · 되살림표 " + j.stet + "건)";
      })
      .catch(function (e) { $("msg").textContent = "실패: " + e; });
  }

  /* ---------------------------------------------------------------- 바인딩 */
  document.addEventListener("DOMContentLoaded", function () {
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
    $("export-png").addEventListener("click", function () { exportSheet("png"); });
    $("return").addEventListener("click", function () { exportSheet("pdf"); });

    if (window.__CHUMSAK__) { boot(window.__CHUMSAK__); return; }
    fetch("/api/session").then(function (r) { return r.json(); }).then(boot)
      .catch(function (e) {
        $("sheetwrap").innerHTML = '<p class="note" style="padding:20px">불러오지 못했습니다: ' +
          esc(e) + "</p>";
      });
  });
})();
