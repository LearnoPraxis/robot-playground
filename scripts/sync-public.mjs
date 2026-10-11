/**
 * 把 frontend/dist 的构建产物同步到仓库根的 public/，并做部署前校验。
 *
 * 背景（见 .trae/documents/troubleshooting-log.md 问题 21）：
 * 曾经 @huggingface/transformers 的 ONNX Runtime WASM 达到 25.6 MiB，
 * 超过 Cloudflare Workers 免费计划"单个静态文件 ≤ 25 MiB"的硬限制，
 * 导致 `wrangler deploy` 失败。当时的应对是"在构建脚本里静默删除所有 .wasm"，
 * 但那样会把问题推迟到线上才暴露（白屏 + Failed to fetch），因此在 2026-10 移除。
 *
 * 现在改为两道显式处理：
 *   1. 排除清单：命中清单的文件按名字报告并跳过，不再无条件删除任何 .wasm；
 *   2. 体积闸门：对标 25 MiB，超限直接以非零退出码失败，报出文件名与实际体积，
 *      在构建期就暴露，而不是等部署失败或线上白屏。
 *
 * 用法：node ../scripts/sync-public.mjs   （cwd = frontend/）
 */

import { cp, mkdir, readdir, rm, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

/** Cloudflare Workers 免费计划：单个静态文件上限（25 MiB）。 */
const MAX_ASSET_BYTES = 25 * 1024 * 1024;

/**
 * 明确排除、且不上传到 public/ 的文件。
 * 命中时只报告，不静默删除——请连同"为什么"一起写清楚。
 */
const EXCLUDED = [
  // { pattern: /^ort-wasm.*\.wasm$/, reason: "ONNX Runtime WASM 25.6MiB 超限（依赖已移除）" },
];

const distDir = path.join(process.cwd(), "dist");
const publicDir = path.resolve(process.cwd(), "..", "public");
const distAssets = path.join(distDir, "assets");
const publicAssets = path.join(publicDir, "assets");

const skipped = [];
const copied = [];

/** 递归收集目录下所有文件（返回相对 publicDir 的 posix 路径）。 */
async function collectFiles(dir, base = dir) {
  const out = [];
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await collectFiles(full, base)));
    else if (entry.isFile()) out.push(path.relative(base, full).split(path.sep).join("/"));
  }
  return out;
}

function excluded(fileName) {
  return EXCLUDED.find((rule) => rule.pattern.test(fileName));
}

async function main() {
  // --- 0. 前置检查：dist 必须存在 ---
  try {
    await stat(distDir);
  } catch {
    console.error(`[sync-public] 找不到 ${distDir}，请先执行 vite build。`);
    process.exit(1);
  }

  // --- 1. 清理上一次的 assets，避免旧 hash 文件长期堆积 ---
  await rm(publicAssets, { recursive: true, force: true });
  await mkdir(publicAssets, { recursive: true });

  // --- 2. index.html ---
  await cp(path.join(distDir, "index.html"), path.join(publicDir, "index.html"));
  copied.push("index.html");

  // --- 3. dist/ 根下的其他静态文件（Vite 从 publicDir 复制来的 favicon.svg、icons.svg 等）---
  for (const entry of await readdir(distDir, { withFileTypes: true })) {
    if (!entry.isFile()) continue;
    if (entry.name === "index.html") continue;
    const rule = excluded(entry.name);
    if (rule) {
      skipped.push({ file: entry.name, reason: rule.reason });
      continue;
    }
    await cp(path.join(distDir, entry.name), path.join(publicDir, entry.name));
    copied.push(entry.name);
  }

  // --- 4. dist/assets/* ---
  for (const entry of await readdir(distAssets, { withFileTypes: true })) {
    if (!entry.isFile()) continue;
    const rule = excluded(entry.name);
    if (rule) {
      skipped.push({ file: `assets/${entry.name}`, reason: rule.reason });
      continue;
    }
    await cp(path.join(distAssets, entry.name), path.join(publicAssets, entry.name));
    copied.push(`assets/${entry.name}`);
  }

  // --- 5. 报告被排除的文件 ---
  for (const item of skipped) {
    console.warn(`[sync-public] 跳过 ${item.file} —— ${item.reason}`);
  }

  // --- 6. 体积闸门：对 public/ 下全部文件做 25 MiB 校验 ---
  const files = await collectFiles(publicDir);
  const oversized = [];
  let total = 0;
  let largest = 0;
  for (const rel of files.sort()) {
    const { size } = await stat(path.join(publicDir, rel));
    total += size;
    if (size > largest) largest = size;
    if (size > MAX_ASSET_BYTES) oversized.push({ rel, size });
  }

  if (oversized.length > 0) {
    console.error(
      `\n[sync-public] 构建失败：以下文件超过 Cloudflare 单文件上限 25 MiB（${MAX_ASSET_BYTES} 字节）：`,
    );
    for (const { rel, size } of oversized) {
      console.error(`  - ${rel}  ${(size / 1024 / 1024).toFixed(2)} MiB`);
    }
    console.error(
      "\n处理方式（按优先级）：\n" +
        "  1. 去掉这个大文件对应的依赖；\n" +
        "  2. 换成更小的构建变体（例如非 asyncify / 非 threaded 的 wasm）；\n" +
        "  3. 放到站外托管——注意页面有 COOP/COEP，跨域资源必须带 CORP 头；\n" +
        "  4. 确实要排除时，在 scripts/sync-public.mjs 的 EXCLUDED 里显式登记并写明原因。\n" +
        "不要用通配删除绕过：那样只会在线上变成白屏。",
    );
    process.exit(1);
  }

  console.log(
    `[sync-public] 已同步 ${copied.length} 个文件到 public/；` +
      `共 ${files.length} 个静态文件、${(total / 1024 / 1024).toFixed(2)} MiB，` +
      `最大单文件 ${(largest / 1024 / 1024).toFixed(2)} MiB（上限 25.00 MiB），校验通过。`,
  );
}

await main();
