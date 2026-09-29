(() => {
  "use strict";
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    if (className) element.className = className;
    return element;
  };
  function inline(parent, spans) {
    for (const span of spans || []) {
      if (span.t === "code") parent.append(node("code", span.v));
      else if (span.t === "b") parent.append(node("strong", span.v));
      else parent.append(document.createTextNode(String(span.v)));
    }
    return parent;
  }
  function codeBlock(block) {
    const figure = node("figure", undefined, "code-block"), bar = node("figcaption");
    const copy = node("button", "Copy"), pre = node("pre"), code = node("code", block.text);
    copy.type = "button";
    copy.setAttribute("aria-label", `Copy ${block.lang || "code"} example`);
    pre.tabIndex = 0; pre.setAttribute("role", "region");
    pre.setAttribute("aria-label", `${block.lang || "Code"} example`);
    pre.append(code); bar.append(node("span", block.lang || "code"), copy); figure.append(bar, pre);
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(block.text);
        copy.textContent = "Copied";
      } catch {
        const range = document.createRange(), selection = getSelection();
        range.selectNodeContents(code); selection.removeAllRanges(); selection.addRange(range);
        copy.textContent = "Selected, copy it";
      }
      setTimeout(() => { copy.textContent = "Copy"; }, 2500);
    });
    return figure;
  }
  function renderBlocks(parent, blocks) {
    for (const block of blocks || []) {
      if (block.type === "code") parent.append(codeBlock(block));
      else if (block.type === "ul" || block.type === "ol") {
        const list = node(block.type);
        if (block.type === "ol" && block.start > 1) list.start = block.start;
        for (const item of block.items) list.append(inline(node("li"), item));
        parent.append(list);
      } else parent.append(inline(node(block.type === "h" ? "h3" : "p"), block.spans));
    }
    return parent;
  }
  const prose = blocks => renderBlocks(node("div", undefined, "prose"), blocks);
  function lessonSection(heading, id) {
    const section = node("section", undefined, "lesson-section");
    if (id) section.id = id;
    section.append(node("h2", heading));
    return section;
  }
  function walkthrough(story) {
    const element = lessonSection("Visual walkthrough", "lesson-walkthrough");
    element.append(node("p", "A prewritten diagram and explanation, not a prerecorded video. Animated video is available through /learn in Telegram.",
                        "section-description"));
    const ns = "http://www.w3.org/2000/svg";
    const svgNode = (tag, attributes, text) => {
      const result = document.createElementNS(ns, tag);
      for (const [key, value] of Object.entries(attributes || {})) result.setAttribute(key, value);
      if (text !== undefined) result.textContent = text;
      return result;
    };
    const figure = node("figure", undefined, "course-diagram");
    const svg = svgNode("svg", {viewBox: `0 0 780 ${story.actors.length > 3 ? 420 : 240}`, role: "img",
                               "aria-label": story.title});
    figure.tabIndex = 0; figure.setAttribute("role", "region"); figure.setAttribute("aria-label", "Scrollable lesson diagram");
    figure.append(svg);
    const title = node("h3"), caption = node("p"), narration = node("p"), paths = node("ul", undefined, "course-paths");
    title.setAttribute("aria-live", "polite");
    const controls = node("div", undefined, "course-controls");
    const previous = node("button", "Previous step"), next = node("button", "Next step");
    previous.type = next.type = "button"; controls.append(previous, next);
    let sceneIndex = 0;
    const positions = Object.fromEntries(story.actors.map((actor, i) => [actor.id, story.actors.length <= 3
      ? [story.actors.length === 2 ? 195 + 390 * i : 135 + 255 * i, 110]
      : [135 + 255 * (i % 3), 100 + 210 * Math.floor(i / 3)]]));
    function draw() {
      const scene = story.scenes[sceneIndex];
      svg.replaceChildren(); paths.replaceChildren();
      const defs = svgNode("defs"), marker = svgNode("marker", {
        id: "course-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
        markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
      });
      marker.append(svgNode("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: "var(--accent)"}));
      defs.append(marker); svg.append(defs);
      for (const edge of story.edges) {
        const [ax, ay] = positions[edge.source], [bx, by] = positions[edge.target];
        const dx = bx - ax, dy = by - ay, ratio = Math.min(dx ? 105 / Math.abs(dx) : Infinity, dy ? 44 / Math.abs(dy) : Infinity);
        const active = scene.active_edges.includes(edge.id);
        svg.append(svgNode("line", {x1: ax + dx * ratio, y1: ay + dy * ratio,
          x2: bx - dx * ratio, y2: by - dy * ratio, stroke: active ? "var(--accent)" : "var(--muted)",
          "stroke-width": active ? 3 : 1, "marker-end": "url(#course-arrow)"}));
        if (active) {
          const source = story.actors.find(a => a.id === edge.source).label;
          const target = story.actors.find(a => a.id === edge.target).label;
          paths.append(node("li", `${source} → ${target}${edge.label ? ": " + edge.label : ""}`));
        }
      }
      for (const actor of story.actors) {
        const [x, y] = positions[actor.id], active = scene.highlights.includes(actor.id);
        svg.append(svgNode("rect", {x: x - 105, y: y - 44, width: 210, height: 88, rx: 8,
          fill: active ? "var(--soft)" : "var(--surface)", stroke: active ? "var(--accent)" : "var(--line)",
          "stroke-width": active ? 2 : 1}));
        const lines = []; let current = "";
        for (const word of actor.label.split(/\s+/)) {
          if (current && (current + " " + word).length > 22) { lines.push(current); current = word; }
          else current = (current + " " + word).trim();
        }
        if (current) lines.push(current);
        lines.forEach((line, i) => svg.append(svgNode("text", {x, y: y - (lines.length - 1) * 10 + i * 20,
          "text-anchor": "middle", "dominant-baseline": "middle", fill: "var(--ink)", "font-size": 15}, line)));
        if (scene.states[actor.id]) svg.append(svgNode("text", {x, y: y + 66, "text-anchor": "middle",
          fill: "var(--muted)", "font-size": 14}, scene.states[actor.id]));
      }
      title.textContent = `${sceneIndex + 1} / ${story.scenes.length} · ${scene.title}`;
      caption.textContent = scene.caption; narration.textContent = scene.narration;
      previous.disabled = sceneIndex === 0; next.disabled = sceneIndex === story.scenes.length - 1;
    }
    previous.addEventListener("click", () => { sceneIndex--; draw(); });
    next.addEventListener("click", () => { sceneIndex++; draw(); });
    const transcript = node("details"), script = node("ol", undefined, "course-transcript");
    transcript.append(node("summary", "Read the complete transcript"));
    for (const scene of story.scenes) script.append(node("li", scene.title + ": " + scene.narration));
    transcript.append(script);
    element.append(figure, title, caption, narration, paths, controls, transcript); draw();
    return element;
  }
  window.SkillCoachLesson = Object.freeze({renderBlocks, prose, lessonSection, walkthrough});
})();
