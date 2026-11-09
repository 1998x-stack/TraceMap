import { test, expect } from '@playwright/test';

const unique = (label:string) => `${label}-${Date.now()}-${Math.random().toString(36).slice(2,6)}`;

/** Visual checks are genuine Chromium screenshots, not generated mockups. */
test('desktop workspace has readable evidence hierarchy, review-safe dialog and diagram', async ({page}) => {
  await page.setViewportSize({width: 1600, height: 950});
  await page.goto('/');
  await expect(page.getByText('EVIDENCE WORKSPACE')).toBeVisible();
  await page.getByPlaceholder('项目名称').fill(unique('桌面研究'));
  await page.getByRole('button',{name:'＋ 创建研究项目'}).click();
  await expect(page.locator('.map-head h2')).toBeVisible();
  await page.getByLabel('来源标题').fill('访谈记录');
  await page.getByLabel('来源正文').fill('产品经理希望每个结论都能回到原始资料。\n\n团队希望在修改观点之前检查差异。');
  await page.getByRole('button',{name:'＋ 添加文本来源'}).click();
  await page.getByRole('button',{name:'◈ 生成原文结构草稿'}).click();
  await expect(page.getByRole('dialog',{name:'导图草稿预览'})).toBeVisible();
  await expect(page.locator('.node-count')).toHaveText('1 NODES');
  await page.getByRole('button',{name:'确认替换地图'}).click();
  await expect(page.locator('.research-node')).toHaveCount(4);
  await expect(page.locator('.react-flow__node').last()).toBeInViewport();
  await expect(page.getByText('02 / REASONING CANVAS')).toBeVisible();
  await page.screenshot({path:'test-results/ui-desktop.png',fullPage:true});
  await page.locator('.react-flow__node').filter({hasText:'产品经理希望每个结论'}).click();
  await expect(page.locator('.evidence-card')).toHaveCount(1);
  await page.locator('.evidence-card').click();
  await expect(page.locator('.quote-context mark')).toContainText('产品经理希望每个结论');
  await page.getByRole('tab',{name:'节点详情'}).click();
  await page.getByRole('button',{name:'质疑'}).click();
  const review=page.getByRole('dialog',{name:'局部修改预览'});
  await expect(review).toBeVisible();
  await expect(review.getByText('候选修改不会直接写入地图。')).toBeVisible();
  await expect(review.locator('input[type="checkbox"]')).not.toBeChecked();
  await page.keyboard.press('Escape');
  await expect(review).not.toBeVisible();
});

test('mobile: project creation and source input remain usable without horizontal page overflow', async ({page}) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.getByPlaceholder('项目名称')).toBeVisible();
  await page.getByPlaceholder('项目名称').fill(unique('移动研究'));
  await page.getByRole('button',{name:'＋ 创建研究项目'}).click();
  await expect(page.locator('.map-head h2')).toBeVisible();
  await expect(page.getByLabel('来源标题')).toBeVisible();
  await page.getByLabel('来源标题').fill('移动测试');
  await page.getByLabel('来源正文').fill('手机用户需要看到可追踪的证据。');
  await page.getByRole('button',{name:'＋ 添加文本来源'}).click();
  await expect(page.locator('.source-item')).toHaveCount(1);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(2);
  await expect(page.locator('.react-flow__node')).toHaveCount(1);
  // Mobile pages are deliberately stacked and taller than one browser viewport.
  // Assert visibility *inside the canvas*, not intersection with the window's
  // current vertical scroll position.
  const geometry=await page.evaluate(()=>{
    const node=document.querySelector('.react-flow__node')?.getBoundingClientRect();
    const canvas=document.querySelector('.canvas-container')?.getBoundingClientRect();
    const status=node?getComputedStyle(document.querySelector('.react-flow__node')!).visibility:null;
    return node&&canvas?{left:node.left,right:node.right,top:node.top,bottom:node.bottom,width:node.width,height:node.height,
      canvasLeft:canvas.left,canvasRight:canvas.right,canvasTop:canvas.top,canvasBottom:canvas.bottom,visibility:status}:null;
  });
  console.log('MOBILE_CANVAS_BOUNDS',JSON.stringify(geometry));
  expect(geometry).not.toBeNull();
  expect(geometry!.visibility).toBe('visible');
  expect(geometry!.width).toBeGreaterThan(100);
  expect(geometry!.right).toBeGreaterThan(geometry!.canvasLeft);
  expect(geometry!.left).toBeLessThan(geometry!.canvasRight);
  expect(geometry!.bottom).toBeGreaterThan(geometry!.canvasTop);
  expect(geometry!.top).toBeLessThan(geometry!.canvasBottom);
  await page.screenshot({path:'test-results/ui-mobile.png',fullPage:true});
});
