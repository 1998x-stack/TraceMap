import {test,expect} from '@playwright/test';

const unique=(name:string)=>name+'-'+Date.now()+'-'+Math.random().toString(36).slice(2,7);

async function seedSource(page:import('@playwright/test').Page){
  await page.goto('/');
  await page.getByPlaceholder('项目名称').fill(unique('Academic'));
  await page.getByRole('button',{name:'＋ 创建研究项目'}).click();
  await expect(page.locator('.map-head h2')).toBeVisible();
  await page.getByLabel('来源标题').fill('研究资料 A');
  await page.getByLabel('来源正文').fill('可溯源的结论必须保留原始引用。\n\n学术论证需要人工核验。');
  await page.getByRole('button',{name:'＋ 添加文本来源'}).click();
  await expect(page.locator('.source-item')).toHaveCount(1);
}

test('long-running generation shows honest elapsed time and observed phases, then review',async ({page})=>{
  await page.setViewportSize({width:1440,height:900});
  await seedSource(page);
  await expect(page.locator('.map-panel')).toHaveCSS('background-color','rgb(245, 243, 236)');
  let requests=0;
  await page.route('**/api/v1/projects/*/generate',async route=>{
    requests+=1;
    await new Promise(resolve=>setTimeout(resolve,2200));
    await route.continue();
  });
  const button=page.getByRole('button',{name:'◈ 生成原文结构草稿'});
  await button.click();
  const status=page.getByRole('status',{name:'生成进度'});
  await expect(status).toBeVisible();
  await expect(status).toContainText('请求已发起');
  await expect(status).toContainText('等待结构生成');
  await expect(status).toContainText('计时不是完成百分比');
  await expect(status.locator('.generation-timer')).toContainText('00:01',{timeout:4500});
  await expect(button).toBeDisabled();
  await expect(page.getByRole('dialog',{name:'导图草稿预览'})).toBeVisible({timeout:15000});
  await expect(status).toHaveCount(0);
  expect(requests).toBe(1);
  await expect(page.locator('.node-count')).toContainText('1 NODES');
});

test('server error clears generation status and allows a retry',async ({page})=>{
  await seedSource(page);
  await page.route('**/api/v1/projects/*/generate',async route=>{
    await new Promise(resolve=>setTimeout(resolve,400));
    await route.fulfill({
      status:503,contentType:'application/json',
      body:JSON.stringify({error:{code:'LLM_UNAVAILABLE',message:'模型服务暂时不可用'}}),
    });
  });
  const button=page.getByRole('button',{name:'◈ 生成原文结构草稿'});
  await button.click();
  await expect(page.getByRole('status',{name:'生成进度'})).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('LLM_UNAVAILABLE',{timeout:12000});
  await expect(page.getByRole('status',{name:'生成进度'})).toHaveCount(0);
  await expect(button).toBeEnabled();
  await expect(page.locator('.node-count')).toContainText('1 NODES');
});

test('model mode shows model wait without claiming a fabricated percentage',async ({page})=>{
  await page.route('**/health',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({status:'ok',mode:'development',generationProvider:'llm',
                         generationModel:'iagent/standard',llmConfigured:true}),
  }));
  await seedSource(page);
  await page.route('**/api/v1/projects/*/generate',async route=>{
    await new Promise(resolve=>setTimeout(resolve,1300));
    await route.fulfill({
      status:503,contentType:'application/json',
      body:JSON.stringify({error:{code:'LLM_UNAVAILABLE',message:'演示故障'}}),
    });
  });
  await page.getByRole('button',{name:'◈ 生成候选导图（LLM）'}).click();
  const status=page.getByRole('status',{name:'生成进度'});
  await expect(status).toContainText('等待模型响应');
  await expect(status).toContainText('同步请求');
  await expect(status).not.toContainText('50%');
  // Screenshot is a mocked slow-provider state, not a live model trace.
  await page.screenshot({path:'test-results/ui-generation-progress.png',fullPage:true});
  await expect(page.getByRole('alert')).toContainText('LLM_UNAVAILABLE');
});

test('academic palette remains legible on a phone with the progress panel',async ({page})=>{
  await page.setViewportSize({width:390,height:844});
  await seedSource(page);
  await page.route('**/api/v1/projects/*/generate',async route=>{
    await new Promise(resolve=>setTimeout(resolve,1200));
    await route.continue();
  });
  await page.getByRole('button',{name:'◈ 生成原文结构草稿'}).click();
  await expect(page.getByRole('status',{name:'生成进度'})).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(2);
  await expect(page.getByRole('dialog',{name:'导图草稿预览'})).toBeVisible();
});
