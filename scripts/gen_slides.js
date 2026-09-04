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
// Compact roadmap strip at the top of the demo slides (isolette + act transitions).
// Off for now per user 2026-09-04: it only appeared in the demo portion, which read as confusing.
// The full Roadmap slide (deck position 2) is unaffected. Flip to true to restore the strips.
const SHOW_COMPACT_STRIP = false;

// ---------- Slide 1: Title ----------
let s1 = pres.addSlide();
s1.background = { color: NAVY };
// Title with an inline lowercase gloss on the tool name, set small/italic/ice so it
// reads as an aside (same face + color as the subtitle). Box widened to 12.0 so the
// whole line stays on one line. Per user edits 2026-09-03: the letters that spell
// "pybb" (py-b-b) are enlarged to 36pt bold inside the gloss.
const gloss = (t) => ({ text: t, options: { fontFace: BODY, fontSize: 22, italic: true, color: ICE } });
const glossBig = (t) => ({ text: t, options: { fontFace: BODY, fontSize: 36, bold: true, italic: true, color: ICE } });
s1.addText([
  { text: "Lifecycle Attestation with pybb", options: { fontFace: HDR, fontSize: 44, bold: true, color: WHITE } },
  gloss(" ("), glossBig("py"), gloss("thon "), glossBig("b"), gloss("lack"), glossBig("b"), gloss("oard)"),
], {
  x: 0.9, y: 2.4, w: 12.0, h: 1.2, align: "left", margin: 0,
});
// Subtitle: two centered lines, wording per user edits 2026-09-03.
s1.addText([
  { text: "Measured trust across models, contracts, code, and proofs in ", options: { breakLine: true } },
  { text: "high assurance, LLM-assisted development pipelines" },
], {
  x: 0.9, y: 3.6, w: 11.5, h: 0.6, fontFace: BODY, fontSize: 20, italic: true,
  color: ICE, align: "center", margin: 0,
});
// Author list (from the paper's IEEE author block; affiliations as numbered superscripts).
// To add an author: append { name, aff } (aff = index into AFFILS, 1-based).
// newLine: true starts a fresh line before that author (keeps the wrap tidy).
const AFFILS = ["University of Kansas", "Collins Aerospace", "Kansas State University"];
const AUTHORS = [
  { name: "Adam Petz", aff: 1 },
  { name: "Isaac Amundson", aff: 2 },
  { name: "Timothy Barclay", aff: 2 },
  { name: "David Hardin", aff: 2 },
  { name: "Jason Belt", aff: 3 },
  { name: "John Hatcliff", aff: 3 },
  { name: "Anakha Krishna", aff: 1, newLine: true },
  { name: "Ina Harris", aff: 1 },
  { name: "Perry Alexander", aff: 1 },
];
const DATE = "September 2026";
// Sponsor acknowledgment, wording from the HCSS 2026 paper's \thanks{} (hcss26.tex).
const SPONSOR = "Supported by the DARPA PROVERS effort (contract FA8750-24-9-1000)";
const authorRuns = [];
AUTHORS.forEach((a, i) => {
  if (a.newLine) authorRuns.push({ text: ",", options: { color: ICE, breakLine: true } });
  authorRuns.push({ text: (i && !a.newLine ? ", " : "") + a.name, options: { color: ICE } });
  authorRuns.push({ text: String(a.aff), options: { color: ICE, superscript: true } });
});
const affilRuns = [];
AFFILS.forEach((name, i) => {
  affilRuns.push({ text: (i ? "    " : "") + String(i + 1), options: { color: ICE, superscript: true } });
  affilRuns.push({ text: name, options: { color: ICE } });
});
s1.addText(authorRuns, {
  // Bottom-anchored tall box: extra authors wrap onto a second line that grows upward.
  x: 0.9, y: 5.2, w: 11.5, h: 0.95, fontFace: BODY, fontSize: 16, color: ICE,
  align: "left", valign: "bottom", margin: 0,
});
s1.addText(affilRuns, {
  x: 0.9, y: 6.2, w: 11.5, h: 0.35, fontFace: BODY, fontSize: 13, color: ICE,
  align: "left", margin: 0,
});
s1.addText(DATE, {
  x: 0.9, y: 6.6, w: 5.0, h: 0.35, fontFace: BODY, fontSize: 13, color: ICE,
  align: "left", margin: 0,
});
s1.addText(SPONSOR, {
  x: 5.9, y: 6.6, w: 6.5, h: 0.35, fontFace: BODY, fontSize: 12, color: ICE,
  align: "right", margin: 0,
});
s1.addNotes("Title card. Subtitle deliberately names the four core artifact classes - the deck's first echo of the artifact-class table (slide 6). Footer: DARPA PROVERS sponsor acknowledgment with contract number (INSPECTA is the team's project under PROVERS).");

// ---------- Slide 2 (deck position 2; swapped before the lifecycle slide per user edits 2026-09-03): Roadmap strip ----------
let s2 = pres.addSlide();
s2.background = { color: WHITE };
s2.addText("Roadmap", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});

const sections = ["Preliminaries", "Demo:\nIsolette (SysMLv2 \u2192 Rust)", "Other Ecosystems", "AI in the Loop", "Close"];
const stripY = 3.1, stripH = 0.85, gap = 0.18, x0 = 0.7, totalW = 11.9;
const segW = (totalW - gap * (sections.length - 1)) / sections.length;
sections.forEach((name, i) => {
  const x = x0 + i * (segW + gap);
  const active = i === 0;
  s2.addShape(pres.ShapeType.roundRect, {
    x, y: stripY, w: segW, h: stripH, rectRadius: 0.07,
    fill: { color: active ? NAVY : ICE }, line: { type: "none" },
  });
  s2.addText(name, {
    x, y: stripY, w: segW, h: stripH, fontFace: BODY, fontSize: 13.5,
    bold: active, color: active ? WHITE : NAVY, align: "center", valign: "middle", margin: 0.02,
  });
  if (i < sections.length - 1) {
    s2.addText("→", {
      x: x + segW - 0.06, y: stripY, w: gap + 0.12, h: stripH, fontFace: BODY,
      fontSize: 14, color: MUTED, align: "center", valign: "middle", margin: 0,
    });
  }
});
// ("Section headers provisional" caption removed per user edits 2026-09-03.)
s2.addNotes(
  "~15 seconds on first appearance; afterwards it rides on transition slides for free.\n" +
  "Design decision: one master/layout holds the strip text so a section rename is a single edit. Header titles are provisional."
);

// ---------- Slide 3 (deck position 3; swapped after Roadmap per user edits 2026-09-03): What is lifecycle attestation? ----------
let s3 = pres.addSlide();
s3.background = { color: WHITE };
s3.addText("What is Lifecycle Attestation?", {
  x: 0.7, y: 0.45, w: 12.0, h: 0.8, fontFace: HDR, fontSize: 36, bold: true,
  color: NAVY, margin: 0,
});
// build bullets as rich text runs
const bullets = [
  // Emphasis per user edits 2026-09-03: lead-in labels are NOT bold (only the
  // ": " separator kept bold, as in the PowerPoint-saved deck); bold is reserved
  // for the key phrases inside each bullet.
  { runs: [
      { text: "Traditional remote attestation: did system components boot into a predictable state? (boot-time, static runtime)", options: {} },
    ], indent: 0 },
  { runs: [
      { text: "Layered, runtime attestation", options: {} },
      { text: ": ", options: { bold: true } },
      { text: "extend boot-time trust via dynamic measurement of system components and their context/dependencies", options: {} },
      { text: " [1]", options: { color: MUTED } }, // Thomas et al., Designing Trustworthy Layered Attestations (arXiv 2026) — first citation in the deck
    ], indent: 0 },
  { runs: [
      { text: "Lifecycle attestation", options: {} },
      { text: ": ", options: { bold: true } },
      { text: "extends this notion to ", options: {} },
      { text: "artifacts of the development lifecycle", options: { bold: true } },
      { text: ": models, contracts, implementations, proofs, toolchains", options: {} },
    ], indent: 0 },
  { runs: [
      { text: "…including the attestation infrastructure and evidence itself", options: {} },
    ], indent: 1 },
  { runs: [
      { text: "…and to natural lifecycle events:", options: {} },
    ], indent: 1 },
  { runs: [{ text: "specification drift ", options: {} }], indent: 2 },
  { runs: [{ text: "toolchain updates", options: {} }], indent: 2 },
  { runs: [{ text: "artifact updates, synthesis, repair", options: {} }], indent: 2 },
  { runs: [
      { text: "Motivation", options: {} },
      { text: ": ", options: { bold: true } },
      { text: "the ", options: {} },
      { text: "proliferation of AI-generated software artifacts", options: { bold: true } },
      { text: ", amid the need for ", options: {} },
      { text: "rapid re-certification of systems", options: { bold: true } },
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

s3.addText(paras, {
  x: 0.7, y: 1.45, w: 12.0, h: 3.9, fontFace: BODY, fontSize: 17, color: DARK,
  align: "left", valign: "top", margin: 0,
});

// Banner
s3.addShape(pres.ShapeType.roundRect, {
  x: 0.7, y: 5.36, w: 11.9, h: 1.35, fill: { color: NAVY }, rectRadius: 0.08, line: { type: "none" },
});
s3.addText([
  { text: "Every trust decision is grounded in cryptographic attestation evidence.", options: { bold: true, fontSize: 20, color: WHITE, breakLine: true, paraSpaceAfter: 4 } },
  { text: "Trust is NOT anchored in the following:  developer claims, untrusted tools, LLM outputs, cached verdicts", options: { italic: true, fontSize: 14, color: ICE } },
], {
  x: 1.0, y: 5.36, w: 11.3, h: 1.35, fontFace: BODY, align: "center", valign: "middle", margin: 0,
});
s3.addNotes(
  "Promise the audience every demo scene echoes the banner.\n" +
  "The administrator's bless survives 'every': authority enters the system only AS signed evidence (the blessed baseline), never by assertion - scene 6's laundering beat proves exactly that.\n" +
  "Subline payoffs: developer claims -> scenes 5/7; untrusted tools -> scene 7; LLM outputs -> capstone slides A/B; cached verdicts -> scene 11.\n" +
  "Visual TODO: three-stage widening-scope progression (boot-time -> layered runtime -> lifecycle loop) to replace/join the bullets."
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
// Numbered citations (2026-09-04): "[n]" at the surrounding text size, muted/ice, on first mention only;
// numbers index the References slide (kept grouped there, so they appear out of order on it).
// [1] layered attestations (slide 3) · [2] Copland paper · [3] CVM repo · [4] SEFM'24 (CVM box) · [5] asp-libs repo · [6] ISSE'22 (output box) · [7]-[13] isolette slide.
s4.addText([
  { text: "Copland", options: { bold: true, fontSize: 17, color: WHITE } },
  { text: " [2]", options: { fontSize: 17, color: ICE, breakLine: true, paraSpaceAfter: 2 } },
  { text: "attestation protocols as formal terms with an evidence semantics", options: { fontSize: 12, color: ICE } },
], { x: LX + 0.25, y: 1.45, w: LW - 0.5, h: 1.1, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

s4.addText("▼", { x: LX + LW / 2 - 0.2, y: 2.56, w: 0.4, h: 0.28, fontSize: 12, color: MUTED, align: "center", margin: 0 });

// CVM layer
s4.addShape(pres.ShapeType.roundRect, {
  x: LX, y: 2.85, w: LW, h: 1.1, rectRadius: 0.07, fill: { color: "3A4A8C" }, line: { type: "none" },
});
s4.addText([
  { text: "Copland Virtual Machine (CVM)", options: { bold: true, fontSize: 17, color: WHITE } },
  { text: " [3,4]", options: { fontSize: 17, color: ICE, breakLine: true, paraSpaceAfter: 2 } },
  { text: "executes Copland phrases · dispatches ASPs according to manifest configurations · appraises results", options: { fontSize: 12, color: ICE } },
], { x: LX + 0.25, y: 2.85, w: LW - 0.5, h: 1.1, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

s4.addText("▼", { x: LX + LW / 2 - 0.2, y: 3.96, w: 0.4, h: 0.28, fontSize: 12, color: MUTED, align: "center", margin: 0 });

// asp-libs layer
s4.addShape(pres.ShapeType.roundRect, {
  x: LX, y: 4.25, w: LW, h: 0.95, rectRadius: 0.07, fill: { color: "56659E" }, line: { type: "none" },
});
s4.addText([
  { text: "asp-libs", options: { bold: true, fontSize: 17, color: WHITE } },
  { text: " [5]", options: { fontSize: 17, color: ICE, breakLine: true, paraSpaceAfter: 2 } },
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
  { text: " [6]", options: { fontSize: 15, color: MUTED } },
], { x: LX + 0.25, y: 5.5, w: LW - 0.5, h: 0.95, fontFace: BODY, align: "left", valign: "middle", margin: 0 });

// Right column: Copland snippet sidebar
const RX = 7.4, RW = 5.2;
s4.addText("Copland protocol from the demo — the Isolette model class:", {
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
  { text: "measure five blessed model files \u2192 ", options: { breakLine: true } },
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
// ("bless ⇒ provision" arrow label removed per user edits 2026-09-03; the arrow stays.)

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
s5.addText("on fail:  no repair chain => escalate", {
  x: 1.52, y: 4.3, w: 1.19, h: 0.9, fontFace: BODY, fontSize: 10,
  color: RED, align: "right", margin: 0,
});

// provision -> measurement (successful provisioning leads to re-measurement)
seg5(s5, 3.0, 2.35, 1.55, 2.35, GREEN, 2);
arrow5(s5, 1.55, 2.35, 1.55, 2.97, GREEN);
s5.addText("provisioned ⇒ re-measure", {
  x: 0.6, y: 2.0, w: 2.6, h: 0.3, fontFace: BODY, fontSize: 10.5,
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
s5.addText("on-fail: handoff to next repair KS \n(attempts spent, changes restored)", {
  x: 8.49, y: 4.12, w: 4.4, h: 0.3, fontFace: BODY, fontSize: 10.5, color: RED, align: "center", margin: 0,
});

// GREEN: on-pass — every KS result returns to the Controller, which re-verifies
seg5(s5, 9.55, 3.0, 9.55, 2.3, GREEN, 2);
seg5(s5, 11.05, 3.0, 11.05, 2.3, GREEN, 2);
seg5(s5, 12.55, 3.0, 12.55, 2.3, GREEN, 2);
seg5(s5, 7.3, 2.3, 12.55, 2.3, GREEN);
arrow5(s5, 7.3, 2.3, 7.3, 2.95, GREEN);
s5.addText("on-pass: restart-episode ⇒ fresh measurement", {
  x: 6.59, y: 1.92, w: 5.4, h: 0.3, fontFace: BODY, fontSize: 11, color: GREEN, align: "center", margin: 0,
});

// RED: route exhausted -> escalate lane
seg5(s5, 12.55, 4.0, 12.55, 5.15, RED);
seg5(s5, 4.3, 5.15, 12.55, 5.15, RED);
arrow5(s5, 4.3, 5.15, 4.3, 4.92, RED);
s5.addText("all rungs exhausted → escalate", {
  x: 7.4, y: 5.22, w: 3.6, h: 0.3, fontFace: BODY, fontSize: 11, color: RED, align: "center", margin: 0,
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

// (Checklist-glyph legend moved from here to the Act I transition slide per user edits 2026-09-03.)

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
  // First four definitions tightened per user edits 2026-09-03.
  { term: "Blackboard", desc: "a collection of entries:  the shared measurement store updated cooperatively by blackboard components" },
  { term: "Blackboard Entry (Key)", desc: "a measurement under judgment:  its measurement content, current standing, repair history" },
  { term: "Episode", desc: "one full judgment of an entry: attestation records verdicts, must be restarted for fresh measurement" },
  { term: "Partition", desc: "the division of blackboard entries among different workflow stages (i.e. provision, certify, escalate) " },
  { term: "Controller", desc: "evaluates every entry (once provisioned), dispatches keys onto outcome-routed chains, advances or hands off, escalates, halts only when entries are in good standing" },
  { term: "Knowledge source (KS)", desc: "operates only on entries in its partition (optionally a single component), bounded by max attempts; its work is always re-judged, never trusted" },
  // desc as runs: the route-chain names are set in Courier New (user edit 2026-09-03).
  { term: "Route", desc: [
      { text: "the per-key control flow chains: " },
      { text: "on_fail ", options: { fontFace: "Courier New" } },
      { text: "= the repair ladder, " },
      { text: "on_pass ", options: { fontFace: "Courier New" } },
      { text: "= a confirmation chain before good standing" },
    ] },
  { term: "History / Ledger", desc: "the blackboard's running record of every change across all partitions (measurements, repairs, verdicts), documenting the audit trail of the repair lifecycle" },
];
const compParas = [];
comps.forEach((c, i) => {
  compParas.push({ text: c.term, options: { bold: true, color: NAVY, bullet: { code: "2022" }, breakLine: false } });
  const runs = Array.isArray(c.desc) ? c.desc : [{ text: c.desc }];
  runs.forEach((r, j) => {
    const last = j === runs.length - 1;
    compParas.push({ text: (j === 0 ? " — " : "") + r.text, options: Object.assign({ color: DARK, breakLine: last && i !== comps.length - 1, paraSpaceAfter: last ? 9 : undefined }, r.options || {}) });
  });
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
if (SHOW_COMPACT_STRIP) {
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

s7.addText("The Isolette Example", {
  x: 0.7, y: 1.04, w: 8.0, h: 0.7, fontFace: HDR, fontSize: 34, bold: true,
  color: NAVY, margin: 0,
});

// Left half: what it is
// Wording + structure per user edits 2026-09-03: each beat carries one "o" sub-bullet.
const SUB = { code: "006F" }; // PowerPoint's default level-2 "o" bullet
const introParas = [
  { text: "The system: ", options: { bold: true, breakLine: false, bullet: { code: "2022" } } },
  { text: "infant-incubator thermostat that regulates and monitors a newborn's environment to maintain a safe temperature range (heat control on/off)", options: {} },
  { text: " [7]", options: { color: MUTED, breakLine: true, paraSpaceAfter: 2 } },
  { text: "requirements traceable to FAA AR-08-32 [10] (the REQ-MHS-* family the scenes will tamper with)", options: { fontSize: 11, italic: true, color: MUTED, breakLine: true, paraSpaceAfter: 10, bullet: SUB, indentLevel: 1 } },
  { text: "The relevance: ", options: { bold: true, breakLine: false, bullet: { code: "2022" } } },
  { text: "the INSPECTA program's seL4/Microkit HAMR-based pipeline", options: {} },
  { text: " [11]", options: { color: MUTED, breakLine: true, paraSpaceAfter: 2 } },
  { text: "current, safety-critical development artifact, not a toy example", options: { breakLine: false, bullet: SUB, indentLevel: 1 } },
];
s7.addText(introParas, {
  x: 0.62, y: 1.98, w: 6.73, h: 2.5, fontFace: BODY, fontSize: 13.5, color: DARK,
  align: "left", valign: "top", margin: 0,
});

// pipeline graphic
{
  // [line1, line2, citation]; citation (if any) follows line 2 in ice, non-bold.
  const stages = [["SysMLv2 model", "+ GUMBO contracts"], ["HAMR", "codegen", "[8,9]"], ["Verus-verified", "Rust", "[12]"], ["seL4 + Microkit", "target", "[13]"]];
  const py = 3.97, ph = 0.85, pgap = 0.34, px0 = 0.7, ptotal = 6.6; // py 4.35 -> 3.97 per user edits 2026-09-03
  const pw = (ptotal - pgap * (stages.length - 1)) / stages.length;
  stages.forEach(([l1, l2, cite], i) => {
    const x = px0 + i * (pw + pgap);
    s7.addShape(pres.ShapeType.roundRect, {
      x, y: py, w: pw, h: ph, rectRadius: 0.06, fill: { color: MID5 }, line: { type: "none" },
    });
    // bold on the label runs (not the box) so the citation run can stay plain — a run-level bold:false is ignored by pptxgenjs
    const runs = [{ text: l1, options: { bold: true, breakLine: true } }, { text: l2, options: { bold: true } }];
    if (cite) runs.push({ text: " " + cite, options: { color: ICE } });
    s7.addText(runs, { x, y: py, w: pw, h: ph, fontFace: BODY, fontSize: 10.5, color: WHITE, align: "center", valign: "middle", margin: 0.02 });
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

// (References footer removed 2026-09-04: the K-State papers are now cited by number [7][8][9] and listed on the References slide.)

// Right half: big-number callouts ("the measured surface" heading removed per user edits 2026-09-03)
const stats = [
  ["13", "measured files (SysMLv2 packages, Verus-contract-bearing Rust)"],
  ["67", "contract slices"],
  ["8", "crates re-verified every episode (7 components and the system-level proof)"],
  ["1,862", "system-proof obligations"],
  ["30", "toolchain + dependency files hashed measure-then-use (4 Verus · 9 HAMR · 17 SysML libs)"],
  ["8", "attestation tiers — the blackboard's entry keys:\nprops · l1a · l2 · verus · cheat · sysproof · gensrc · report"],
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
    x: i === 0 ? 8.88 : 9.25, y, w: i === 0 ? 3.67 : 3.3, h: 0.74, fontFace: BODY, fontSize: 10, color: DARK,
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
  // Scene tags, watch-for wording and the scenesY nudge on Acts IV-VII per user edits 2026-09-04.
  { num: "ACT I", title: "The consistent baseline", scenes: "Demo scene 1",
    watch: [
      { text: "All artifacts start in a \u201Cpass\u201D state with integrity against golden values and ", options: { italic: true, breakLine: true } },
      { text: "implementations meet their contracts.", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 1",
    legend: true,
    notes: "Beats: readiness gate green -> one full episode -> per-crate checklist all green. Dwell on the final checklist - it is the frame every later refusal is compared against." },
  { num: "ACT II", title: "Spec drift: benign, promote then re-verify", scenes: "Demo scene 3",
    watch: "A benign change in requirements — the temperature alarm range widened — model appraisal fails quickly.  Administrator re-blesses new spec, all contract appraisals again pass.",
    cmd: "./examples/demo_isolette.sh --scenes 3 --drift range         (ruling at the prompt: bless)",
    notes: "Single benign beat (per user deck edit, restored 2026-08-27): the Table A-12 upper-alarm ceiling widened 102 -> 103 in the shared GUMBO library constant. Beats: appraisal fails, gumbo_library attributed, all else green (dwell: 'sanction, not semantics') -> ruling diff -> bless -> spec-first green -> promote (real codegen; speed-ramp) -> re-proves ALL GREEN; offered diff = the regenerated shared-library constant. The breaking spec beat lives elsewhere (breaking-impl is Act V/scene 2, breaking-contract is Act IV/scene 14), so Act II stays the clean benign-model story." },
  { num: "ACT III", title: "Implementation drift: benign, re-verify", scenes: "Demo scene 13",
    watch: [
      { text: "A developer rewrites semantically equivalent implementation logic.  The hash moves, but ", options: { italic: true, breakLine: true } },
      { text: "every contract slice maintains integrity", options: { bold: true, italic: false } },
      { text: ", and the proofs re-verify: the benign change survives.", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 13",
    notes: "Beats: equivalent NORMAL-mode guard rewrite (x>y -> y<x), outside every marker block -> l1a hash moves -> files entry passes via l2 refinement (slices intact) -> the l1b contracts entry stays clean -> confirmation chain RE-VERIFIES the rewrite green. The mirror of Act II's benign spec beat, one artifact class down: a developer-owned region has no blessed bytes to match, so its attested properties are contracts (intact) + provability (re-verified live)." },
  { num: "ACT IV", title: "Contract drift: breaking, restore then attempt re-verification", scenes: "Demo scene 14", scenesY: 3.54,
    watch: [
      { text: "The model is untouched, but a live Verus contract is weakened (", options: { italic: true } },
      { text: "after codegen, but before verification", options: { bold: true, italic: true } },
      { text: ") and the code is inverted to match — verus checks pass.  Contract repair (restoring the true Verus contract) exposes the verification failure.", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 14",
    notes: "The report emits NO slice for compute_cases realizations, so the weakened REQ_MHS_2 lands between l2 slices. Beats: launder (weaken REQ_MHS_2 ensures + invert impl) -> cargo-verus SUCCEEDS (self-consistent) -> the l1b MARKER tier (a new Copland protocol: readfile_marker_range over every contract-block byte) refuses -> its repair rung splices the golden contract back -> the restored TRUE contract refutes the still-inverted impl: end on the exposed Verus refusal (verus_targ Appraisal was not successful). Discovered while building this demo; the marker-coverage lint now enforces the invariant. Do NOT auto-repair to green - the exposure IS the beat; the impl repair is Act V's ladder. Slide-C candidate row." },
  { num: "ACT V", title: "Implementation drift: breaking, diagnose then repair", scenes: "Demo scene 2", scenesY: 3.54,
    watch: [
      { text: "Implementation code (developer-owned) changes, breaking a Verus contract.  Blackboard loop diagnoses, repairs, then ", options: { italic: true } },
      { text: "returns the artifact to good standing only by re-measurement", options: { bold: true, italic: true } },
      { text: ".", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes 2",
    notes: "Beats: dummy-bad-impl diff (take the [v]iew - VSCode diff D1 on camera) -> contracts-intact rung exhausts -> impl rung restores crate-scoped -> restart -> re-attested clean." },
  { num: "ACT VI", title: "Baseline drift:  tampered evidence bundle, protocol, tooling", scenes: "Demo scenes 6 + 7", scenesY: 3.54,
    watch: [
      { text: "The signed golden evidence bundle, an installed (live) golden value in the appraisal protocol, then the verification tool itself — each tamper attributed, ", options: { italic: true } },
      { text: "each refused by cryptographic checks", options: { bold: true, italic: true } },
      { text: ".", options: { italic: true } },
    ],
    cmd: "./examples/demo_isolette.sh --scenes \"6 7\"",
    notes: "Scene 6 beats: three tampers, three attributed refusals (signature -> anchor -> derivability); optionally the flipped-evidence-byte diff on camera. Scene 7 beats: wrapper edit (take the [v]iew, diff D10) -> readiness still passes -> tool hash refutes, every proof cell poisons to ? - dwell, this is the act's money shot. --restore-tools recovery in VO only." },
  { num: "ACT VII", title: "Axiom drift:  semantic measurement detects axioms and unsound proof techniques", scenes: "Demo scenes 9 + 12", scenesY: 3.54,
    watch: [
      { text: "Proofs verify, but measurement detects ", options: { italic: true } },
      { text: "subtle cheating in proof attempts, ", options: { bold: true, breakLine: true } },
      { text: "that would otherwise undermine verification soundness.", options: { italic: true } },
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
  if (SHOW_COMPACT_STRIP) sections.forEach((name, i) => {
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
    x: 0.9, y: act.scenesY || 3.45, w: 11.5, h: 0.45, fontFace: BODY, fontSize: 15, italic: true,
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
  if (act.legend) {
    // Checklist-glyph legend (Act I only; moved here from slide 5 per user edits 2026-09-03)
    sa.addShape(pres.ShapeType.roundRect, {
      x: 6.75, y: 6.19, w: 2.99, h: 0.8, rectRadius: 0.07, fill: { color: "F2F4F8" }, line: { color: ICE, width: 1 },
    });
    sa.addText("✓ attested   \n✗ refuted\n? poisoned (untrustworthy)", {
      x: 6.9, y: 6.19, w: 2.83, h: 0.8, fontFace: "Courier New", fontSize: 11,
      color: DARK, align: "left", valign: "middle", margin: 0,
    });
  }
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
    { text: "The blackboard infrastructure and artifact classes don\u2019t change \u2014 only the ", options: {} },
    { text: "pipeline around them does", options: { bold: true } },
    { text: ": modeling language, prover, ", options: { breakLine: true } },
    { text: "target runtime, and attestation primitives.", options: {} },
  ], { x: 0.7, y: 1.12, w: 12.0, h: 0.5, fontFace: BODY, fontSize: 15, italic: true, color: DARK, margin: 0 });

  const cards = [
    { header: "SysML v2 \u2192 HAMR \u2192 Rust / Verus", caption: "isolette", badge: "the demo", ref: true,
      bullets: ["SysMLv2 GUMBO component contracts", "seL4 / Microkit runtime target", "Every artifact class measured"] },
    { header: "AADL \u2192 HAMR \u2192 Slang / Logika", caption: "temp-control",
      bullets: ["AADL GUMBO component contracts", "JVM runtime target", "Same blackboard, similar Copland protocols to SysMLv2 pipeline"] },
    { header: "Standalone Rust / Verus", caption: "find-max-verus",
      // { sub: true } = level-2 "o" sub-bullet (user edit 2026-09-04; exact pPr patched post-build, see PPR_OVERRIDES)
      bullets: ["Contracts + proofs written directly in Verus", "No model, no codegen \u2014 implementation + proof classes only", "Proof-repair experiments",
        { text: "AutoVerus", sub: true }, { text: "KU Dogtreat linear planner", sub: true }] },
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
      const sub = typeof b === "object" && b.sub;
      paras.push({ text: typeof b === "object" ? b.text : b, options: {
        bullet: { code: sub ? "006F" : "2022" }, indentLevel: sub ? 1 : 0, color: c.ref ? ICE : DARK, fontSize: 12,
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

  // Cell wording per user edits 2026-09-04 (headers, every "rule" cell, LLM column trimmed).
  const rows = [
    [th("Workflow stage"), th("Where LLMs participate"), th("The Guardrail")],
    [td([B("Model / spec")]),
     td([P("May draft or restate specs")]),
     td([P("Only a human administrator may authenticate a new spec")])],
    [td([B("Implementation")]),
     td([P("spec-guided synthesis / re-derivation")]),
     td([P("Code must meet its formal contracts, checked by legitimate toolchain, derived from human-blessed spec")])],
    [td([B("Proofs")]),
     td([P("Suggests tactic portfolio (deterministic at runtime) \u00b7 API calls + LLM-assisted desktop sessions (loop is paused) \u00b7 Proof repair agents (AutoVerus \u00b7 KU Dogtreat linear planner)")]),
     td([P("Only fresh measurement re-establishes good standing")])],
    [td([B("Verification & appraisal")], TINT),
     td([B("none \u2014 by design")], TINT),
     td([P("Verification kernels (Rocq, Lean, Verus), formally-verified attestation managers (evidence unbundling), trusted attestation primitives (hash checks, semantic analysis of source code, etc.)")], TINT)],
    [td([B("Evidence / trust state")], TINT),
     td([B("none \u2014 by design")], TINT),
     td([P("Cryptographic immutability")], TINT)],
  ];
  sa.addTable(rows, {
    x: 0.7, y: 1.84, w: 11.9, colW: [2.5, 4.9, 4.5], // y 1.75 -> 1.84 per user edits 2026-09-04
    border: { type: "solid", color: "D8DEEA", pt: 1 },
    rowH: [0.4, 0.62, 0.62, 1.0, 0.72, 0.72], margin: 0.09, fontFace: BODY,
  });

  // (The "🔒 the bottom two — the judges — are AI-free by design" footer was removed per user edits 2026-09-04;
  //  the point stays in the speaker notes.)

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
  const C = (t) => ({ text: t, options: { fontFace: "Courier New" } });
  const BR = (t) => ({ text: t, options: { breakLine: true } }); // ends a paragraph inside a cell

  // Cell wording per user edits 2026-09-04 ("How we trust it (or not)" column rewritten; code names in Courier New).
  const rows = [
    [th("What AI built"), th(""), th("How we trust it (or not)")],
    [td([B("Blackboard infrastructure")]),
     td([P("pybb framework (blackboard, controller, knowledge sources), demo arcs, install script, CI suite, detailed documentation")]),
     td([P("Orchestration in python is untrusted,"), B(" but evidence bundles are independently-verifiable")])],
    [td([B("CVM core & frontends")]),
     td([C("bpar"), P(" (parallel Copland term) "), { text: "in the verified CVM core,", options: { italic: true, breakLine: true } },
         P("CVM frontend fixes ("), C("--stdin, --req_file "), P("interfaces)")]),
     td([B("Rocq proofs w.r.t. CVM reference semantics --"), P("Claude couldn\u2019t update existing proofs automatically, but assisted an expert Rocq developer")])],
    [td([B("Measurement primitives")]),
     td([B("12 new + 7 upgraded"), P(" asp-libs binaries (hashing, the Lean/Rocq/HAMR runners & appraisers, cheat scan, golden-slice extraction)")]),
     td([P("New attestation primitives are untrusted, require manual inspection (or formal analysis)")])],
    [td([B("Attestation protocols")]),
     td([B("42 provisioned"), P(" Copland protocol directories across the ecosystems")]),
     td([P("Copland protocol analysis bolsters trust")])],
    [td([B("Attacks")]),
     td([P("demo tampers + "), B("7 red-team attack classes "), P("(see next slide)")]),
     td([P("Concrete \u201Ccounter-examples\u201D show attacks succeeding, "), B("undetected by existing measurement")])],
  ];
  sb.addTable(rows, {
    x: 0.7, y: 1.75, w: 11.9, colW: [2.6, 5.6, 3.7],
    border: { type: "solid", color: "D8DEEA", pt: 1 },
    rowH: [0.4, 0.7, 0.72, 0.92, 0.62, 0.82], margin: 0.09, fontFace: BODY,
  });

  sb.addText([
    { text: "A virtuous cycle \u2013 ", options: { bold: true } },
    { text: "AI-assisted workflow to add (deterministic) tools and domain-specific measurement capabilities.  ", options: {} },
  ], { x: 0.7, y: 6.61, w: 11.9, h: 0.4, fontFace: BODY, fontSize: 13.5, italic: true, color: NAVY, align: "left", margin: 0 });

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
  const C = (t) => ({ text: t, options: { fontFace: "Courier New" } });

  // Cell wording per user edits 2026-09-04 (identifiers in Courier New; several cells trimmed).
  const rows = [
    [th("Attack"), th("Avoided detection by"), th("New measurement forced")],
    [td([B("ADMIT"), P(" \u2014 "), C("assume(false) "), P("in an unmeasured bridge file")]),
     td([P("cargo-verus reports the same success over the hollow proof")]),
     td([P("cheat scan ("), C("cheat_scan_verus"), P(")")])],
    [td([B("SMUGGLE"), P(" \u2014 "), C("external_body "), P("broadcast axiom, ensures false")]),
     td([P("cargo-verus reports the same success over the hollow proof")]),
     td([P("cheat scan ("), C("cheat_scan_verus"), P(")")])],
    [td([B("SHRINK"), P(" \u2014 system-proof module commented out")]),
     td([P("smaller crate still verifies, 0 errors")]),
     td([P("sysproof file hashes")])],
    [td([B("SWAP"), P(" \u2014 contract dropped, trivial one added, same count")]),
     td([P("outcome, count, escape surface all unchanged")]),
     td([P("sysproof file hashes")])],
    [td([B("STALE"), P(" \u2014 semantic flip in a cached dep, "), C("mtime"), P(" preserved")]),
     td([P("mtime-gated cache serves the stale verdict")]),
     td([C("gensrc"), P(" measurement")])],
    [td([B("INVERT"), P(" \u2014 heat command flipped in unverified FFI glue")]),
     td([P("Verus never reads the body (unverified code, out of scope)")]),
     td([C("gensrc"), P(" measurement")])],
    [td([B("LAUNDER"), P(" \u2014 contract weakened + impl inverted to match")], HILITE),
     td([P("gap in contract coverage for attestation report\u2019s compute_cases construct")], HILITE),
     td([P("stopgap contract measurement, contract coverage check at provisioning")], HILITE)],
  ];
  sc.addTable(rows, {
    x: 0.7, y: 1.7, w: 11.9, colW: [3.95, 4.45, 3.5],
    border: { type: "solid", color: "D8DEEA", pt: 1 },
    rowH: [0.36, 0.55, 0.55, 0.5, 0.6, 0.62, 0.62, 0.86], margin: 0.08, fontFace: BODY,
  });

  sc.addText([
    { text: "Adversarial co-development", options: { bold: true } },
    { text: " \u2014 defense-in-depth, anomaly detection, proposed mitigation.", options: {} },
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

// Numbers = order of first on-slide citation (2026-09-04; verified against Crossref/DBLP/FAA/GitHub the same day):
//   lifecycle slide: [1] Thomas et al. layered attestations (arXiv 2026) ·
//   core-stack slide: [2] Copland paper, [3] CVM repo, [4] SEFM'24 config/deployment, [5] asp-libs repo, [6] ISSE'22 bundling/appraisal ·
//   isolette slide: [7] paper, [8][9] HAMR, [10] FAA handbook, [11] INSPECTA models, [12] Verus, [13] seL4.
// Groupings kept per user, so numbers read out of order here — intentional. Group order per user 2026-09-04:
// Attestation foundations first, then the isolette & HAMR group, then verification & platform.
const refGroups = [
  ["Attestation foundations", [
    [1, ["Thomas, Schmalz, Petz, Alexander, Guttman, Rowe, Carter, ", 0], ["Designing Trustworthy Layered Attestations", 1], [", arXiv:2603.06326, 2026", 0]],
    [2, ["Ramsdell, Rowe, Alexander, Helble, Loscocco, Pendergrass, Petz, ", 0], ["Orchestrating Layered Attestations", 1], [", POST 2019, LNCS 11426, pp. 197\u2013221", 0]],
    [3, ["Copland Virtual Machine (CVM), KU SLDG: github.com/ku-sldg/cvm", 0]],
    [4, ["Petz, Thomas, Fritz, Barclay, Schmalz, Alexander, ", 0], ["Verified Configuration and Deployment of Layered Attestation Managers", 1], [", SEFM 2024, LNCS 15280, pp. 290\u2013308", 0]],
    [5, ["asp-libs (attestation service provider libraries), KU SLDG: github.com/ku-sldg/asp-libs", 0]],
    [6, ["Petz & Alexander, ", 0], ["Formally Verified Bundling and Appraisal of Evidence for Layered Attestations", 1], [", Innovations in Systems and Software Engineering 19(4), 2023, pp. 411\u2013426", 0]],
  ]],
  ["The isolette & HAMR (Kansas State)", [
    [7, ["Hatcliff & Belt, ", 0], ["The Isolette System: Illustrating End-to-End Artifacts for Rigorous Model-Based Engineering", 1], [", Springer LNCS 15240, 2025, pp. 93\u2013117", 0]],
    [8, ["Hatcliff, Belt, Robby, McKenzie, Liang, ", 0], ["End-to-End Formal Methods Integrated Development with SysMLv2 Using HAMR", 1], [", FMICS 2025, Springer LNCS 16040, pp. 241\u2013260", 0]],
    [9, ["Hatcliff, Belt, Robby, Carpenter, ", 0], ["HAMR: An AADL Multi-platform Code Generation Toolset", 1], [", ISoLA 2021, LNCS 13036, pp. 274\u2013295", 0]],
    [10, ["Lempia & Miller, ", 0], ["Requirements Engineering Management Handbook", 1], [", DOT/FAA/AR-08/32, 2009", 0]],
    [11, ["INSPECTA models: github.com/loonwerks/INSPECTA-models", 0]],
  ]],
  ["Verification & platform", [
    [12, ["Lattuada, Hance, Cho, Brun, Subasinghe, Zhou, Howell, Parno, Hawblitzel, ", 0], ["Verus: Verifying Rust Programs using Linear Ghost Types", 1], [", PACMPL 7 (OOPSLA1), 2023", 0]],
    [13, ["Klein et al., ", 0], ["seL4: Formal Verification of an OS Kernel", 1], [", SOSP 2009, pp. 207\u2013220", 0]],
  ]],
];
let refParas = [];
refGroups.forEach(([group, refs], gi) => {
  refParas.push({ text: group, options: { bold: true, color: NAVY, fontSize: 14, breakLine: true, paraSpaceBefore: gi === 0 ? 0 : 12, paraSpaceAfter: 4 } });
  refs.forEach(([num, ...runs]) => {
    refParas.push({ text: `[${num}]  `, options: { bold: true, color: NAVY, fontSize: 11.5, breakLine: false } });
    runs.forEach(([text, ital], j) => {
      refParas.push({ text, options: { italic: ital === 1, color: DARK, fontSize: 11.5, breakLine: j === runs.length - 1, paraSpaceAfter: 3 } });
    });
  });
});
refParas[refParas.length - 1].options.breakLine = false;
sref.addText(refParas, {
  x: 0.7, y: 1.5, w: 12.0, h: 5.6, fontFace: BODY, align: "left", valign: "top", margin: 0,
});
sref.addNotes(
  "Collection point for every reference in the deck - keep this slide current as sections are added. Numbers follow first on-slide citation ([1] on the lifecycle slide; [2]-[6] on the core-stack slide; [7]-[13] on the isolette slide); groupings kept, so numbers read out of order here on purpose.\n" +
  "DOIs on record in docs/video_slide_drafts.md."
);

const OUT = process.argv[2] || require("path").join(__dirname, "..", "docs", "video_slides_draft.pptx");

// ---------- Post-build fidelity patches ----------
// pptxgenjs cannot express a few paragraph properties PowerPoint wrote when the user
// edited the deck directly. To keep regeneration byte-faithful to those edits, patch
// the affected <a:pPr> elements in the written file. Each entry: slide XML part, the
// 0-based index among that slide's lvl="1" paragraphs, and the exact pPr to install.
const PPR_OVERRIDES = [
  // Isolette slide (deck position 8): the two "o" sub-bullets use PowerPoint's default
  // Courier New bullet font and its own hanging indents (user edit 2026-09-03).
  { part: "ppt/slides/slide8.xml", lvl1Index: 0,
    ppr: '<a:pPr marL="628650" lvl="1" indent="-171450"><a:spcAft><a:spcPts val="1000"/></a:spcAft><a:buFont typeface="Courier New" panose="02070309020205020404" pitchFamily="49" charset="0"/><a:buChar char="o"/></a:pPr>' },
  { part: "ppt/slides/slide8.xml", lvl1Index: 1,
    ppr: '<a:pPr marL="800100" lvl="1" indent="-342900"><a:buSzPct val="100000"/><a:buFont typeface="Courier New" panose="02070309020205020404" pitchFamily="49" charset="0"/><a:buChar char="o"/></a:pPr>' },
  // Ecosystems slide (deck position 16): the two "o" sub-bullets under "Proof-repair experiments" (user edit 2026-09-04).
  { part: "ppt/slides/slide16.xml", lvl1Index: 0,
    ppr: '<a:pPr marL="800100" lvl="1" indent="-342900"><a:spcAft><a:spcPts val="400"/></a:spcAft><a:buSzPct val="100000"/><a:buFont typeface="Courier New" panose="02070309020205020404" pitchFamily="49" charset="0"/><a:buChar char="o"/></a:pPr>' },
  { part: "ppt/slides/slide16.xml", lvl1Index: 1,
    ppr: '<a:pPr marL="800100" lvl="1" indent="-342900"><a:spcAft><a:spcPts val="400"/></a:spcAft><a:buSzPct val="100000"/><a:buFont typeface="Courier New" panose="02070309020205020404" pitchFamily="49" charset="0"/><a:buChar char="o"/></a:pPr>' },
];
async function applyPprOverrides(file) {
  const fs = require("fs"), JSZip = require("jszip");
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  for (const o of PPR_OVERRIDES) {
    let xml = await zip.file(o.part).async("string");
    let k = -1;
    xml = xml.replace(/<a:pPr[^>]*\blvl="1"[^>]*>.*?<\/a:pPr>/gs, (m) => (++k === o.lvl1Index ? o.ppr : m));
    if (k < o.lvl1Index) throw new Error(`pPr override: lvl1 paragraph ${o.lvl1Index} not found in ${o.part}`);
    zip.file(o.part, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

pres.writeFile({ fileName: OUT })
  .then(() => applyPprOverrides(OUT))
  .then(() => console.log("written: " + OUT));
