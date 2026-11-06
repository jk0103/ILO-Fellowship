// The floating rules button and its panel. The panel is not modal: the proof
// stays usable while it is open, so a click outside does not close it — the
// button, the × and Escape do. The chapter tab last picked is remembered.

(function () {
  var fab = document.getElementById("rules-fab");
  var panel = document.getElementById("rules-panel");
  if (!fab || !panel) return;

  var KEY = "ilo:rules-tab";
  var tabs = panel.querySelectorAll("[data-rules-tab]");

  function pick(chapter) {
    // A chapter with no tab of its own falls back to the first.
    if (!panel.querySelector('[data-rules-tab="' + chapter + '"]')) chapter = tabs[0].dataset.rulesTab;
    tabs.forEach(function (tab) {
      var on = tab.dataset.rulesTab === chapter;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
    });
    panel.querySelectorAll("[data-rules-panel]").forEach(function (section) {
      section.hidden = section.dataset.rulesPanel !== chapter;
    });
    panel.querySelector(".rules-body").scrollTop = 0;
  }

  function open(show) {
    panel.hidden = !show;
    fab.setAttribute("aria-expanded", show ? "true" : "false");
    fab.classList.toggle("is-open", show);
    if (show) panel.querySelector('[aria-selected="true"]').focus();
    else if (fab.offsetParent) fab.focus();     // hidden on phones
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      pick(tab.dataset.rulesTab);
      try { localStorage.setItem(KEY, tab.dataset.rulesTab); } catch (e) {}
    });
    // Arrow keys move along the tabs, as a tab list should.
    tab.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      var list = Array.prototype.slice.call(tabs);
      var next = list[(list.indexOf(tab) + (event.key === "ArrowRight" ? 1 : -1) + list.length) % list.length];
      next.click();
      next.focus();
    });
  });

  fab.addEventListener("click", function () { open(panel.hidden); });
  // The editor's own Rules button, which stands in for this one on phones.
  // It is built by fitch.js, so listen on the document rather than on it.
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-rules-open]")) open(panel.hidden);
  });
  document.getElementById("rules-close").addEventListener("click", function () { open(false); });
  document.addEventListener("keydown", function (event) {
    // Escape belongs to the formula box while a rule is waiting on input.
    if (event.key === "Escape" && !panel.hidden && event.target.id !== "fitch-entry-input") open(false);
  });

  // A loaded question opens on its own chapter; otherwise the last tab used.
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  var loaded = window.__ILO_QUESTION ? panel.dataset.chapter : null;
  pick(loaded || saved || panel.dataset.chapter);
})();
