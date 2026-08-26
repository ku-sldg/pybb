// Generator for docs/video_slides_draft.pptx (the video presentation deck).
// Usage: node scripts/gen_slides.js [output.pptx]   (default: docs/video_slides_draft.pptx)
// Requires pptxgenjs (npm install pptxgenjs).
// NOTE: the deck is ALSO edited directly in PowerPoint. Before regenerating,
// diff the on-disk deck for manual edits (scripts/pptx_diff.py old.pptx new.pptx)
// and port them here first — see docs/video_slide_drafts.md for the content
// source of truth and per-slide decision log.
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5

const NAVY = "1E2761", ICE = "CADCFC", WHITE = "FFFFFF", DARK = "212121", MUTED = "5A6478";
const HDR = "Cambria", BODY = "Calibri";

// ---------- Slide 1: Title ----------
let s1 = pres.addSlide();
s1.background = { color: NAVY };
s1.addText("Lifecycle Attestation with pybb", {
  x: 0.9, y: 2.4, w: 11.5, h: 1.2, fontFace: HDR, fontSize: 44, bold: true,
  color: WHITE, align: "left", margin: 0,
});
s1.addText("Measured trust across models, contracts, implementations, and proofs", {
  x: 0.9, y: 3.6, w: 11.5, h: 0.6, fontFace: BODY, fontSize: 20, italic: true,
  color: ICE, align: "left", margin: 0,
});
s1.addText("Presenter name  ·  affiliation  ·  date", {
  x: 0.9, y: 6.3, w: 11.5, h: 0.4, fontFace: BODY, fontSize: 14, color: ICE,
  align: "left", margin: 0,
});
s1.addNotes("Title card. Subtitle deliberately names the four core artifact classes - the deck's first echo of the artifact-class table (slide 6). Optional footer: INSPECTA program context.");

// ---------- Slide 2: What is lifecycle attestation? ----------
let s2 = pres.addSlide();
s2.background = { color: WHITE };
s2.addText("What is lifecycle attestation?", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});
// build bullets as rich text runs
const bullets = [
  { runs: [
      { text: "Traditional remote attestation: ", options: { bold: true } },
      { text: "did system components boot into a predictable state?", options: { bold: true } },
      { text: " (boot-time, static runtime)", options: {} },
    ], indent: 0 },
  { runs: [
      { text: "Layered, runtime attestation: ", options: { bold: true } },
      { text: "extend boot-time trust via dynamic measurement of system components ", options: {} },
      { text: "and their context/dependencies", options: { bold: true } },
    ], indent: 0 },
  { runs: [
      { text: "Lifecycle attestation: ", options: { bold: true } },
      { text: "extends this notion to ", options: {} },
      { text: "artifacts of the development lifecycle", options: { bold: true } },
      { text: ": models, contracts, implementations, proofs, toolchains", options: {} },
    ], indent: 0 },
  { runs: [
      { text: "…including the attestation infrastructure and evidence itself", options: {} },
    ], indent: 1 },
  { runs: [
      { text: "…and to lifecycle ", options: {} },
      { text: "events", options: { bold: true } },
      { text: ":", options: {} },
    ], indent: 1 },
  { runs: [{ text: "specification drift (sanctioned or not)", options: {} }], indent: 2 },
  { runs: [{ text: "artifact tampering", options: {} }], indent: 2 },
  { runs: [{ text: "artifact synthesis", options: {} }], indent: 2 },
  { runs: [{ text: "artifact repair", options: {} }], indent: 2 },
  { runs: [
      { text: "Motivation: ", options: { bold: true } },
      { text: "the ", options: {} },
      { text: "proliferation of AI-generated software artifacts", options: { bold: true } },
      { text: ", amid the need for rapid re-certification of systems", options: {} },
    ], indent: 0 },
];

const bulletCodes = ["2022", "2013", "25AA"]; // • – ▪ by indent level
const paras = [];
bullets.forEach((b, i) => {
  b.runs.forEach((r, j) => {
    const opts = Object.assign({}, r.options);
    if (j === 0) {
      opts.bullet = { code: bulletCodes[b.indent] || "2022" };
      opts.indentLevel = b.indent;
    }
    opts.breakLine = (j === b.runs.length - 1) && (i !== bullets.length - 1);
    if (j === b.runs.length - 1) opts.paraSpaceAfter = b.indent === 2 ? 2 : 10;
    paras.push({ text: r.text, options: opts });
  });
});

s2.addText(paras, {
  x: 0.7, y: 1.45, w: 12.0, h: 3.9, fontFace: BODY, fontSize: 17, color: DARK,
  align: "left", valign: "top", margin: 0,
});

// Banner
s2.addShape(pres.ShapeType.roundRect, {
  x: 0.7, y: 5.55, w: 11.9, h: 1.35, fill: { color: NAVY }, rectRadius: 0.08, line: { type: "none" },
});
s2.addText([
  { text: "Every trust decision is grounded in cryptographic attestation evidence.", options: { bold: true, fontSize: 20, color: WHITE, breakLine: true, paraSpaceAfter: 4 } },
  { text: "trust is NOT anchored in the following:  developer claims, untrusted tools, LLM outputs, cached verdicts", options: { italic: true, fontSize: 14, color: ICE } },
], {
  x: 1.0, y: 5.55, w: 11.3, h: 1.35, fontFace: BODY, align: "center", valign: "middle", margin: 0,
});
s2.addNotes(
  "Promise the audience every demo scene echoes the banner.\n" +
  "The administrator's bless survives 'every': authority enters the system only AS signed evidence (the blessed baseline), never by assertion - scene 6's laundering beat proves exactly that.\n" +
  "Subline payoffs: developer claims -> scenes 5/7; untrusted tools -> scene 7; LLM outputs -> capstone slides A/B; cached verdicts -> scene 11.\n" +
  "Visual TODO: three-stage widening-scope progression (boot-time -> layered runtime -> lifecycle loop) to replace/join the bullets."
);

// ---------- Slide 3: Roadmap strip ----------
let s3 = pres.addSlide();
s3.background = { color: WHITE };
s3.addText("Roadmap", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});

const sections = ["Preliminaries", "Demo:\nIsolette (SysMLv2 \u2192 Rust)", "Other Ecosystems", "AI in the Loop", "Close"];
const stripY = 3.1, stripH = 0.85, gap = 0.18, x0 = 0.7, totalW = 11.9;
const segW = (totalW - gap * (sections.length - 1)) / sections.length;
sections.forEach((name, i) => {
  const x = x0 + i * (segW + gap);
  const active = i === 0;
  s3.addShape(pres.ShapeType.roundRect, {
    x, y: stripY, w: segW, h: stripH, rectRadius: 0.07,
    fill: { color: active ? NAVY : ICE }, line: { type: "none" },
  });
  s3.addText(name, {
    x, y: stripY, w: segW, h: stripH, fontFace: BODY, fontSize: 13.5,
    bold: active, color: active ? WHITE : NAVY, align: "center", valign: "middle", margin: 0.02,
  });
  if (i < sections.length - 1) {
    s3.addText("→", {
      x: x + segW - 0.06, y: stripY, w: gap + 0.12, h: stripH, fontFace: BODY,
      fontSize: 14, color: MUTED, align: "center", valign: "middle", margin: 0,
    });
  }
});
s3.addText("Section headers provisional — the strip returns at every act transition with the current section highlighted.", {
  x: 0.7, y: 4.35, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 13, italic: true, color: MUTED, margin: 0,
});
s3.addNotes(
  "~15 seconds on first appearance; afterwards it rides on transition slides for free.\n" +
  "Design decision: one master/layout holds the strip text so a section rename is a single edit. Header titles are provisional."
);

// ---------- Slide 4: The core attestation stack ----------
let s4 = pres.addSlide();
s4.background = { color: WHITE };
s4.addText("The core attestation stack", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});

// Left column: layered diagram (simple stacked boxes + arrows)
const LX = 0.7, LW = 6.3;

// Copland layer
s4.addShape(pres.ShapeType.roundRect, {
  x: LX, y: 1.45, w: LW, h: 1.1, rectRadius: 0.07, fill: { color: NAVY }, line: { type: "none" },
});
s4.addText([
  { text: "Copland", options: { bold: true, fontSize: 17, color: WHITE, breakLine: true, paraSpaceAfter: 2 } },
  { text: "attestation protocols as formal terms with an evidence semantics: what was measured, in what order, signed by whom", options: { fontSize: 12, color: ICE } },
], { x: LX + 0.25, y: 1.45, w: LW - 0.5, h: 1.1, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

s4.addText("▼", { x: LX + LW / 2 - 0.2, y: 2.56, w: 0.4, h: 0.28, fontSize: 12, color: MUTED, align: "center", margin: 0 });

// CVM layer
s4.addShape(pres.ShapeType.roundRect, {
  x: LX, y: 2.85, w: LW, h: 1.1, rectRadius: 0.07, fill: { color: "3A4A8C" }, line: { type: "none" },
});
s4.addText([
  { text: "CVM — Copland Virtual Machine", options: { bold: true, fontSize: 17, color: WHITE, breakLine: true, paraSpaceAfter: 2 } },
  { text: "executes Copland phrases · dispatches ASPs according to manifest configurations · appraises results", options: { fontSize: 12, color: ICE } },
], { x: LX + 0.25, y: 2.85, w: LW - 0.5, h: 1.1, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

s4.addText("▼", { x: LX + LW / 2 - 0.2, y: 3.96, w: 0.4, h: 0.28, fontSize: 12, color: MUTED, align: "center", margin: 0 });

// asp-libs layer
s4.addShape(pres.ShapeType.roundRect, {
  x: LX, y: 4.25, w: LW, h: 0.95, rectRadius: 0.07, fill: { color: "56659E" }, line: { type: "none" },
});
s4.addText([
  { text: "asp-libs", options: { bold: true, fontSize: 17, color: WHITE, breakLine: true, paraSpaceAfter: 2 } },
  { text: "measurement & appraisal primitives: hash, readfile, signature, golden comparison, \u2026", options: { fontSize: 12, color: ICE } },
], { x: LX + 0.25, y: 4.25, w: LW - 0.5, h: 0.95, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

s4.addText("▼", { x: LX + LW / 2 - 0.2, y: 5.21, w: 0.4, h: 0.28, fontSize: 12, color: MUTED, align: "center", margin: 0 });

// Output layer
s4.addShape(pres.ShapeType.roundRect, {
  x: LX, y: 5.5, w: LW, h: 0.95, rectRadius: 0.07, fill: { color: ICE }, line: { type: "none" },
});
s4.addText([
  { text: "signed evidence bundles", options: { bold: true, fontSize: 15, color: NAVY } },
  { text: ", appraised against ", options: { fontSize: 15, color: NAVY } },
  { text: "golden baselines", options: { bold: true, fontSize: 15, color: NAVY } },
], { x: LX + 0.25, y: 5.5, w: LW - 0.5, h: 0.95, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

// Right column: Copland snippet sidebar
const RX = 7.4, RW = 5.2;
s4.addText("A real protocol from the demo — the isolette model class:", {
  x: RX, y: 1.55, w: RW, h: 0.4, fontFace: BODY, fontSize: 13, italic: true, color: MUTED, margin: 0,
});
s4.addShape(pres.ShapeType.roundRect, {
  x: RX, y: 2.0, w: RW, h: 2.5, rectRadius: 0.05, fill: { color: "F2F4F8" }, line: { color: ICE, width: 1 },
});
s4.addText(
  "( readfile Regulate.sysml\n" +
  "  +<+ readfile Monitor.sysml\n" +
  "  +<+ readfile Operator_Interface.sysml\n" +
  "  +<+ readfile oip_oit_app.rs\n" +
  "  +<+ readfile GUMBO_Library )\n" +
  "-> SIG -> APPR",
  { x: RX + 0.25, y: 2.0, w: RW - 0.5, h: 2.5, fontFace: "Courier New", fontSize: 13,
    color: DARK, align: "left", valign: "middle", margin: 0 });
s4.addText([
  { text: "measure the five blessed model files \u2192 ", options: { breakLine: true } },
  { text: "\tsign the evidence (SIG) \u2192 ", options: { breakLine: true } },
  { text: "\tappraise it (APPR)", options: {} },
], {
  x: RX, y: 4.6, w: RW, h: 1.45, fontFace: BODY, fontSize: 20, italic: true, color: MUTED, margin: 0,
});

s4.addNotes(
  "One phrase of 'what this layer contributes' each; asp-libs has its own layer box; keep it to one spoken clause (its inventory returns as a star of capstone slide B).\n" +
  "On the snippet: 'you don't need to read this - you need to know it's a formal object with an evidence semantics.' Measure the five blessed model files, sign the evidence, appraise it.\n" +
  "Snippet source: tests/fixtures/isolette_sysmlv2_rust_props/term.json, rendered in concrete syntax (branches flattened, target IDs shortened to file names - cosmetic).\n" +
  "The verus-tier measure-then-use phrase is deliberately held back for scene 7's reveal."
);

// ---------- Slide 5: pybb — a blackboard architecture for attestation ----------
const GREEN = "2C7A3F", RED = "A33327", MID5 = "3A4A8C";
function box5(s, x, y, w, h, fillColor, label, opts = {}) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06, fill: { color: fillColor }, line: { type: "none" },
  });
  s.addText(label, {
    x, y, w, h, fontFace: BODY, fontSize: opts.fontSize || 13,
    bold: opts.bold !== false, color: opts.textColor || WHITE,
    align: "center", valign: "middle", margin: 0.03,
  });
}
function arrow5(s, x1, y1, x2, y2, color, opts = {}) {
  s.addShape(pres.ShapeType.line, {
    x: Math.min(x1, x2), y: Math.min(y1, y2),
    w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color, width: opts.width || 2, endArrowType: "triangle" },
  });
}
function seg5(s, x1, y1, x2, y2, color, w = 2) {
  s.addShape(pres.ShapeType.line, {
    x: Math.min(x1, x2), y: Math.min(y1, y2),
    w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color, width: w },
  });
}

let s5 = pres.addSlide();
s5.background = { color: WHITE };
s5.addText("pybb: a blackboard architecture for attestation", {
  x: 0.7, y: 0.32, w: 12.0, h: 0.72, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});

// administrator blessing (human authority act, out-of-band) -> provision
s5.addShape(pres.ShapeType.roundRect, {
  x: 3.7, y: 1.12, w: 2.7, h: 0.62, rectRadius: 0.06,
  fill: { color: WHITE }, line: { color: NAVY, width: 1.5, dashType: "dash" },
});
s5.addText([
  { text: "Administrator blessing", options: { bold: true, fontSize: 11.5, color: NAVY, breakLine: true } },
  { text: "(signs golden spec)", options: { fontSize: 10.5, color: NAVY, italic: true } },
], { x: 3.7, y: 1.12, w: 2.7, h: 0.62, fontFace: BODY, align: "center", valign: "middle", margin: 0.02 });
arrow5(s5, 4.3, 1.74, 4.3, 2.08, NAVY, { width: 1.5 });
s5.addText("bless ⇒ provision", {
  x: 4.42, y: 1.76, w: 1.9, h: 0.28, fontFace: BODY, fontSize: 10, italic: true, color: NAVY, align: "left", margin: 0,
});

// measurement
box5(s5, 0.7, 3.0, 1.7, 1.0, MID5, "measurement");
arrow5(s5, 2.4, 3.5, 3.0, 3.5, DARK);

// blackboard with 3 lanes
s5.addText("Blackboard", { x: 3.0, y: 1.78, w: 1.1, h: 0.3, fontFace: BODY, fontSize: 12, bold: true, color: NAVY, align: "left", margin: 0 });
box5(s5, 3.0, 2.1, 2.6, 0.8, ICE, "provision", { textColor: NAVY, fontSize: 12 });
box5(s5, 3.0, 3.0, 2.6, 1.0, NAVY, "certify");
box5(s5, 3.0, 4.1, 2.6, 0.8, ICE, "escalate", { textColor: RED, fontSize: 12 });
arrow5(s5, 5.6, 3.5, 6.2, 3.5, DARK);

// provision -> escalate: no repair chain
seg5(s5, 3.0, 2.5, 2.72, 2.5, RED);
seg5(s5, 2.72, 2.5, 2.72, 4.5, RED);
arrow5(s5, 2.72, 4.5, 3.0, 4.5, RED);
s5.addText("no repair chain:\nfail ⇒ escalate", {
  x: 0.25, y: 4.35, w: 1.2, h: 0.9, fontFace: BODY, fontSize: 10, italic: true,
  color: RED, align: "right", margin: 0,
});

// provision -> measurement (successful provisioning leads to re-measurement)
seg5(s5, 3.0, 2.35, 1.55, 2.35, GREEN, 2);
arrow5(s5, 1.55, 2.35, 1.55, 2.97, GREEN);
s5.addText("provisioned ⇒ re-measure", {
  x: 0.6, y: 2.0, w: 2.6, h: 0.3, fontFace: BODY, fontSize: 10.5, italic: true,
  color: GREEN, align: "center", margin: 0,
});

// controller
box5(s5, 6.2, 3.0, 2.2, 1.0, MID5, "Controller\n(evaluate = episode)", { fontSize: 12 });
arrow5(s5, 8.4, 3.5, 9.0, 3.5, DARK);
s5.addText("dispatch", { x: 8.2, y: 3.55, w: 1.0, h: 0.28, fontFace: BODY, fontSize: 10, color: MUTED, align: "center", margin: 0 });

// KS chain — RED arrows = on-fail handoff
box5(s5, 9.0, 3.0, 1.1, 1.0, NAVY, "KS 1", { fontSize: 12 });
arrow5(s5, 10.1, 3.5, 10.5, 3.5, RED);
box5(s5, 10.5, 3.0, 1.1, 1.0, NAVY, "KS 2", { fontSize: 12 });
arrow5(s5, 11.6, 3.5, 12.0, 3.5, RED);
box5(s5, 12.0, 3.0, 1.1, 1.0, NAVY, "KS n", { fontSize: 12 });
s5.addText("red → = on-fail handoff (attempts spent, changes restored)", {
  x: 8.8, y: 4.12, w: 4.4, h: 0.3, fontFace: BODY, fontSize: 10.5, italic: true, color: RED, align: "center", margin: 0,
});

// GREEN: on-pass — every KS result returns to the Controller, which re-verifies
seg5(s5, 9.55, 3.0, 9.55, 2.3, GREEN, 2);
seg5(s5, 11.05, 3.0, 11.05, 2.3, GREEN, 2);
seg5(s5, 12.55, 3.0, 12.55, 2.3, GREEN, 2);
seg5(s5, 7.3, 2.3, 12.55, 2.3, GREEN);
arrow5(s5, 7.3, 2.3, 7.3, 2.95, GREEN);
s5.addText("on-pass: re-verify · restart-episode ⇒ fresh measurement", {
  x: 6.4, y: 1.92, w: 5.4, h: 0.3, fontFace: BODY, fontSize: 11, color: GREEN, align: "center", margin: 0,
});

// RED: route exhausted -> escalate lane
seg5(s5, 12.55, 4.0, 12.55, 5.15, RED);
seg5(s5, 4.3, 5.15, 12.55, 5.15, RED);
arrow5(s5, 4.3, 5.15, 4.3, 4.92, RED);
s5.addText("all rungs exhausted → escalate", {
  x: 7.2, y: 5.22, w: 3.6, h: 0.3, fontFace: BODY, fontSize: 11, color: RED, align: "center", margin: 0,
});

// Controller -> measurement: evaluating a predicate runs the attestation measurement
seg5(s5, 7.0, 4.0, 7.0, 6.0, DARK, 1.5);
seg5(s5, 1.55, 6.0, 7.0, 6.0, DARK, 1.5);
arrow5(s5, 1.55, 6.0, 1.55, 4.02, DARK, { width: 1.5 });
s5.addText("evaluate ⇒ run measurement", {
  x: 2.6, y: 6.06, w: 3.4, h: 0.3, fontFace: BODY, fontSize: 11, color: MUTED, align: "center", margin: 0,
});

// Callout: the repair ladder (the slide's one idea)
s5.addShape(pres.ShapeType.roundRect, {
  x: 0.7, y: 6.55, w: 8.9, h: 0.8, rectRadius: 0.07, fill: { color: NAVY }, line: { type: "none" },
});
s5.addText([
  { text: "The repair ladder: ", options: { bold: true, color: WHITE } },
  { text: "a rung's exhaustion is a ", options: { color: ICE } },
  { text: "local diagnosis ", options: { color: ICE, bold: true, italic: true } },
  { text: "of failure— every repair is ", options: { color: ICE, breakLine: true } },
  { text: "judged only by ", options: { color: ICE } },
  { text: "fresh re-measurement", options: { color: ICE, bold: true, italic: true } },
  { text: ".", options: { color: ICE } },
], { x: 0.95, y: 6.55, w: 8.4, h: 0.8, fontFace: BODY, fontSize: 13, align: "left", valign: "middle", margin: 0 });

// Legend: the checklist glyphs the demo is read through
s5.addShape(pres.ShapeType.roundRect, {
  x: 9.8, y: 6.55, w: 2.8, h: 0.8, rectRadius: 0.07, fill: { color: "F2F4F8" }, line: { color: ICE, width: 1 },
});
s5.addText("✓ attested   ✗ refuted\n?  poisoned (fail-closed)", {
  x: 9.95, y: 6.55, w: 2.55, h: 0.8, fontFace: "Courier New", fontSize: 11,
  color: DARK, align: "left", valign: "middle", margin: 0,
});

s5.addNotes(
  "Keep the vocabulary minimal: entry, episode, knowledge source, ladder, escalate. Everything else is detail the scenes show live.\n" +
  "Semantics verified against the pybb README control flow: green = on-pass (results return to the Controller; standing re-established only by its re-evaluation, with restart-episode forcing genuinely fresh measurement); red = on-fail (handoff on exhaustion with changes restored; exhausted routes escalate; provision requests have no repair chains and escalate immediately - the readiness-gate refusal).\n" +
  "The Administrator blessing box is dashed/white: a human, out-of-band authority act, not a component in the measured loop - only exit from a refused baseline (scene 6).\n" +
  "Speaker-note-only details (cut from the slide): on_pass/on_fail dispatch mechanics, success-driven handoff for component-wise entries, max_attempts per rung.\n" +
  "The legend earns its space: every scene's checklist frames render through these glyphs."
);

// ---------- Slide 5b: pybb key components ----------
let s5b = pres.addSlide();
s5b.background = { color: WHITE };
s5b.addText("pybb: key components", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});

const comps = [
  { term: "Blackboard", desc: "the shared store: every measurement lands as an entry with its condition and standing; three segments (provision · certify · escalate) plus a full history of every change" },
  { term: "Blackboard Entry (Key)", desc: "one measurement under judgment, identified by its key: the measurement, its condition, its standing, its repair history" },
  { term: "Episode", desc: "one full judgment of an entry: the attestation runs once and its verdicts are memoized until the episode ends — or is restarted for genuinely fresh measurement" },
  { term: "Partition", desc: "the division of blackboard entries among different workflow stages: each knowledge source watches its own collection of keys, and an entry sits in the partition of whichever rung currently owns it" },
  { term: "Controller", desc: "the cycle: evaluates every entry (provision first), dispatches keys onto outcome-routed chains, advances or hands off, escalates; halts only when everything is in good standing" },
  { term: "Knowledge source (KS)", desc: "a repair rung: operates only on entries in its partition (optionally a single component), bounded by max_attempts; its work is always re-judged, never trusted" },
  { term: "Route", desc: "the per-key chains: on_fail = the repair ladder, on_pass = a confirmation chain before an entry may rest in good standing" },
  { term: "History / Ledger", desc: "the blackboard's running record of every change across all segments — measurements, repairs, verdicts — the audit trail of the repair lifecycle" },
];
const compParas = [];
comps.forEach((c, i) => {
  compParas.push({ text: c.term, options: { bold: true, color: NAVY, bullet: { code: "2022" }, breakLine: false } });
  compParas.push({ text: " — " + c.desc, options: { color: DARK, breakLine: i !== comps.length - 1, paraSpaceAfter: 9 } });
});
s5b.addText(compParas, {
  x: 0.7, y: 1.5, w: 12.0, h: 5.7, fontFace: BODY, fontSize: 16, align: "left", valign: "top", margin: 0,
});

s5b.addNotes(
  "The audience's glossary for the terminal scenes - point back at the slide-5 diagram while reading it.\nEntry keys in the real demos are the provisioned protocols: ready (the readiness gate), isolette_sysmlv2_rust_props (blessed model), _l1a (file hashes), _l2 (contract slices), _verus, _cheat, _sysproof, _gensrc, _report. Every row of the checklist the audience is about to watch is one of these keys.\n" +
  "Predicate and restart-episode are deliberately OFF this slide (parked; placement TBD - possibly an 'evaluation primitives' strip). If asked: a predicate is the judge (one evaluation = one attestation episode), restart-episode is the freshness primitive (forget memoized verdicts, reset, re-evaluate).\n" +
  "Also deliberately excluded (README-level detail): partition mechanics, component-wise entries and success handoff, dispatch latching, max_cycles."
);

// ---------- Slide 6 (deck position 7): Artifact classes ----------
let s6 = pres.addSlide();
s6.background = { color: WHITE };
s6.addText("Artifact classes", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 34, bold: true,
  color: NAVY, margin: 0,
});

const th = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 14, align: "left", valign: "middle" } });
const td = (t, opts = {}) => ({ text: t, options: Object.assign({ color: DARK, fontSize: 12.5, align: "left", valign: "middle" }, opts) });

const CROSS = { color: NAVY };
const tableRows = [
  [th("Artifact Class"), th("Measured how"), th("Judged by"), th("Repair type")],
  [td([{ text: "Model", options: { bold: true } }]),
   td("whole-file hash of spec files"),
   td("appraisal vs the signed golden"),
   td([{ text: "restore from golden — or ", options: {} }, { text: "bless", options: { italic: true } }, { text: " (sanctioned change)", options: {} }])],
  [td([{ text: "Contract", options: { bold: true } }]),
   td("syntax-guided file slices"),
   td("slice-level appraisal, attributed by name"),
   td("restore golden slice")],
  [td([{ text: "Implementation", options: { bold: true } }]),
   td("developer-owned code"),
   td("tests + verification of contracts"),
   td("code synthesis/repair")],
  [td([{ text: "Proof / Verification", options: { bold: true } }]),
   td("live verification run"),
   td("verification kernel — fresh, never cached"),
   td("proof synthesis/repair")],
  [td([{ text: "Toolchain ", options: { bold: true, color: NAVY } }, { text: "(cross-cutting)", options: { italic: true, fontSize: 11, color: NAVY } }]),
   td([{ text: "hashed ", options: {} }, { text: "measure-then-use", options: { bold: true } }]),
   td("the tool hash(es), taken in the same term"),
   td("out-of-band or pre-sanctioned restore")],
  [td([{ text: "Trust state ", options: { bold: true, color: NAVY } }, { text: "(cross-cutting)", options: { italic: true, fontSize: 11, color: NAVY } }]),
   td("bundles, goldens, signatures"),
   td("appraisal vs the signed golden or derived"),
   td([{ text: "principled refusal", options: { bold: true } }, { text: " — out-of-band re-bless", options: {} }])],
];
s6.addTable(tableRows, {
  x: 0.7, y: 1.55, w: 11.9, colW: [2.4, 2.9, 3.3, 3.3],
  border: { type: "solid", color: "D8DEEA", pt: 1 },
  fill: { color: WHITE },
  rowH: 0.72,
  margin: 0.08,
  fontFace: BODY,
});

s6.addNotes(
  "The last two rows are the surprising ones - scenes 6-7 exist for them.\n" +
  "Spoken hook (never on-slide text): 'This table is deliberately incomplete - the demo will show why.' The cheat / sysproof / gensrc tiers are capstone slide C's punchline: attacks forced them into existence. Do not pre-introduce them here.\n" +
  "Same column shape (class -> measured how -> judged by -> repair) as capstone slide B, so the audience recognizes it when it returns."
);

const OUT = process.argv[2] || require("path").join(__dirname, "..", "docs", "video_slides_draft.pptx");
pres.writeFile({ fileName: OUT })
  .then(() => console.log("written: " + OUT));
