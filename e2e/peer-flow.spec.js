const fs = require("node:fs");
const path = require("node:path");
const { expect, test } = require("@playwright/test");

const TRACKS = new Set(["plain-codex", "workerbee-codex"]);

function runTrack() {
  const track = process.env.SIMULACRA_TRACK;
  return TRACKS.has(track) ? track : "";
}

function evidenceDir() {
  if (process.env.SIMULACRA_EVIDENCE_DIR) {
    return path.resolve(process.env.SIMULACRA_EVIDENCE_DIR);
  }
  const runId = process.env.SIMULACRA_RUN_ID;
  const track = runTrack();
  const phase = evidencePhase();
  if (runId && track) {
    const screenshotsRoot = path.join(process.cwd(), ".local", "runs", runId, track, "evidence", "screenshots");
    if (phase) return path.join(screenshotsRoot, phase, "peer-flow");
    return path.join(screenshotsRoot, "peer-flow");
  }
  return path.join(process.cwd(), ".local", "evidence", "peer-flow");
}

function videoDir(root) {
  return path.join(root, "..", "video", "peer-flow");
}

function evidencePhase() {
  const raw = process.env.SIMULACRA_EVIDENCE_PHASE || "";
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

async function videoHasStream(page, selector) {
  return page.locator(selector).evaluate((video) => {
    const stream = video.srcObject;
    return Boolean(stream && stream.getTracks && stream.getTracks().length > 0);
  });
}

async function openPeerPage(context, role, username) {
  const page = await context.newPage();
  await page.goto(`/peer?role=${encodeURIComponent(role)}&username=${encodeURIComponent(username)}`);
  await page.locator("[data-peer-ice-profile]").selectOption("none");
  await expect(page.locator("[data-peer-status]")).toHaveText("Idle.");
  return page;
}

async function createPeerContexts(browser, baseURL, root) {
  const permissions = ["camera", "microphone"];
  const recordVideo =
    process.env.SIMULACRA_RECORD_VIDEO === "1"
      ? { dir: videoDir(root), size: { width: 1280, height: 720 } }
      : undefined;
  const contextOptions = { baseURL, permissions, recordVideo };
  return {
    jedi: await browser.newContext(contextOptions),
    padawan: await browser.newContext(contextOptions),
  };
}

function appendEvidenceEvent(summaryPath, artifacts) {
  const runId = process.env.SIMULACRA_RUN_ID;
  const track = runTrack();
  if (!runId || !track) return;
  const phase = evidencePhase() || "local";

  const eventsPath = path.join(process.cwd(), ".local", "runs", runId, track, "events.jsonl");
  const event = {
    event_type: "evidence",
    payload: { artifacts, phase, summary_path: summaryPath },
    run_id: runId,
    schema_version: "simulacra.event.v1",
    source: "playwright",
    summary: `Padawan/Jedi browser evidence captured (${phase})`,
    timestamp: new Date().toISOString(),
    track,
  };
  fs.mkdirSync(path.dirname(eventsPath), { recursive: true });
  fs.appendFileSync(eventsPath, JSON.stringify(event) + "\n", "utf8");
}

test("Padawan and Jedi exchange AV, chat, course, and progress data", async ({ browser }, testInfo) => {
  const root = evidenceDir();
  fs.mkdirSync(root, { recursive: true });

  const baseURL =
    testInfo.project.use.baseURL || process.env.PADAWAN_BASE_URL || "http://127.0.0.1:8787";
  const contexts = await createPeerContexts(browser, baseURL, root);
  const artifacts = [];
  let summaryPath = "";
  let jedi;
  let padawan;

  try {
    jedi = await openPeerPage(contexts.jedi, "jedi", "Obi-Wan");
    padawan = await openPeerPage(contexts.padawan, "padawan", "Ahsoka");

    await jedi.locator("[data-peer-create]").click();
    await expect.poll(async () => (await jedi.locator("[data-peer-token]").inputValue()).length).toBeGreaterThan(40);
    const token = await jedi.locator("[data-peer-token]").inputValue();

    await padawan.locator("[data-peer-token]").fill(token);
    await padawan.locator("[data-peer-join]").click();

    await expect(jedi.locator("[data-peer-data-status]")).toContainText("Open.");
    await expect(padawan.locator("[data-peer-data-status]")).toContainText("Open.");
    await expect.poll(() => videoHasStream(jedi, "[data-peer-local-video]")).toBeTruthy();
    await expect.poll(() => videoHasStream(jedi, "[data-peer-remote-video]")).toBeTruthy();
    await expect.poll(() => videoHasStream(padawan, "[data-peer-local-video]")).toBeTruthy();
    await expect.poll(() => videoHasStream(padawan, "[data-peer-remote-video]")).toBeTruthy();

    await padawan.locator("[data-peer-chat-input]").fill("hello from the padawan track");
    await padawan.locator("[data-peer-chat-input]").press("Enter");
    await expect(jedi.locator("[data-peer-chat-log]")).toContainText("Peer: hello from the padawan track");

    const courseId = await jedi.locator("[data-peer-course-select]").inputValue();
    await jedi.locator("[data-peer-send-course]").click();
    await expect(padawan.locator("[data-peer-chat-log]")).toContainText(`Received course: ${courseId}`);

    await padawan.locator("[data-peer-send-progress]").click();
    await expect(jedi.locator("[data-peer-chat-log]")).toContainText(`Received progress: ${courseId}`);

    const jediScreenshot = path.join(root, "jedi-peer.png");
    const padawanScreenshot = path.join(root, "padawan-peer.png");
    await jedi.screenshot({ path: jediScreenshot, fullPage: true });
    await padawan.screenshot({ path: padawanScreenshot, fullPage: true });
    artifacts.push(jediScreenshot, padawanScreenshot);

    summaryPath = path.join(root, "peer-flow-summary.json");
    const summary = {
      base_url: baseURL,
      course_id: courseId,
      data_channel: "open",
      ice_profile: "none",
      phase: evidencePhase() || "local",
      screenshots: [jediScreenshot, padawanScreenshot],
      timestamp: new Date().toISOString(),
      video_recording: process.env.SIMULACRA_RECORD_VIDEO === "1",
    };
    fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2) + "\n", "utf8");
    artifacts.push(summaryPath);
    await testInfo.attach("peer-flow-summary", { path: summaryPath, contentType: "application/json" });
  } finally {
    const videos = [jedi?.video(), padawan?.video()].filter(Boolean);
    await Promise.allSettled([contexts.jedi.close(), contexts.padawan.close()]);
    for (const video of videos) {
      artifacts.push(await video.path());
    }
    if (summaryPath) appendEvidenceEvent(summaryPath, artifacts);
  }
});
