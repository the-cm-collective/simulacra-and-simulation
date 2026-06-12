const { defineConfig, devices } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./e2e",
  timeout: 90000,
  expect: {
    timeout: 20000,
  },
  reporter: [
    ["list"],
    ["html", { outputFolder: ".local/playwright-report", open: "never" }],
  ],
  outputDir: ".local/playwright-results",
  use: {
    baseURL: process.env.PADAWAN_BASE_URL || "http://127.0.0.1:8787",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: {
      args: [
        "--allow-insecure-localhost",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
