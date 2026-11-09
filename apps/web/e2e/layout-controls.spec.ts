import {test,expect} from '@playwright/test';

const unique=(name:string)=>name+'-'+Date.now()+'-'+Math.random().toString(36).slice(2,7);

async function createWorkspace(page:import('@playwright/test').Page){
  await page.goto('/');
  const title=unique('Layout');
  await page.getByPlaceholder('项目名称').fill(title);
  await page.getByRole('button',{name:'＋ 创建研究项目'}).click();
  await expect(page.locator('.map-head h2')).toHaveText(title);
  return title;
}

test('project rail, source library and evidence inspector collapse independently',async ({page})=>{
  await page.setViewportSize({width:1600,height:950});
  const title=await createWorkspace(page);

  await page.getByRole('button',{name:'折叠项目导航'}).click();
  await expect(page.locator('.rail')).toHaveClass(/is-collapsed/);
  await expect(page.getByRole('button',{name:'打开项目：'+title})).toBeVisible();
  await page.getByRole('button',{name:'展开项目导航'}).click();
  await expect(page.locator('.rail')).not.toHaveClass(/is-collapsed/);

  await page.getByRole('button',{name:'折叠研究资料侧栏'}).click();
  await expect(page.locator('.source-panel')).toHaveClass(/is-collapsed/);
  await expect(page.getByRole('button',{name:'展开研究资料侧栏'})).toBeVisible();
  await page.getByRole('button',{name:'展开研究资料侧栏'}).click();
  await expect(page.locator('.source-panel')).not.toHaveClass(/is-collapsed/);

  await page.getByRole('button',{name:'折叠证据检查侧栏'}).click();
  await expect(page.locator('.inspector')).toHaveClass(/is-collapsed/);
  await page.getByRole('button',{name:'展开证据检查侧栏'}).click();
  await expect(page.locator('.inspector')).not.toHaveClass(/is-collapsed/);

  // Both work panels can stay collapsed at once without sacrificing the canvas.
  await page.getByRole('button',{name:'折叠研究资料侧栏'}).click();
  await page.getByRole('button',{name:'折叠证据检查侧栏'}).click();
  await expect(page.locator('.map-panel')).toBeVisible();
  await expect(page.locator('.studio')).toHaveClass(/source-collapsed/);
  await expect(page.locator('.studio')).toHaveClass(/inspector-collapsed/);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(2);
});

test('fullscreen focus mode works when browser Fullscreen API is unavailable and Escape exits',async ({page})=>{
  await page.addInitScript(()=>{
    Object.defineProperty(HTMLElement.prototype,'requestFullscreen',{
      configurable:true,value:()=>Promise.reject(new Error('fullscreen is blocked in this context')),
    });
  });
  await page.setViewportSize({width:1440,height:900});
  await createWorkspace(page);
  await page.getByRole('button',{name:'全屏显示画布'}).click();
  const canvas=page.locator('.map-panel');
  await expect(canvas).toHaveClass(/is-canvas-fullscreen/);
  await expect(canvas).toHaveCSS('position','fixed');
  await expect(page.getByRole('button',{name:'退出画布全屏'})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(canvas).not.toHaveClass(/is-canvas-fullscreen/);
  await expect(page.getByRole('button',{name:'全屏显示画布'})).toBeVisible();
});

test('mobile can collapse each sidebar and fullscreen restores the graph canvas',async ({page})=>{
  await page.addInitScript(()=>{
    Object.defineProperty(HTMLElement.prototype,'requestFullscreen',{
      configurable:true,value:()=>Promise.reject(new Error('fullscreen unavailable')),
    });
  });
  await page.setViewportSize({width:390,height:844});
  await createWorkspace(page);

  await page.getByRole('button',{name:'折叠项目导航'}).click();
  await expect(page.locator('.rail')).toHaveCSS('height','66px');
  await page.getByRole('button',{name:'展开项目导航'}).click();

  await page.getByRole('button',{name:'折叠研究资料侧栏'}).click();
  await expect(page.locator('.source-panel')).toHaveCSS('height','44px');
  await page.getByRole('button',{name:'展开研究资料侧栏'}).click();
  await page.getByRole('button',{name:'折叠证据检查侧栏'}).click();
  await expect(page.locator('.inspector')).toHaveCSS('height','44px');
  await page.getByRole('button',{name:'展开证据检查侧栏'}).click();

  await page.getByRole('button',{name:'全屏显示画布'}).click();
  const canvas=page.locator('.map-panel');
  await expect(canvas).toHaveClass(/is-canvas-fullscreen/);
  await expect(page.locator('.mobile-outline')).toBeHidden();
  await expect(page.locator('.canvas-container .react-flow')).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(2);
  await page.getByRole('button',{name:'退出画布全屏'}).click();
  await expect(canvas).not.toHaveClass(/is-canvas-fullscreen/);
  await expect(page.locator('.mobile-outline')).toBeVisible();
});
