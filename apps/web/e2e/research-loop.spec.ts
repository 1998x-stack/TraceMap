import { test, expect } from '@playwright/test';

test('evidence research loop: source → draft → citation → review patch → undo → export', async ({page,request}) => {
  const title = `E2E-${Date.now()}`;
  await page.goto('/');
  await expect(page.getByText('DEV MODE · dev-alice')).toBeVisible();
  await page.getByPlaceholder('项目名称').fill(title);
  await page.getByRole('button',{name:'＋ 创建研究项目'}).click();
  await expect(page.locator('.map-head h2')).toHaveText(title);

  await page.getByLabel('来源标题').fill('竞争产品介绍');
  await page.getByLabel('来源正文').fill('😀结论需要核验。\n\n第二段资料包含另一种描述。');
  await page.getByRole('button',{name:'＋ 添加文本来源'}).click();
  await expect(page.locator('.source-item')).toHaveCount(1);
  await expect(page.locator('.node-count')).toContainText('1 NODES');

  await page.getByRole('button',{name:'◈ 生成原文结构草稿'}).click();
  await expect(page.getByRole('dialog',{name:'导图草稿预览'})).toBeVisible();
  await expect(page.locator('.node-count')).toContainText('1 NODES');
  await page.getByRole('button',{name:'确认替换地图'}).click();
  await expect(page.locator('.node-count')).toContainText('4 NODES');

  // Choose one claim node and inspect its original Unicode anchor.
  await page.locator('.react-flow__node').filter({hasText:'😀结论需要核验'}).click();
  await expect(page.locator('.evidence-card')).toHaveCount(1);
  await page.locator('.evidence-card').click();
  await expect(page.locator('.quote-context mark')).toHaveText('😀结论需要核验。');

  await page.getByRole('button',{name:'节点详情'}).click();
  await page.getByRole('button',{name:'质疑'}).click();
  const dialog=page.getByRole('dialog',{name:'局部修改预览'});
  await expect(dialog).toBeVisible();
  const checkbox=dialog.locator('input[type=checkbox]');
  await expect(checkbox).not.toBeChecked();
  await expect(page.locator('.node-count')).toContainText('4 NODES');
  await checkbox.check();
  await page.getByRole('button',{name:'确认应用 1 项'}).click();
  await expect(page.locator('.node-count')).toContainText('5 NODES');
  await page.getByRole('button',{name:'↶ 撤销'}).click();
  await expect(page.locator('.node-count')).toContainText('4 NODES');

  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 Markdown ↗'}).click();
  const download=await downloadPromise;
  expect(download.suggestedFilename()).toContain('.md');
});
