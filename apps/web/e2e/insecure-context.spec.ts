import { test, expect } from '@playwright/test';

/**
 * GT-0021: a plain-HTTP origin that is not localhost (e.g. a LAN IP such as
 * http://192.168.169.223:5173) is not a browser *secure context*, so
 * `crypto.randomUUID` is undefined there and every write used to fail with
 * "crypto.randomUUID is not a function". We simulate that condition locally by
 * removing randomUUID before the app loads, then exercise two writes (both of
 * which need an Idempotency-Key).
 */
test('writes work without crypto.randomUUID (plain-HTTP LAN origin)', async ({ page }) => {
  await page.addInitScript(() => {
    try { Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true }); } catch { /* ignore */ }
    try { Object.defineProperty(Crypto.prototype, 'randomUUID', { value: undefined, configurable: true }); } catch { /* ignore */ }
  });

  const title = `INSECURE-${Date.now()}`;
  await page.goto('/');
  expect(await page.evaluate(() => typeof window.crypto.randomUUID)).toBe('undefined');
  expect(await page.evaluate(() => typeof window.crypto.getRandomValues)).toBe('function');

  await page.getByPlaceholder('项目名称').fill(title);
  await page.getByRole('button', { name: '＋ 创建研究项目' }).click();
  await expect(page.locator('.map-head h2')).toHaveText(title);

  // A second write (source import) must also succeed with the fallback id.
  await page.getByLabel('来源标题').fill('LAN 资料');
  await page.getByLabel('来源正文').fill('在不安全上下文里也要能写入。');
  await page.getByRole('button', { name: '＋ 添加文本来源' }).click();
  await expect(page.locator('.source-item')).toHaveCount(1);
});
