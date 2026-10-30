// The profile page: saving the basic-info form, and drawing its two charts.
//
// The charts are plain SVG drawn at the container's real pixel width (and
// redrawn when it changes), so bar thickness and text size stay what they are
// meant to be rather than scaling with a viewBox.

(function () {
  var $ = function (id) { return document.getElementById(id); };

  // --- basic info ------------------------------------------------------------

  var form = $("profile-form");
  var username = $("username");
  var usernameHint = $("username-hint");
  var DEFAULT_HINT = usernameHint.textContent;
  var saved = username.value;  // the handle as stored, so "taken" can exclude it
  var debounce;

  function say(kind, message) {
    $("profile-error").hidden = kind !== "error";
    $("profile-note").hidden = kind !== "note";
    var box = $(kind === "error" ? "profile-error" : "profile-note");
    if (box) box.textContent = message || "";
  }

  username.addEventListener("input", function () {
    clearTimeout(debounce);
    var value = username.value.trim();
    usernameHint.className = "hint";
    if (!/^[A-Za-z0-9_]{3,20}$/.test(value)) {
      usernameHint.textContent = DEFAULT_HINT;
      return;
    }
    if (value.toLowerCase() === saved.toLowerCase()) {
      usernameHint.textContent = "That is your current username.";
      return;
    }
    usernameHint.textContent = "Checking…";
    debounce = setTimeout(function () {
      fetch("/api/username-available?u=" + encodeURIComponent(value))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (username.value.trim() !== value) return;  // typed on since
          usernameHint.textContent = value + (data.available
            ? " is available." : " is already taken.");
          usernameHint.className = "hint " + (data.available ? "ok-hint" : "error-hint");
        })
        .catch(function () { usernameHint.textContent = DEFAULT_HINT; });
    }, 350);
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var about = {
      gender: $("gender").value,
      age: Number($("age").value),
      school: $("school").value.trim(),
      nationality: $("nationality").value,
    };
    var min = Number($("age").min), max = Number($("age").max);
    var problem =
      !/^[A-Za-z0-9_]{3,20}$/.test(username.value.trim()) ? ["username", "Username must be 3-20 characters: letters, numbers, underscores."] :
      !about.gender ? ["gender", "Please select your gender."] :
      !(Number.isInteger(about.age) && about.age >= min && about.age <= max) ? ["age", "Please enter your age (" + min + "–" + max + ")."] :
      !about.school ? ["school", "Please enter your school."] :
      !about.nationality ? ["nationality", "Please select your nationality."] : null;
    if (problem) {
      say("error", problem[1]);
      $(problem[0]).focus();
      return;
    }

    var button = $("save-btn");
    button.disabled = true;
    button.textContent = "Saving…";
    fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: username.value.trim(), about: about }),
    })
      .then(function (r) { return r.json().then(function (data) { return [r.ok, data]; }); })
      .then(function (result) {
        var data = result[1];
        if (!result[0]) {
          say("error", data.error || "Could not save your changes.");
          if (data.field && $(data.field)) $(data.field).focus();
          return;
        }
        saved = data.username;
        username.value = saved;
        usernameHint.textContent = DEFAULT_HINT;
        usernameHint.className = "hint";
        document.querySelectorAll(".nav-user").forEach(function (el) { el.textContent = saved; });
        say("note", "Saved.");
      })
      .catch(function () { say("error", "Network problem. Check your connection and try again."); })
      .then(function () {
        button.disabled = false;
        button.textContent = "Save changes";
      });
  });

  // --- charts ----------------------------------------------------------------

  var data = JSON.parse($("profile-data").textContent);
  var SVG = "http://www.w3.org/2000/svg";
  var M = { top: 18, right: 6, bottom: 24, left: 30 };  // room for value and axis labels
  var BAR_MAX = 24, GAP = 2, RADIUS = 4;

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG, name);
    for (var key in attrs) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function text(parent, x, y, value, attrs) {
    var node = el("text", Object.assign({ x: x, y: y }, attrs || {}), parent);
    node.textContent = value;
    return node;
  }

  /** A clean axis top at or above `value`, and its step, for about 4 ticks. */
  function scale(value) {
    var steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000];
    var step = steps.find(function (s) { return Math.ceil(value / s) <= 4; }) || 1000;
    return { max: Math.max(step, Math.ceil(value / step) * step), step: step };
  }

  /** A column rounded at its data end and square on the baseline. */
  function column(x, y, w, h) {
    var r = Math.min(RADIUS, w / 2, h);
    return "M" + x + "," + (y + h) + "V" + (y + r) +
      "A" + r + "," + r + " 0 0 1 " + (x + r) + "," + y +
      "H" + (x + w - r) +
      "A" + r + "," + r + " 0 0 1 " + (x + w) + "," + (y + r) +
      "V" + (y + h) + "Z";
  }

  /** Frame shared by both charts: an svg, the plot box, and a y-axis. */
  function frame(container, top) {
    container.innerHTML = "";
    var width = container.clientWidth, height = container.clientHeight;
    var svg = el("svg", { width: width, height: height, role: "img" }, container);
    var plot = {
      svg: svg,
      x: M.left, y: M.top,
      w: width - M.left - M.right, h: height - M.top - M.bottom,
    };
    var s = scale(top);
    plot.max = s.max;
    plot.yOf = function (v) { return plot.y + plot.h - (v / s.max) * plot.h; };
    for (var v = 0; v <= s.max; v += s.step) {
      var y = Math.round(plot.yOf(v)) + 0.5;
      el("line", { x1: plot.x, x2: plot.x + plot.w, y1: y, y2: y,
                   stroke: v ? "var(--chart-grid)" : "var(--border)" }, svg);
      text(svg, plot.x - 8, y + 4, v, { "text-anchor": "end" });
    }
    var tip = document.createElement("div");
    tip.className = "chart-tip";
    tip.hidden = true;
    container.appendChild(tip);
    plot.tip = tip;
    return plot;
  }

  /** A hover target wider than its mark, showing `html` above (cx, cy). */
  function hover(plot, x, w, cx, cy, html) {
    var hit = el("rect", { x: x, y: plot.y, width: w, height: plot.h,
                           fill: "transparent" }, plot.svg);
    hit.addEventListener("mouseenter", function () {
      plot.tip.innerHTML = html;
      plot.tip.hidden = false;
      var half = plot.tip.offsetWidth / 2;
      var left = Math.min(Math.max(cx, half), plot.svg.clientWidth - half);
      plot.tip.style.left = left + "px";
      plot.tip.style.top = cy + "px";
    });
    hit.addEventListener("mouseleave", function () { plot.tip.hidden = true; });
  }

  function empty(container, message) {
    var note = document.createElement("div");
    note.className = "chart-empty";
    note.textContent = message;
    container.appendChild(note);
  }

  function label(band) { return band.charAt(0).toUpperCase() + band.slice(1); }

  // Solved by level: a group of three columns per chapter, easy to hard.
  function drawLevels() {
    var container = $("level-chart");
    var groups = data.byLevel, bands = data.bands;
    var top = Math.max(data.toClear, Math.max.apply(null, groups.map(function (g) {
      return Math.max.apply(null, bands.map(function (b) { return g.bands[b]; }));
    })));
    var plot = frame(container, top);
    var slot = plot.w / groups.length;
    var w = Math.min(BAR_MAX, (slot * 0.7 - GAP * (bands.length - 1)) / bands.length);
    var total = 0;

    groups.forEach(function (group, i) {
      var groupW = w * bands.length + GAP * (bands.length - 1);
      var left = plot.x + slot * i + (slot - groupW) / 2;
      bands.forEach(function (band, j) {
        var value = group.bands[band];
        var x = left + j * (w + GAP), y = plot.yOf(value);
        total += value;
        if (value) {
          el("path", { d: column(x, y, w, plot.y + plot.h - y),
                       fill: "var(--chart-" + band + ")" }, plot.svg);
          text(plot.svg, x + w / 2, y - 5, value,
               { "text-anchor": "middle", "class": "chart-value" });
        }
        hover(plot, x - GAP / 2, w + GAP, x + w / 2, y,
              "<b>" + group.title + "</b><br>" + label(band) + ": " + value + " solved");
      });
      text(plot.svg, plot.x + slot * (i + 0.5), plot.y + plot.h + 16, group.label,
           { "text-anchor": "middle" });
    });

    // Where a level clears. Drawn after the columns so it reads across them.
    var clearY = Math.round(plot.yOf(data.toClear)) + 0.5;
    el("line", { x1: plot.x, x2: plot.x + plot.w, y1: clearY, y2: clearY,
                 stroke: "var(--text)", "stroke-opacity": 0.35 }, plot.svg);

    plot.svg.setAttribute("aria-label", "Questions solved per chapter and band; " +
      total + " in all. The table below has every value.");
    if (!total) empty(container, "Solve a question and it shows up here.");
  }

  // Solves per day: one column a day, the busiest day labelled.
  function drawDays() {
    var container = $("day-chart");
    var days = data.byDay;
    var values = days.map(function (d) { return d.solved; });
    var peak = Math.max.apply(null, values);
    var total = values.reduce(function (a, b) { return a + b; }, 0);
    var plot = frame(container, Math.max(peak, 1));
    var slot = plot.w / days.length;
    var w = Math.min(BAR_MAX, slot - GAP);
    var fmt = function (iso) {
      return new Date(iso + "T00:00:00Z").toLocaleDateString(undefined,
        { month: "short", day: "numeric", timeZone: "UTC" });
    };
    var labelled = false;

    days.forEach(function (day, i) {
      var x = plot.x + slot * i + (slot - w) / 2, y = plot.yOf(day.solved);
      if (day.solved) {
        el("path", { d: column(x, y, w, plot.y + plot.h - y),
                     fill: "var(--chart-easy)" }, plot.svg);
      }
      // Label only the most recent busiest day, so the number stays readable.
      if (day.solved && day.solved === peak && !labelled &&
          values.lastIndexOf(peak) === i) {
        text(plot.svg, x + w / 2, y - 5, day.solved,
             { "text-anchor": "middle", "class": "chart-value" });
        labelled = true;
      }
      // A tick a week, counted back from today so the last one is today.
      if ((days.length - 1 - i) % 7 === 0) {
        text(plot.svg, x + w / 2, plot.y + plot.h + 16, fmt(day.date), {
          "text-anchor": i === days.length - 1 ? "end" : "middle",
        });
      }
      hover(plot, plot.x + slot * i, slot, x + w / 2, y,
            "<b>" + fmt(day.date) + "</b><br>" + day.solved + " solved");
    });

    $("day-total").textContent = total
      ? total + " question" + (total === 1 ? "" : "s") + " proved for the first time. Days are UTC."
      : "Questions proved for the first time, per day.";
    plot.svg.setAttribute("aria-label", "First solves per day over the last 30 days; " +
      total + " in all. The table below lists each day.");
    if (!total) empty(container, "No solves in the last 30 days yet.");
  }

  var legend = $("level-legend");
  data.bands.forEach(function (band) {
    var item = document.createElement("li");
    item.innerHTML = '<i style="background: var(--chart-' + band + ')"></i>' + label(band);
    legend.appendChild(item);
  });

  function draw() { drawLevels(); drawDays(); }
  draw();
  if (window.ResizeObserver) {
    var last = 0;
    new ResizeObserver(function () {
      var width = $("level-chart").clientWidth;
      if (width !== last) { last = width; draw(); }
    }).observe($("level-chart"));
  }
})();
