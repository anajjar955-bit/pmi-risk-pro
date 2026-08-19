// Renders promo.html to an MP4 by seeking the deterministic timeline frame
// by frame in headless Chromium and piping JPEG frames into ffmpeg (libx264).
//
// Usage: node render.mjs <chromium-path> <ffmpeg-path> <out.mp4> [fps]
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const [,, CHROME, FFMPEG, OUT, FPS_ARG] = process.argv;
const FPS = Number(FPS_ARG || 30);
const W = 1080, H = 1920;
const here = path.dirname(fileURLToPath(import.meta.url));
const pageUrl = 'file://' + path.join(here, 'promo.html') + '?render=1';

const browser = await chromium.launch({
  executablePath: CHROME,
  args: ['--force-color-profile=srgb', '--hide-scrollbars', '--font-render-hinting=none'],
});
const page = await browser.newPage({ viewport: { width: W, height: H } });
await page.goto(pageUrl);
await page.evaluate(() => document.fonts.ready);
const DUR = await page.evaluate(() => window.DUR);
const total = Math.round(DUR / 1000 * FPS);

const ff = spawn(FFMPEG, [
  '-y', '-f', 'image2pipe', '-vcodec', 'mjpeg', '-framerate', String(FPS), '-i', '-',
  '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-crf', '19',
  '-preset', 'medium', '-movflags', '+faststart', OUT,
], { stdio: ['pipe', 'inherit', 'inherit'] });

const write = buf => new Promise((res, rej) => {
  ff.stdin.write(buf, err => err ? rej(err) : res());
});

for (let i = 0; i < total; i++) {
  const t = i * 1000 / FPS;
  await page.evaluate(ms => window.seek(ms), t);
  const buf = await page.screenshot({ type: 'jpeg', quality: 92, clip: { x: 0, y: 0, width: W, height: H } });
  await write(buf);
  if (i % 150 === 0) console.log(`frame ${i}/${total}`);
}

ff.stdin.end();
await new Promise(res => ff.on('close', res));
await browser.close();
console.log('done:', OUT);
