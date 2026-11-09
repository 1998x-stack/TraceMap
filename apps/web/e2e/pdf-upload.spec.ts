import { test, expect } from '@playwright/test';

/** Build a minimal, valid multi-page PDF with an extractable text layer. */
function buildTextLayerPdf(pages: string[][]): Buffer {
  const objs = new Map<number, Buffer>();
  objs.set(1, Buffer.from('<< /Type /Catalog /Pages 2 0 R >>'));
  objs.set(3, Buffer.from('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'));
  const kids: string[] = [];
  pages.forEach((lines, k) => {
    const content = 'BT /F1 14 Tf 72 720 Td 18 TL\n' + lines.map((t) => `(${t}) Tj T*`).join('\n') + '\nET';
    const stream = Buffer.from(content, 'latin1');
    const contentNum = 4 + 2 * k;
    const pageNum = 5 + 2 * k;
    kids.push(`${pageNum} 0 R`);
    objs.set(contentNum, Buffer.concat([Buffer.from(`<< /Length ${stream.length} >>\nstream\n`), stream, Buffer.from('\nendstream')]));
    objs.set(pageNum, Buffer.from(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${contentNum} 0 R >>`));
  });
  objs.set(2, Buffer.from(`<< /Type /Pages /Kids [${kids.join(' ')}] /Count ${pages.length} >>`));
  const nums = [...objs.keys()].sort((a, b) => a - b);
  const size = Math.max(...nums) + 1;
  const chunks: Buffer[] = [Buffer.from('%PDF-1.4\n')];
  const offsets = new Map<number, number>();
  let length = chunks[0].length;
  for (const num of nums) {
    offsets.set(num, length);
    const piece = Buffer.concat([Buffer.from(`${num} 0 obj\n`), objs.get(num)!, Buffer.from('\nendobj\n')]);
    chunks.push(piece);
    length += piece.length;
  }
  const xref = length;
  let tail = `xref\n0 ${size}\n0000000000 65535 f \n`;
  for (let num = 1; num < size; num += 1) {
    tail += `${String(offsets.get(num)).padStart(10, '0')} 00000 n \n`;
  }
  tail += `trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  chunks.push(Buffer.from(tail));
  return Buffer.concat(chunks);
}

test('upload a text-layer PDF and read its extracted pages', async ({ page }) => {
  const title = `PDF-${Date.now()}`;
  await page.goto('/');
  await page.getByPlaceholder('项目名称').fill(title);
  await page.getByRole('button', { name: '＋ 创建研究项目' }).click();
  await expect(page.locator('.map-head h2')).toHaveText(title);

  const buffer = buildTextLayerPdf([['TraceMap PDF evidence page one.'], ['Second page statement.']]);
  await page.locator('input[type=file]').setInputFiles({ name: 'sample.pdf', mimeType: 'application/pdf', buffer });

  await expect(page.locator('.source-item')).toHaveCount(1);
  await expect(page.locator('.source-item').first()).toContainText('sample.pdf');
  await expect(page.locator('.node-count')).toContainText('1 NODES');

  // The inspector shows the original (unmodified) extracted paragraphs, per page.
  await page.locator('.source-item').first().click();
  await expect(page.locator('.quote-context')).toHaveCount(2);
  await expect(page.locator('.quote-context').first()).toContainText('TraceMap PDF evidence page one.');
  await expect(page.locator('.quote-context').first()).toContainText('第 1 页');
  await expect(page.locator('.quote-context').nth(1)).toContainText('第 2 页');
});
