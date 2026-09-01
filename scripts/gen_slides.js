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

// ---------- Slide 7 (deck position 8): The isolette ----------
let s7 = pres.addSlide();
s7.background = { color: WHITE };

// compact roadmap strip, "Demo" segment active
{
  const stripY = 0.22, stripH = 0.55, gap = 0.14, x0 = 0.7, totalW = 11.9, fs = 9;
  const segW = (totalW - gap * (sections.length - 1)) / sections.length;
  sections.forEach((name, i) => {
    const x = x0 + i * (segW + gap);
    const active = i === 1;
    s7.addShape(pres.ShapeType.roundRect, {
      x, y: stripY, w: segW, h: stripH, rectRadius: 0.05,
      fill: { color: active ? NAVY : "E4EAF4" }, line: { type: "none" },
    });
    s7.addText(name, {
      x, y: stripY, w: segW, h: stripH, fontFace: BODY, fontSize: fs,
      bold: active, color: active ? WHITE : MUTED, align: "center", valign: "middle", margin: 0.02,
    });
  });
}

s7.addText("The isolette", {
  x: 0.7, y: 1.04, w: 8.0, h: 0.7, fontFace: HDR, fontSize: 34, bold: true,
  color: NAVY, margin: 0,
});

// Left half: what it is
const introParas = [
  { text: "The system: ", options: { bold: true, breakLine: false } },
  { text: "an infant-incubator thermostat — regulate and monitor functions keep a newborn's environment in a safe temperature range; heat control on/off", options: { breakLine: true, paraSpaceAfter: 2 } },
  { text: "requirements traceable to FAA AR-08-32 (the REQ-MHS-* family the scenes will tamper with)", options: { fontSize: 11, italic: true, color: MUTED, breakLine: true, paraSpaceAfter: 10 } },
  { text: "The relevance: ", options: { bold: true, breakLine: false } },
  { text: "the INSPECTA program's seL4/Microkit exemplar — a real, current, safety-critical development artifact, not a toy built for this talk", options: { breakLine: false } },
];
introParas[0].options.bullet = { code: "2022" };
introParas[3].options.bullet = { code: "2022" };
s7.addText(introParas, {
  x: 0.62, y: 1.98, w: 6.73, h: 2.5, fontFace: BODY, fontSize: 13.5, color: DARK,
  align: "left", valign: "top", margin: 0,
});

// pipeline graphic
{
  const stages = ["SysMLv2 model\n+ GUMBO contracts", "HAMR\ncodegen", "Verus-verified\nRust", "seL4 / Microkit\ntarget"];
  const py = 4.35, ph = 0.85, pgap = 0.34, px0 = 0.7, ptotal = 6.6;
  const pw = (ptotal - pgap * (stages.length - 1)) / stages.length;
  stages.forEach((t, i) => {
    const x = px0 + i * (pw + pgap);
    s7.addShape(pres.ShapeType.roundRect, {
      x, y: py, w: pw, h: ph, rectRadius: 0.06, fill: { color: MID5 }, line: { type: "none" },
    });
    s7.addText(t, { x, y: py, w: pw, h: ph, fontFace: BODY, fontSize: 10.5, bold: true, color: WHITE, align: "center", valign: "middle", margin: 0.02 });
    if (i < stages.length - 1) {
      s7.addText("→", { x: x + pw - 0.04, y: py, w: pgap + 0.08, h: ph, fontFace: BODY, fontSize: 13, color: MUTED, align: "center", valign: "middle", margin: 0 });
    }
  });
}

s7.addText([
  { text: "Why this example: ", options: { bold: true, bullet: { code: "2022" }, breakLine: false } },
  { text: "every artifact class from the previous slide is present and measured — blessed model, generated contracts, developer-owned implementation, machine-checked proofs, pinned toolchain", options: {} },
], {
  x: 0.7, y: 5.5, w: 6.6, h: 1.2, fontFace: BODY, fontSize: 13.5, color: DARK,
  align: "left", valign: "top", margin: 0,
});

// References footer (K-State HAMR/isolette credits + the pipeline tool papers)
s7.addText([
  { text: "Hatcliff & Belt, ", options: { breakLine: false } },
  { text: "The Isolette System: Illustrating End-to-End Artifacts for Rigorous Model-Based Engineering", options: { italic: true, breakLine: false } },
  { text: ", Springer LNCS 15240, 2025", options: { breakLine: true } },
  { text: "Hatcliff, Belt, Robby, McKenzie, Liang, ", options: { breakLine: false } },
  { text: "End-to-End Formal Methods Integrated Development with SysMLv2 Using HAMR", options: { italic: true, breakLine: false } },
  { text: ", Springer, 2025", options: { breakLine: true } },
  { text: "Hatcliff, Belt, Robby, Carpenter, ", options: { breakLine: false } },
  { text: "HAMR: An AADL Multi-platform Code Generation Toolset", options: { italic: true, breakLine: false } },
  { text: ", ISoLA 2021, LNCS 13036", options: {} },
], {
  x: 0.7, y: 6.82, w: 11.9, h: 0.62, fontFace: BODY, fontSize: 8.5, color: MUTED,
  align: "left", valign: "top", margin: 0,
});

// Right half: the measured surface (big-number callouts)
s7.addText("the measured surface", {
  x: 7.7, y: 1.45, w: 4.9, h: 0.35, fontFace: BODY, fontSize: 13, italic: true, color: MUTED, align: "left", margin: 0,
});
const stats = [
  ["13", "measured files (SysML packages + contract-bearing Rust)"],
  ["67", "contract slices"],
  ["8", "crates re-verified every episode (7 components + the system proof)"],
  ["1,862", "system-proof obligations"],
  ["30", "toolchain + dependency files hashed measure-then-use (4 Verus · 9 HAMR · 17 SysML libs)"],
  ["8", "attestation tiers — the glossary's entry keys:\nprops · l1a · l2 · verus · cheat · sysproof · gensrc · report"],
];
stats.forEach(([num, label], i) => {
  const y = 1.78 + i * 0.82;
  s7.addShape(pres.ShapeType.roundRect, {
    x: 7.7, y, w: 4.9, h: 0.74, rectRadius: 0.06, fill: { color: "F2F4F8" }, line: { color: ICE, width: 1 },
  });
  s7.addText(num, {
    x: 7.85, y, w: 1.35, h: 0.74, fontFace: HDR, fontSize: 26, bold: true, color: NAVY,
    align: "left", valign: "middle", margin: 0,
  });
  s7.addText(label, {
    x: i === 0 ? 8.97 : 9.25, y, w: i === 0 ? 3.58 : 3.3, h: 0.74, fontFace: BODY, fontSize: 10, color: DARK,
    align: "left", valign: "middle", margin: 0,
  });
});

s7.addNotes(
  "This slide IS the section transition into the demo (strip: Demo segment highlighted).\n" +
  "The tiers callout is the bridge: these keys are the glossary's entry keys, and every checklist row in the scenes is one of them.\n" +
  "Spoken line on the why-beat: 'the table you just saw, instantiated.'\n" +
  "Held back on purpose (scene 9's reveal): cheat-tier depth stats - 86 blessed external_body sites, 10 scanned crates.\n" +
  "Numbers verified exact 2026-08-25 (l1a targets, l2 slices, verus term, pub-proof-fn count); provision-dependent - re-verify before recording day."
);

// ---------- Act transition slides I-V (deck positions 9-13) ----------
const ACTS = [
  { num: "ACT I", title: "The consistent baseline", scenes: "scene 1",
    watch: "All artifacts start in a \u201Cpass\u201D state:  all artifacts have integrity against golden values and implementations meet their contracts.",
    cmd: "./examples/demo_isolette.sh --scenes 1",
    notes: "Beats: readiness gate green -> one full episode -> per-crate checklist all green. Dwell on the final checklist - it is the frame every later refusal is compared against." },
  { num: "ACT II", title: "Spec drift: benign, promote then re-verify", scenes: "scene 3 (expand allowed temperature range)",
    watch: "A benign change in requirements — the temperature alarm range widened — model appraisal fails quickly.  Administrator re-blesses new spec, all contract appraisals again pass.",
    cmd: "./examples/demo_isolette.sh --scenes 3 --drift range         (ruling at the prompt: bless)",
    notes: "Single benign beat (per user deck edit, restored 2026-08-27): the Table A-12 upper-alarm ceiling widened 102 -> 103 in the shared GUMBO library constant. Beats: appraisal fails, gumbo_library attributed, all else green (dwell: 'sanction, not semantics') -> ruling diff -> bless -> spec-first green -> promote (real codegen; speed-ramp) -> re-proves ALL GREEN; offered diff = the regenerated shared-library constant. The breaking spec beat lives elsewhere (breaking-impl is Act V/scene 2, breaking-contract is Act IV/scene 14), so Act II stays the clean benign-model story." },
  { num: "ACT III", title: "Implementation drift: benign, re-verify", scenes: "scene 13",
    watch: [
      { text: "A developer rewrites implementation logic — semantically equivalent. The hash moves, but ", options: { italic: true } },
      { text: "every contract slice maintains integrity", options: { bold: true, italic: false } },
      { text: ", and the proofs re-verify: the benign change survives.", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 13",
    notes: "Beats: equivalent NORMAL-mode guard rewrite (x>y -> y<x), outside every marker block -> l1a hash moves -> files entry passes via l2 refinement (slices intact) -> the l1b contracts entry stays clean -> confirmation chain RE-VERIFIES the rewrite green. The mirror of Act II's benign spec beat, one artifact class down: a developer-owned region has no blessed bytes to match, so its attested properties are contracts (intact) + provability (re-verified live)." },
  { num: "ACT IV", title: "Contract drift: breaking, restore then attempt re-verification", scenes: "scene 14",
    watch: [
      { text: "The model is untouched, but a Verus contract is weakened (", options: { italic: true } },
      { text: "after codegen, but before verification", options: { bold: true, italic: true } },
      { text: ") and the code is inverted to match — verus checks pass.  Contract repair (restoring the true Verus contract) exposes the verification failure.", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 14",
    notes: "The report emits NO slice for compute_cases realizations, so the weakened REQ_MHS_2 lands between l2 slices. Beats: launder (weaken REQ_MHS_2 ensures + invert impl) -> cargo-verus SUCCEEDS (self-consistent) -> the l1b MARKER tier (a new Copland protocol: readfile_marker_range over every contract-block byte) refuses -> its repair rung splices the golden contract back -> the restored TRUE contract refutes the still-inverted impl: end on the exposed Verus refusal (verus_targ Appraisal was not successful). Discovered while building this demo; the marker-coverage lint now enforces the invariant. Do NOT auto-repair to green - the exposure IS the beat; the impl repair is Act V's ladder. Slide-C candidate row." },
  { num: "ACT V", title: "Implementation drift: breaking, diagnose then repair", scenes: "scene 2",
    watch: [
      { text: "Implementation code (developer-owned) changes, breaking a Verus contract.  Blackboard loop diagnoses, repairs (simulated for demo), then ", options: { italic: true } },
      { text: "returns the artifact to good standing only by re-measurement", options: { bold: true, italic: true } },
      { text: ".", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 2",
    notes: "Beats: dummy-bad-impl diff (take the [v]iew - VSCode diff D1 on camera) -> contracts-intact rung exhausts -> impl rung restores crate-scoped -> restart -> re-attested clean." },
  { num: "ACT VI", title: "Baseline drift:  tampered evidence bundle, protocol, tooling", scenes: "scenes 6 + 7",
    watch: "The signed golden evidence bundle, an installed golden value in the protocol ASP ARGS, then the verifier itself — each tamper attributed, each refused by cryptographic checks.",
    cmd: "./examples/demo_isolette.sh --scenes \"6 7\"",
    notes: "Scene 6 beats: three tampers, three attributed refusals (signature -> anchor -> derivability); optionally the flipped-evidence-byte diff on camera. Scene 7 beats: wrapper edit (take the [v]iew, diff D10) -> readiness still passes -> tool hash refutes, every proof cell poisons to ? - dwell, this is the act's money shot. --restore-tools recovery in VO only." },
  { num: "ACT VII", title: "Axiom drift:  semantic measurement detects axioms and unsound proof techniques", scenes: "scenes 9 + 12",
    watch: [
      { text: "Proofs verify, but measurement detects ", options: { italic: true } },
      { text: "subtle ways that proof attempts cheat ", options: { bold: true } },
      { text: "to undermine verification soundness.", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes \"9 12\"",
    notes: "The detector escalation that closes the demo. BEAT 1 (scene 9, axioms): two-grid view - the verus grid all green (cargo-verus succeeds) beside the proof-escape grid refusing the exact crate and naming the construct (ADMIT: assume 0->1; SMUGGLE: broadcast 0->1, external_body 0->1). The CHEAT SCAN catches what the outcome cannot - a construct appeared. BEAT 2 (scene 12, FFI): the heat command inverted behind external_body (diff D18) -> every proof passes AND the cheat scan is SILENT (no construct) -> only the GENSRC byte anchor refuses, naming the file -> diagnosis rung classifies -> repair by regeneration (speed-ramp). Three detectors, three blind spots: outcome (blind to both), construct scan (catches beat 1), byte anchor (catches beat 2). Close naming scenes 10-11 (slide C carries the rest)." },
];
ACTS.forEach((act) => {
  const sa = pres.addSlide();
  sa.background = { color: WHITE };
  // compact roadmap strip, Demo active
  const stripY = 0.22, stripH = 0.55, sgap = 0.14, sx0 = 0.7, stotalW = 11.9, sfs = 9;
  const ssegW = (stotalW - sgap * (sections.length - 1)) / sections.length;
  sections.forEach((name, i) => {
    const x = sx0 + i * (ssegW + sgap);
    const active = i === 1;
    sa.addShape(pres.ShapeType.roundRect, {
      x, y: stripY, w: ssegW, h: stripH, rectRadius: 0.05,
      fill: { color: active ? NAVY : "E4EAF4" }, line: { type: "none" },
    });
    sa.addText(name, {
      x, y: stripY, w: ssegW, h: stripH, fontFace: BODY, fontSize: sfs,
      bold: active, color: active ? WHITE : MUTED, align: "center", valign: "middle", margin: 0.02,
    });
  });
  sa.addText(act.num, {
    x: 0.9, y: 2.0, w: 11.5, h: 0.5, fontFace: BODY, fontSize: 18, bold: true,
    color: MUTED, charSpacing: 3, margin: 0,
  });
  sa.addText(act.title, {
    x: 0.9, y: 2.5, w: 11.5, h: 0.9, fontFace: HDR, fontSize: 40, bold: true,
    color: NAVY, margin: 0,
  });
  sa.addText(act.scenes, {
    x: 0.9, y: 3.45, w: 11.5, h: 0.45, fontFace: BODY, fontSize: 15, italic: true,
    color: MUTED, margin: 0,
  });
  sa.addText(act.watch, {
    x: 0.9, y: 4.35, w: 11.2, h: 1.4, fontFace: BODY, fontSize: 20, italic: true,
    color: DARK, margin: 0,
  });
  sa.addText(act.cmd, {
    x: 0.9, y: 6.62, w: 11.5, h: 0.66, fontFace: "Courier New", fontSize: 11,
    color: MUTED, margin: 0,
  });
  sa.addNotes(act.notes + "\nWatch-for line doubles as the VO opener over the terminal cut. Full runbook: docs/video_recording_plan.md.");
});

// ---------- Ecosystems: one blackboard, many artifact pipelines (card grid) ----------
{
  const TINT = "F2F4F8", MID_E = "3A4A8C";
  const seco = pres.addSlide();
  seco.background = { color: WHITE };
  seco.addText("One blackboard, many artifact pipelines", {
    x: 0.7, y: 0.4, w: 12.0, h: 0.7, fontFace: HDR, fontSize: 34, bold: true, color: NAVY, margin: 0,
  });
  seco.addText([
    { text: "The blackboard, controller, repair ladder, and artifact classes don\u2019t change \u2014 only the ", options: {} },
    { text: "pipeline around them does", options: { bold: true } },
    { text: ": the modeling language, the prover, the target runtime, and the attestation primitives.", options: {} },
  ], { x: 0.7, y: 1.12, w: 12.0, h: 0.5, fontFace: BODY, fontSize: 15, italic: true, color: DARK, margin: 0 });

  const cards = [
    { header: "SysML v2 \u2192 HAMR \u2192 Rust / Verus", caption: "isolette", badge: "the demo", ref: true,
      bullets: ["SysMLv2 GUMBO component contracts", "seL4 / Microkit runtime target", "Every artifact class measured \u2014 the full demo"] },
    { header: "AADL \u2192 HAMR \u2192 Slang / Logika", caption: "temp-control",
      bullets: ["AADL GUMBO component contracts", "JVM runtime target", "Same blackboard, similar Copland protocols"] },
    { header: "Standalone Rust / Verus", caption: "find-max-verus",
      bullets: ["Contracts + proofs written directly in Verus", "No model, no codegen \u2014 implementation + proof classes only", "Proof-repair experiments: AutoVerus, KU Dogtreat linear planner"] },
    { header: "Interactive Theorem Provers:  Lean / Rocq", caption: "landing-gear, temp-control",
      bullets: ["Blessed theorem statements, workflow-owned implementations, proofs", "Tactic-driven and LLM-driven proof repair", "Goal-directed: attestation enforces one invariant while synthesis iterates", "ITP-specific axiom checks"] },
  ];
  const CW = 5.85, CH = 2.35, GX = 0.7, GY = 1.8, gapx = 0.3, gapy = 0.3;
  cards.forEach((c, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = GX + col * (CW + gapx), y = GY + row * (CH + gapy);
    seco.addShape(pres.ShapeType.roundRect, {
      x, y, w: CW, h: CH, rectRadius: 0.06,
      fill: { color: c.ref ? NAVY : TINT }, line: c.ref ? { type: "none" } : { color: ICE, width: 1 },
    });
    seco.addText(c.header, {
      x: x + 0.25, y: y + 0.12, w: CW - 0.5, h: 0.36, fontFace: BODY, fontSize: 15.5,
      bold: true, color: c.ref ? WHITE : NAVY, align: "left", valign: "middle", margin: 0,
    });
    const capRuns = [{ text: c.caption, options: { italic: true, fontSize: 10.5, color: c.ref ? ICE : MUTED } }];
    if (c.badge) capRuns.push({ text: "   \u25c0 " + c.badge, options: { bold: true, italic: true, fontSize: 10.5, color: ICE } });
    seco.addText(capRuns, { x: x + 0.26, y: y + 0.5, w: CW - 0.5, h: 0.28, fontFace: BODY, align: "left", valign: "middle", margin: 0 });
    const paras = [];
    c.bullets.forEach((b, j) => {
      paras.push({ text: b, options: {
        bullet: { code: "2022" }, color: c.ref ? ICE : DARK, fontSize: 12,
        breakLine: j !== c.bullets.length - 1, paraSpaceAfter: 4 } });
    });
    seco.addText(paras, { x: x + 0.3, y: y + 0.85, w: CW - 0.55, h: CH - 0.98, fontFace: BODY, align: "left", valign: "top", margin: 0 });
  });
  seco.addNotes(
    "High-level breadth slide (section 3 opener) - card grid, per user edits 2026-08-30. Four artifact pipelines: the isolette (SysML->HAMR->Rust/Verus, the demo, highlighted), AADL->HAMR->Slang/Logika (temp-control), standalone Rust/Verus (find-max-verus; AutoVerus + KU Dogtreat repair experiments), and the interactive theorem provers Lean & Rocq (blessed statements, tactic/LLM repair). Title = the artifact pipeline; caption = example system(s). Repair-strategy breadth lands per-card where it defines the ecosystem."
  );
}

// ---------- Capstone A: AI in the loop (untrusted synthesis, deterministic audit) ----------
{
  const TINT = "E4E7EF";
  const sa = pres.addSlide();
  sa.background = { color: WHITE };
  sa.addText([
    { text: "AI ", options: {} },
    { text: "in", options: { italic: true } },
    { text: " the loop", options: {} },
  ], { x: 0.7, y: 0.38, w: 12.0, h: 0.7, fontFace: HDR, fontSize: 40, bold: true, color: NAVY, margin: 0 });
  sa.addText("untrusted artifact synthesis/repair;  verified, deterministic appraisal", {
    x: 0.72, y: 1.12, w: 12.0, h: 0.45, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0,
  });

  const th = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 13.5, align: "left", valign: "middle" } });
  const td = (runs, fill) => ({ text: runs, options: { fill: { color: fill || WHITE }, color: DARK, fontSize: 12, align: "left", valign: "middle" } });
  const B = (t) => ({ text: t, options: { bold: true } });
  const P = (t) => ({ text: t, options: {} });

  const rows = [
    [th("Workflow stage"), th("Where AI participates"), th("The rule")],
    [td([B("Model / spec")]),
     td([P("LLMs may draft or restate specs")]),
     td([P("only the administrator "), B("blesses"), P(" \u2014 authority is human")])],
    [td([B("Implementation")]),
     td([P("spec-guided synthesis / re-derivation with LLM engines")]),
     td([P("the seed proofs must prove again against the blessed statements")])],
    [td([B("Proofs")]),
     td([P("LLM-suggested tactic portfolio (deterministic at runtime) \u00b7 LLM API calls + LLM-assisted desktop sessions (loop is paused) \u00b7 Custom proof repair agents (AutoVerus \u00b7 KU Dogtreat linear planner)")]),
     td([P("a repair claim is worthless without evidence; only fresh measurement re-establishes good standing")])],
    [td([B("Verification & appraisal")], TINT),
     td([B("none \u2014 by design")], TINT),
     td([P("deterministic judges: proof kernels (Rocq, Lean, Verus), hash appraisal vs signed goldens, semantic analysis of source code")], TINT)],
    [td([B("Evidence / trust state")], TINT),
     td([B("none \u2014 by design")], TINT),
     td([P("cryptographic anchor \u00b7 non-derivability; no one (human or AI) may repair a baseline without fresh administrator blessing")], TINT)],
  ];
  sa.addTable(rows, {
    x: 0.7, y: 1.75, w: 11.9, colW: [2.5, 4.9, 4.5],
    border: { type: "solid", color: "D8DEEA", pt: 1 },
    rowH: [0.4, 0.62, 0.62, 1.0, 0.72, 0.72], margin: 0.09, fontFace: BODY,
  });

  sa.addText([
    { text: "\uD83D\uDD12  the bottom two \u2014 the judges \u2014 are AI-free by design", options: { bold: true, color: NAVY } },
    { text: ":  an LLM\u2019s output is just another untrusted artifact, facing the same episode and appraisal as a human edit or a tamper. Guarantees never depend on LLM engines being good, honest, or even present.", options: { color: DARK } },
  ], { x: 0.7, y: 6.55, w: 11.9, h: 0.75, fontFace: BODY, fontSize: 12.5, italic: true, align: "left", valign: "top", margin: 0 });

  sa.addNotes(
    "Capstone slide 1 of 3 (theme: 'AI in the loop' as the big title, a descriptive caption beneath - B and C reuse the header).\n" +
    "One idea: AI helps everywhere EXCEPT the judges. The top three stages (model, implementation, proofs) are AI-assisted; the bottom two (verification/appraisal, evidence/trust state) are AI-free by design - the shaded band.\n" +
    "The Proofs row is where the repair-strategy breadth lands (deferred from the ecosystems slide): tactic portfolio, LLM (API + desktop sessions), AutoVerus, KU Dogtreat linear planner.\n" +
    "Motivation flip (speaker, sets up the close): as more lifecycle artifacts ARE AI-generated, lifecycle attestation is what makes them trustworthy - provenance and evidence, not provider assurances."
  );
}

// ---------- Capstone B: AI built the loop ----------
{
  const sb = pres.addSlide();
  sb.background = { color: WHITE };
  sb.addText([
    { text: "AI ", options: {} },
    { text: "built", options: { italic: true } },
    { text: " the loop", options: {} },
  ], { x: 0.7, y: 0.38, w: 12.0, h: 0.7, fontFace: HDR, fontSize: 40, bold: true, color: NAVY, margin: 0 });
  sb.addText("blackboard and attestation infrastructure, artifact measurements, attestation protocols, attacks", { x: 0.72, y: 1.12, w: 12.0, h: 0.45, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0 });

  const th = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 13.5, align: "left", valign: "middle" } });
  const td = (runs) => ({ text: runs, options: { fill: { color: WHITE }, color: DARK, fontSize: 12, align: "left", valign: "middle" } });
  const B = (t) => ({ text: t, options: { bold: true } });
  const I = (t) => ({ text: t, options: { italic: true } });
  const P = (t) => ({ text: t, options: {} });

  const rows = [
    [th("What AI built"), th(""), th("Judged by")],
    [td([B("Blackboard infrastructure")]),
     td([P("pybb framework (blackboard / controller / knowledge sources), demo arcs, install script, CI suite, detailed documentation")]),
     td([P("Untrusted orchestration (evidence bundles are independently-verifiable)")])],
    [td([B("CVM core & frontends")]),
     td([P("bpar (parallel Copland term) "), I("in the verified CVM"), P("; --stdin / --req_file frontend fixes")]),
     td([B("Rocq proofs w.r.t. CVM reference semantics --"), P("Claude couldn\u2019t update existing proofs automatically, but assisted an expert Rocq developer")])],
    [td([B("Measurement primitives")]),
     td([B("12 new + 7 upgraded"), P(" asp-libs binaries \u2014 hashing, the Lean/Rocq/HAMR runners & appraisers, the cheat scan, golden-slice extraction")]),
     td([P("tool hashes measure-then-use; syntax-guided analysis of source files, appraisal vs signed goldens")])],
    [td([B("Attestation protocols")]),
     td([B("42 provisioned"), P(" Copland protocol directories across the ecosystems")]),
     td([P("readiness-gate config checks; blessed baselines")])],
    [td([B("Attacks")]),
     td([P("scripted demo tampers (scenes 1\u20138) + "), B("7 red-team attack classes"), P(" (scenes 9\u201312, 14)")]),
     td([P("every scene gates on detection / attribution; each forced a new tier ("), I("\u2192 next slide"), P(")")])],
  ];
  sb.addTable(rows, {
    x: 0.7, y: 1.75, w: 11.9, colW: [2.6, 5.6, 3.7],
    border: { type: "solid", color: "D8DEEA", pt: 1 },
    rowH: [0.4, 0.7, 0.72, 0.92, 0.62, 0.82], margin: 0.09, fontFace: BODY,
  });

  sb.addText([
    { text: "A virtuous cycle \u2013 ", options: { bold: true } },
    { text: "AI-assisted workflow to add (deterministic) tools and domain-specific measurement capabilities.  ", options: {} },
  ], { x: 0.7, y: 6.7, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 13.5, italic: true, color: NAVY, align: "left", margin: 0 });

  sb.addNotes(
    "Capstone slide 2 of 3 (theme: 'AI in the loop' big title + caption). The one idea: AI built the entire attestation stack, and that stack is held to the same measured discipline it enforces.\n" +
    "Counts current 2026-08-30: 12 new + 7 upgraded asp-libs binaries (git-attested, separate repo); 42 provisioned Copland protocol dirs (the newest, the l1b marker tier, was built in this very session - a callback available if wanted); 7 red-team attack classes.\n" +
    "cvm-mcp aside (15 s): an AI-built MCP interface so AI agents can drive attestation - AI both built the loop and can drive it.\n" +
    "Git provenance deliberately de-emphasized per user; the point is the self-application (the reflexive footer), not the Co-Authored-By trailers."
  );
}

// ---------- Capstone C: AI attacked the loop ----------
{
  const HILITE = "EDEFF4";
  const sc = pres.addSlide();
  sc.background = { color: WHITE };
  sc.addText([
    { text: "AI ", options: {} },
    { text: "attacked", options: { italic: true } },
    { text: " the loop", options: {} },
  ], { x: 0.7, y: 0.38, w: 12.0, h: 0.7, fontFace: HDR, fontSize: 40, bold: true, color: NAVY, margin: 0 });
  sc.addText("seven attack types, each undetected at discovery time \u2014 each forced a new measurement capability", {
    x: 0.72, y: 1.12, w: 12.0, h: 0.45, fontFace: BODY, fontSize: 16, italic: true, color: MUTED, margin: 0,
  });

  const th = (t) => ({ text: t, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 12.5, align: "left", valign: "middle" } });
  const td = (runs, fill) => ({ text: runs, options: { fill: { color: fill || WHITE }, color: DARK, fontSize: 11, align: "left", valign: "middle" } });
  const B = (t) => ({ text: t, options: { bold: true } });
  const P = (t) => ({ text: t, options: {} });

  const rows = [
    [th("Attack"), th("Avoided detection by\u2026"), th("New measurement forced")],
    [td([B("ADMIT"), P(" \u2014 assume(false) in an unmeasured bridge file")]),
     td([P("cargo-verus reports the same success over the hollow proof")]),
     td([P("cheat scan (cheat_scan_verus)")])],
    [td([B("SMUGGLE"), P(" \u2014 external_body broadcast axiom, ensures false")]),
     td([P("cargo-verus reports the same success over the hollow proof")]),
     td([P("cheat scan (cheat_scan_verus)")])],
    [td([B("SHRINK"), P(" \u2014 a system-proof module commented out")]),
     td([P("smaller crate still verifies, 0 errors")]),
     td([P("sysproof file hashes")])],
    [td([B("SWAP"), P(" \u2014 real VC dropped, trivial one added, constant count")]),
     td([P("outcome, count, escape surface all unchanged")]),
     td([P("sysproof file hashes")])],
    [td([B("STALE"), P(" \u2014 semantic flip in a cached dep, mtime preserved")]),
     td([P("mtime-gated cache serves the stale verdict; green over false bytes")]),
     td([P("gensrc measurement")])],
    [td([B("INVERT"), P(" \u2014 heat command flipped in unverified FFI glue")]),
     td([P("Verus never reads the body \u2014 unverified code, out of scope")]),
     td([P("gensrc measurement")])],
    [td([B("LAUNDER"), P(" \u2014 contract weakened + impl inverted to match")], HILITE),
     td([P("self-consistent; gap in contract coverage for attestation report\u2019s compute_cases construct")], HILITE),
     td([P("stopgap contract measurement, contract coverage check at provisioning")], HILITE)],
  ];
  sc.addTable(rows, {
    x: 0.7, y: 1.7, w: 11.9, colW: [3.95, 4.45, 3.5],
    border: { type: "solid", color: "D8DEEA", pt: 1 },
    rowH: [0.36, 0.55, 0.55, 0.5, 0.6, 0.62, 0.62, 0.86], margin: 0.08, fontFace: BODY,
  });

  sc.addText([
    { text: "Adversarial co-development", options: { bold: true } },
    { text: " \u2014 defense-in-depth, anomaly detection, mitigation.", options: {} },
  ], { x: 0.7, y: 6.72, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 13.5, italic: true, color: NAVY, align: "left", margin: 0 });

  sc.addNotes(
    "Capstone slide 3 of 3 (title 'AI attacked the loop'). The same sessions red-teamed the stack they built; every attack was green across every EXISTING tier when found, and each forced a new measurement capability - defense-in-depth measured into existence.\n" +
    "7 attacks -> 4 measurement capabilities: cheat scan (ADMIT, SMUGGLE), sysproof file hashes (SHRINK, SWAP), gensrc measurement (STALE, INVERT), and the l1b marker tier + coverage lint (LAUNDER, highlighted - found this session).\n" +
    "STALE vs INVERT are two different blind spots of 'verification succeeded': STALE = a stale cached verdict (verified over old bytes); INVERT = unverified code out of the proof's scope. Same detector (gensrc bytes), different evasion.\n" +
    "LAUNDER is the reflexive one: it exposed a COVERAGE gap in the measurement itself (the report emits no compute_cases slice), so it forced a detector PLUS a provisioning invariant. Root cause is upstream (HAMR report emission) - see draft_hamr_report_contract_coverage.md.\n" +
    "Speaker: the escalating lesson of 9->12 is that 'verification succeeded' and 'no cheats present' are both weaker claims than 'these are the blessed bytes.'"
  );
}

// ---------- References (deck final slide) ----------
// Collects ALL deck references; add new entries here as the deck grows.
let sref = pres.addSlide();
sref.background = { color: WHITE };
sref.addText("References", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});

const refGroups = [
  ["The isolette & HAMR (Kansas State)", [
    [["Hatcliff & Belt, ", 0], ["The Isolette System: Illustrating End-to-End Artifacts for Rigorous Model-Based Engineering", 1], [", Springer LNCS 15240, 2025", 0]],
    [["Hatcliff, Belt, Robby, McKenzie, Liang, ", 0], ["End-to-End Formal Methods Integrated Development with SysMLv2 Using HAMR", 1], [", Springer, 2025", 0]],
    [["Hatcliff, Belt, Robby, Carpenter, ", 0], ["HAMR: An AADL Multi-platform Code Generation Toolset", 1], [", ISoLA 2021, LNCS 13036, pp. 274\u2013295", 0]],
    [["Lempia & Miller, ", 0], ["Requirements Engineering Management Handbook", 1], [", DOT/FAA/AR-08/32, 2009", 0]],
    [["INSPECTA models: github.com/loonwerks/INSPECTA-models", 0]],
  ]],
  ["Attestation foundations", [
    [["Ramsdell, Rowe, Alexander, Helble, Loscocco, Pendergrass, Petz, ", 0], ["Orchestrating Layered Attestations", 1], [", POST 2019, LNCS 11426", 0]],
  ]],
  ["Verification & platform", [
    [["Lattuada, Hance, Cho, Brun, Subasinghe, Zhou, Howell, Parno, Hawblitzel, ", 0], ["Verus: Verifying Rust Programs using Linear Ghost Types", 1], [", PACMPL 7 (OOPSLA1), 2023", 0]],
    [["Klein et al., ", 0], ["seL4: Formal Verification of an OS Kernel", 1], [", SOSP 2009", 0]],
  ]],
];
let refParas = [];
refGroups.forEach(([group, refs], gi) => {
  refParas.push({ text: group, options: { bold: true, color: NAVY, fontSize: 14, breakLine: true, paraSpaceBefore: gi === 0 ? 0 : 12, paraSpaceAfter: 4 } });
  refs.forEach((runs) => {
    runs.forEach(([text, ital], j) => {
      refParas.push({ text, options: { italic: ital === 1, color: DARK, fontSize: 11.5, bullet: j === 0 ? { code: "2022" } : undefined, indentLevel: j === 0 ? 0 : undefined, breakLine: j === runs.length - 1, paraSpaceAfter: 3 } });
    });
  });
});
refParas[refParas.length - 1].options.breakLine = false;
sref.addText(refParas, {
  x: 0.7, y: 1.5, w: 12.0, h: 5.6, fontFace: BODY, align: "left", valign: "top", margin: 0,
});
sref.addNotes(
  "Collection point for every reference in the deck - keep this slide current as sections are added (isolette slide carries the K-State + AR-08-32 citations inline; Copland/Verus/seL4 seeded here ahead of their sections).\n" +
  "DOIs on record in docs/video_slide_drafts.md."
);

const OUT = process.argv[2] || require("path").join(__dirname, "..", "docs", "video_slides_draft.pptx");
pres.writeFile({ fileName: OUT })
  .then(() => console.log("written: " + OUT));
