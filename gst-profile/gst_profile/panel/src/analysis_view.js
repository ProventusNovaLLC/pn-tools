/* Analysis tab: the ranked findings, each expandable to evidence → why → fix, with
   the structured patch rendered as a best-effort launch-string diff. Heuristic and
   static findings are visibly labeled; the footer carries verified_on + scoping. */
var GPAnalysis = (function () {
  function render(state) {
    var host = document.getElementById("findings");
    var verdict = state.verdict;
    if (!verdict || !verdict.findings || !verdict.findings.length) {
      host.replaceChildren(mk("p", "dim", verdict ? "no findings." : "waiting for the first verdict…"));
      renderFooter(state);
      return;
    }
    var openIds = {};
    Array.prototype.forEach.call(host.querySelectorAll(".finding.open"), function (el) {
      openIds[el.getAttribute("data-id")] = true;
    });
    if (state.focusFinding) openIds[state.focusFinding] = true;
    host.replaceChildren();
    verdict.findings.forEach(function (f) {
      host.appendChild(card(state, f, openIds[f.id]));
    });
    renderFooter(state);
    if (state.focusFinding) {
      var el = host.querySelector('[data-id="' + cssEscape(state.focusFinding) + '"]');
      if (el) el.scrollIntoView({ block: "nearest" });
    }
  }

  function card(state, f, open) {
    var d = mk("div", "finding " + f.severity + (open ? " open" : ""));
    d.setAttribute("data-id", f.id || "");

    var head = mk("div", "head");
    head.appendChild(mk("span", "sev", f.severity));
    head.appendChild(mk("span", "rule mono", f.rule));
    var title = mk("span", "title", f.title);
    head.appendChild(title);
    if (typeof f.share_of_latency_pct === "number") {
      head.appendChild(mk("span", "share mono", f.share_of_latency_pct.toFixed(0) + "%"));
    }
    if (f.heuristic && f.severity === "info" && f.rule !== "HOT" && f.rule !== "OK") {
      head.appendChild(mk("span", "heur", "heuristic"));
    }
    head.addEventListener("click", function () { d.classList.toggle("open"); });
    d.appendChild(head);

    var body = mk("div", "body");
    var ev = f.evidence || {};
    var evKeys = Object.keys(ev);
    if (evKeys.length) {
      body.appendChild(mk("h4", "", "evidence"));
      var table = mk("table", "ev");
      evKeys.forEach(function (k) {
        var tr = document.createElement("tr");
        tr.appendChild(mk("td", "k mono", k));
        tr.appendChild(mk("td", "v mono", String(ev[k])));
        table.appendChild(tr);
      });
      body.appendChild(table);
    }
    if (f.why) { body.appendChild(mk("h4", "", "why")); body.appendChild(mk("p", "", f.why)); }
    body.appendChild(mk("h4", "", "fix"));
    if (f.fix_text) body.appendChild(mk("p", "", f.fix_text));
    var diff = launchDiff(state, f.fix_patch);
    if (diff) body.appendChild(diff);
    else if (f.fix_patch) body.appendChild(mk("p", "dim mono", patchLine(f.fix_patch)));

    var actions = mk("div", "actions");
    var show = mk("button", "", "Show on pipeline");
    show.addEventListener("click", function () {
      GPStore.focusFinding(f.id);
      GPApp.showTab("pipeline");
    });
    actions.appendChild(show);
    if (f.ref && /^https?:\/\//.test(f.ref)) {
      var a = document.createElement("a");
      a.href = f.ref; a.target = "_blank"; a.rel = "noopener";
      a.textContent = "reference →";
      actions.appendChild(a);
    }
    if (f.verified_on && f.verified_on.length) {
      actions.appendChild(mk("span", "dim", "verified on " + f.verified_on.join(", ")));
    }
    body.appendChild(actions);
    d.appendChild(body);
    return d;
  }

  /* One-line description of a structured fix patch (rules.py shapes):
     replace-element {element, with} · insert-element {before, element} ·
     set-property {element, property, value} · set-caps {link, to} · remove-element {element} */
  function patchLine(p) {
    switch (p.kind) {
      case "replace-element": return "replace " + p.element + " with " + p.with;
      case "insert-element": return "insert " + p.element + (p.before ? " before " + p.before : "");
      case "set-property": return "set " + p.element + " " + p.property + "=" + p.value;
      case "set-caps": return "force caps " + (p.to || "") + (p.link ? " on " + p.link : "");
      case "remove-element": return "remove " + p.element;
      default: return JSON.stringify(p);
    }
  }

  /* Resolve an instance name to its factory token in the launch string; null when the
     token is absent or appears more than once (ambiguous). */
  function tokenIndex(state, tokens, instance) {
    var els = state.session.graph.elements || [];
    var target = els.filter(function (e) { return e.id === instance; })[0];
    var factory = target && target.factory;
    if (!factory) return -1;
    var first = tokens.indexOf(factory);
    return first >= 0 && tokens.indexOf(factory, first + 1) < 0 ? first : -1;
  }

  /* Best-effort render of the patch as a diff of the launch string. Falls back to null
     (caller shows the plain patch line) when the anchor token can't be resolved. */
  function launchDiff(state, patch) {
    var launch = state.session && state.session.session && state.session.session.launch;
    if (!patch || !launch) return null;
    var tokens = launch.split(/\s+/);
    var pre = mk("div", "patch mono");
    function span(text) { if (text) pre.appendChild(document.createTextNode(text)); }
    function delTok(text) { var e = document.createElement("del"); e.textContent = text; pre.appendChild(e); }
    function insTok(text) { var e = document.createElement("ins"); e.textContent = text; pre.appendChild(e); }
    var idx;
    if (patch.kind === "replace-element" && patch.with) {
      idx = tokenIndex(state, tokens, patch.element);
      if (idx < 0) return null;
      span(tokens.slice(0, idx).join(" ") + " ");
      delTok(tokens[idx]); span(" "); insTok(patch.with);
      span(" " + tokens.slice(idx + 1).join(" "));
    } else if (patch.kind === "insert-element" && patch.before) {
      idx = tokenIndex(state, tokens, patch.before);
      if (idx < 0) return null;
      span(tokens.slice(0, idx).join(" ") + " ");
      insTok(patch.element + " !"); span(" ");
      span(tokens.slice(idx).join(" "));
    } else if (patch.kind === "set-property" && patch.property) {
      idx = tokenIndex(state, tokens, patch.element);
      if (idx < 0) return null;
      span(tokens.slice(0, idx + 1).join(" ") + " ");
      insTok(patch.property + "=" + patch.value);
      span(" " + tokens.slice(idx + 1).join(" "));
    } else if (patch.kind === "set-caps" && patch.link && patch.to) {
      idx = tokenIndex(state, tokens, String(patch.link).split(":")[0]);
      if (idx < 0) return null;
      span(tokens.slice(0, idx + 1).join(" ") + " ");
      insTok("! " + patch.to);
      span(" " + tokens.slice(idx + 1).join(" "));
    } else {
      return null;
    }
    return pre;
  }

  function renderFooter(state) {
    var foot = document.getElementById("an-footer");
    foot.replaceChildren();
    var verdict = state.verdict || {};
    var verified = {};
    (verdict.findings || []).forEach(function (f) {
      (f.verified_on || []).forEach(function (c) { verified[c] = true; });
    });
    var configs = Object.keys(verified);
    foot.appendChild(mk("span", "", configs.length
      ? "rules verified on: " + configs.join(", ") + " · "
      : "no rules bench-verified on hardware yet; diagnostics above are heuristic · "));
    var scope = verdict.scope || ((verdict.findings || [])[0] || {}).ref;
    if (scope && /^https?:\/\//.test(scope)) {
      var a = document.createElement("a");
      a.href = scope; a.target = "_blank"; a.rel = "noopener";
      a.textContent = "need help with this pipeline? scoping call →";
      foot.appendChild(a);
    }
  }

  function cssEscape(s) {
    return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function mk(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== "") e.textContent = text;
    return e;
  }

  return { render: render };
})();
if (typeof module !== "undefined") module.exports = GPAnalysis;
